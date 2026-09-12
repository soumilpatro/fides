from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.auth.sessions import Principal
from app.core.errors import AuthError, ResourceUnavailable
from app.models.enums import UserStatus
from app.models.user import User

KINDS = ["commitment", "repayment", "verification", "ledger_event", "extension_request"]


def lookup(graph, kind, actor, identifier=None, *, group=0, lock=False):
    resource_id = identifier if identifier is not None else graph.groups[group][kind]
    with graph.factory.begin() as db:
        return getattr(graph.authorization, kind)(
            db, graph.principals[actor], resource_id, lock=lock
        )


@pytest.mark.parametrize("actor", ["A", "B"])
def test_connection_either_participant_allowed(graph, actor):
    access = lookup(graph, "connection", actor, graph.connection_ab)
    assert access.resource_id == graph.connection_ab and access.role == "participant"
    assert access.commitment_id is None


def test_connection_unrelated_denied(graph):
    with pytest.raises(ResourceUnavailable):
        lookup(graph, "connection", "C", graph.connection_ab)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("actor,role", [("A", "lender"), ("C", "borrower")])
@pytest.mark.parametrize("lock", [False, True])
def test_direct_financial_participants_and_roles(graph, kind, actor, role, lock):
    access = lookup(graph, kind, actor, lock=lock)
    assert access.resource_id == graph.groups[0][kind]
    assert access.commitment_id == graph.groups[0]["commitment"] and access.role == role
    if kind in ("repayment", "verification"):
        assert access.repayment_id == graph.groups[0]["repayment"]


@pytest.mark.parametrize("kind", KINDS)
def test_connected_reporter_verifier_actor_requester_has_no_financial_access(graph, kind):
    assert lookup(graph, "connection", "B", graph.connection_ab)
    assert lookup(graph, kind, "B", group=2).role == "borrower"
    with pytest.raises(ResourceUnavailable, match="NOT_FOUND"):
        lookup(graph, kind, "B", group=0)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("actor,role", [("A", "borrower"), ("C", "lender")])
def test_reverse_direction_and_independent_commitments(graph, kind, actor, role):
    first = lookup(graph, kind, actor, group=0)
    second = lookup(graph, kind, actor, group=1)
    assert first.commitment_id != second.commitment_id
    assert first.role != second.role and second.role == role


@pytest.mark.parametrize("kind", ["connection", *KINDS])
def test_missing_and_existing_unavailable_have_identical_error(graph, kind):
    actor = "C" if kind == "connection" else "B"
    existing = graph.connection_ab if kind == "connection" else graph.groups[0][kind]
    errors = []
    for identifier in (existing, uuid4()):
        with pytest.raises(ResourceUnavailable) as captured:
            lookup(graph, kind, actor, identifier)
        errors.append((captured.value.code, captured.value.message, str(captured.value)))
    assert errors[0] == errors[1] == ("NOT_FOUND", "Unavailable resource.", "NOT_FOUND")


def test_history_authorization_is_bound_to_its_exact_parent(graph):
    repayment = lookup(graph, "repayment", "B", group=2)
    ledger = lookup(graph, "commitment", "B", group=2)
    assert repayment.repayment_id == graph.groups[2]["repayment"]
    assert ledger.commitment_id == graph.groups[2]["commitment"]
    for kind in ("repayment", "commitment", "verification", "ledger_event"):
        with pytest.raises(ResourceUnavailable):
            lookup(graph, kind, "B", group=0)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        SimpleNamespace(user_id=uuid4()),
        Principal(uuid4(), uuid4(), b"short"),
        Principal("bad", uuid4(), b"x" * 32),
    ],
)
def test_principal_like_input_cannot_bypass_b2(graph, bad):
    with graph.factory.begin() as db, pytest.raises(AuthError, match="INVALID_AUTH_TOKEN"):
        graph.authorization.commitment(db, bad, graph.groups[0]["commitment"])


@pytest.mark.parametrize("change", ["user_id", "session_id", "_digest"])
def test_mismatched_principal_is_revalidated(graph, change):
    principal = replace(
        graph.principals["B"],
        **{
            change: graph.users["A"]
            if change == "user_id"
            else uuid4()
            if change == "session_id"
            else b"x" * 32
        },
    )
    with graph.factory.begin() as db, pytest.raises(AuthError, match="INVALID_AUTH_TOKEN"):
        graph.authorization.commitment(db, principal, graph.groups[0]["commitment"])


@pytest.mark.parametrize(
    "case,code",
    [
        ("expired", "AUTH_TOKEN_EXPIRED"),
        ("revoked", "SESSION_REVOKED"),
        ("rotated", "INVALID_AUTH_TOKEN"),
        ("deactivated", "ACCOUNT_DEACTIVATED"),
        ("unavailable", "ACCOUNT_UNAVAILABLE"),
    ],
)
def test_stale_principal_cannot_bypass_current_b2_eligibility(graph, case, code):
    if case == "expired":
        graph.clock.now += timedelta(minutes=15)
    elif case == "revoked":
        graph.service.revoke_one(
            graph.service.recognize_logout("Bearer " + graph.credentials["A"].access_token)
        )
    elif case == "rotated":
        graph.service.refresh(graph.credentials["A"].refresh_token, ip="192.0.2.1")
    else:
        with graph.factory.begin() as db:
            db.get(User, graph.users["A"]).status = (
                UserStatus.DEACTIVATED if case == "deactivated" else UserStatus.ANONYMIZED
            )
    with pytest.raises(AuthError, match=code):
        lookup(graph, "commitment", "A")


def test_no_caller_role_or_actor_override(graph):
    with graph.factory.begin() as db:
        with pytest.raises(TypeError):
            graph.authorization.commitment(
                db,
                graph.principals["B"],
                graph.groups[0]["commitment"],
                actor_user_id=graph.users["A"],
            )
        with pytest.raises(TypeError):
            graph.authorization.commitment(
                db, graph.principals["B"], graph.groups[0]["commitment"], role="lender"
            )
    access = lookup(graph, "commitment", "C")
    with pytest.raises(FrozenInstanceError):
        access.role = "lender"


@pytest.mark.parametrize("identifier", [None, "not-a-uuid", 123, True])
def test_invalid_identifier_never_queries_financial_content(graph, identifier):
    with graph.factory.begin() as db, pytest.raises(AuthError, match="VALIDATION_ERROR"):
        graph.authorization.commitment(db, graph.principals["A"], identifier)
