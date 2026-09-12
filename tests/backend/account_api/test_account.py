from datetime import timedelta

import pytest
from app.models.audit_log import AuditLog
from app.models.auth_identity import AuthIdentity
from app.models.auth_session import AuthSession
from app.models.commitment import Commitment
from app.models.enums import CommitmentStatus, UserStatus
from app.models.user import User
from auth_api.test_api import BASE, PHONE, error, request, verify
from sqlalchemy import select

ME = "/api/v1/me"


def call(account, method="GET", path=ME, **kwargs):
    return account.api.client.request(method, path, headers=account.headers, **kwargs)


def test_get_exact_current_user_and_no_client_authority(account):
    response = call(account, path=ME + "?user_id=" + str(account.other_id))
    assert response.status_code == 200 and response.json() == account.credentials["user"]
    assert set(response.json()) == {
        "id",
        "phone_e164",
        "display_name",
        "timezone",
        "status",
        "created_at",
        "updated_at",
    }
    assert response.headers["Cache-Control"] == "no-store" and response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    "body",
    [
        {"display_name": "  Cafe\u0301  "},
        {"timezone": " Asia/Kolkata "},
        {"display_name": "Updated", "timezone": "Europe/London"},
    ],
)
def test_patch_changed_fields_and_exact_audit(account, body):
    api = account.api
    api.clock.now += timedelta(seconds=1)
    response = call(account, "PATCH", json=body)
    assert response.status_code == 200
    assert response.json()["id"] == str(account.user_id)
    with api.factory() as db:
        user = db.get(User, account.user_id)
        assert user.updated_at == api.clock.now and user.status == UserStatus.ACTIVE
        assert user.phone_e164 == PHONE and user.deactivated_at is None
        if "display_name" in body:
            assert user.display_name == (
                "Café" if body["display_name"].startswith(" ") else "Updated"
            )
        if "timezone" in body:
            assert user.timezone == body["timezone"].strip()
        audits = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "PROFILE_UPDATED", AuditLog.actor_user_id == user.id
            )
        ).all()
        assert len(audits) == 1 and audits[0].object_id == user.id and audits[0].result == "SUCCESS"
        assert audits[0].metadata_ == {
            "changed_fields": sorted(body),
            "request_id": response.headers["X-Request-ID"],
        }


def test_normalized_noop_preserves_timestamp_and_has_no_audit(account):
    account.api.clock.now += timedelta(seconds=5)
    response = call(account, "PATCH", json={"display_name": " Example ", "timezone": " UTC "})
    assert response.status_code == 200 and response.json() == account.credentials["user"]
    with account.api.factory() as db:
        assert not db.scalars(
            select(AuditLog).where(
                AuditLog.action == "PROFILE_UPDATED", AuditLog.actor_user_id == account.user_id
            )
        ).all()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"display_name": None},
        {"timezone": None},
        {"display_name": True},
        {"display_name": 123},
        {"display_name": " "},
        {"display_name": "x\x00y"},
        {"display_name": "x" * 101},
        {"timezone": "Mars/Test"},
        {"phone_e164": PHONE},
        {"id": "12345678-1234-1234-1234-123456789abc"},
        {"status": "ACTIVE"},
        {"deactivated_at": "2026-01-01T00:00:00Z"},
        {"created_at": "2026-01-01T00:00:00Z"},
        {"identities": []},
        {"display_name": "Changed", "extra": 1},
    ],
)
def test_patch_rejects_overposting_null_and_invalid_values(account, body):
    error(call(account, "PATCH", json=body), "VALIDATION_ERROR", 422)
    assert call(account).json() == account.credentials["user"]


@pytest.mark.parametrize("status", list(CommitmentStatus))
@pytest.mark.parametrize("borrower", [False, True])
def test_deactivation_terminal_whitelist_for_both_parties(account, status, borrower):
    identifier = account.commitment(status, borrower=borrower)
    response = call(account, "POST", ME + "/deactivate")
    terminal = status in {
        CommitmentStatus.CLOSED,
        CommitmentStatus.REJECTED,
        CommitmentStatus.CANCELLED,
    }
    if terminal:
        assert response.status_code == 200
    else:
        error(response, "ACCOUNT_HAS_UNRESOLVED_COMMITMENTS", 409)
        assert call(account).status_code == 200
    with account.api.factory() as db:
        assert db.get(Commitment, identifier).status == status
        assert db.get(User, account.user_id).status == (
            UserStatus.DEACTIVATED if terminal else UserStatus.ACTIVE
        )


def test_one_unresolved_among_terminal_commitments_blocks(account):
    account.commitment(CommitmentStatus.CLOSED)
    account.commitment(CommitmentStatus.FULLY_REPAID, borrower=True)
    error(
        call(account, "POST", ME + "/deactivate", json={}),
        "ACCOUNT_HAS_UNRESOLVED_COMMITMENTS",
        409,
    )


def test_deactivation_revokes_all_sessions_preserves_identity_and_denies_future_access(account):
    api = account.api
    other = api.service.create(account.user_id, intent="login")
    previously_revoked = api.service.create(account.user_id, intent="login")
    api.service.revoke_one(
        api.service.recognize_logout("Bearer " + previously_revoked.access_token)
    )
    api.clock.now += timedelta(seconds=1)
    response = call(account, "POST", ME + "/deactivate", json={})
    assert response.status_code == 200 and set(response.json()) == {"status", "deactivated_at"}
    assert response.json()["status"] == "DEACTIVATED" and response.json()[
        "deactivated_at"
    ].endswith("Z")
    with api.factory() as db:
        user = db.get(User, account.user_id)
        assert user.phone_e164 == PHONE and user.deactivated_at == user.updated_at == api.clock.now
        assert (
            db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == user.id)).provider_subject
            == PHONE
        )
        sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
        assert len(sessions) == 3 and all(row.revoked_at for row in sessions)
        assert sorted(row.revocation_reason for row in sessions) == [
            "ACCOUNT_DEACTIVATED",
            "ACCOUNT_DEACTIVATED",
            "LOGOUT",
        ]
        audits = db.scalars(select(AuditLog).where(AuditLog.actor_user_id == user.id)).all()
        assert len([a for a in audits if a.action == "AUTH_SESSION_REVOKED"]) == 3
        deactivated = [a for a in audits if a.action == "ACCOUNT_DEACTIVATED"]
        assert len(deactivated) == 1 and deactivated[0].metadata_["revoked_session_count"] == 2
    error(call(account), "SESSION_REVOKED", 401)
    error(call(account, "POST", ME + "/deactivate"), "SESSION_REVOKED", 401)
    error(
        api.client.get(ME, headers={"Authorization": "Bearer " + other.access_token}),
        "SESSION_REVOKED",
        401,
    )
    error(
        api.client.post(BASE + "/refresh", json={"refresh_token": other.refresh_token}),
        "SESSION_REVOKED",
        401,
    )
    api.clock.now += timedelta(seconds=60)
    challenge = request(api, "login").json()["challenge_id"]
    error(verify(api, challenge, "login"), "ACCOUNT_DEACTIVATED", 403)
