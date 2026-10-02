from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.extension_request import ExtensionRequest
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.notification_event import NotificationEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from sqlalchemy import select

MODELS = (
    Commitment,
    CommitmentTermsVersion,
    CommitmentInstallment,
    Repayment,
    RepaymentVerification,
    ExtensionRequest,
    LedgerEvent,
    AuditLog,
    NotificationEvent,
    IdempotencyKey,
)
OPERATIONS = (
    "create",
    "confirm",
    "reject",
    "cancel",
    "report",
    "verify",
    "dispute",
    "extension-create",
    "extension-accept",
    "extension-reject",
)


def snapshot(env):
    with env.api.factory() as db:
        return {m.__name__: list(db.execute(select(m.__table__).order_by(m.id))) for m in MODELS}


def operation(env, name, key="b13-recovery"):
    """Set up once; retries always use precisely the same endpoint/key/body."""
    if name in ("create", "confirm", "reject", "cancel"):
        actor = "A" if name in ("create", "cancel") else "B"
        suffix = ""
        if name != "create":
            proposed = env.request("POST", json=env.body)
            assert proposed.status_code == 201
            suffix = f"/{proposed.json()['id']}/{name}"
        return lambda: env.request(
            "POST", suffix, actor=actor, key=key, json=env.body if name == "create" else {}
        )
    if name == "report":
        return lambda: env.report(parent=env.identifier, key=key)
    if name in ("verify", "dispute"):
        return lambda: env.financial.decide(action=name, key=key)
    if name == "extension-create":
        return lambda: env.create(key=key)
    created = env.create()
    assert created.status_code == 201
    return lambda: env.decide(created.json()["id"], name.split("-")[1], key=key)


def assert_effects(before, after, operation, *, idempotency_addition=1):
    additions = {
        "LedgerEvent": 1,
        "AuditLog": 1,
        "NotificationEvent": 1,
        "IdempotencyKey": idempotency_addition,
    }
    if operation == "create":
        additions.update(Commitment=1, CommitmentTermsVersion=1)
    elif operation == "report":
        additions["Repayment"] = 1
    elif operation in ("verify", "dispute"):
        additions["RepaymentVerification"] = 1
    elif operation == "extension-create":
        additions["ExtensionRequest"] = 1
    elif operation == "extension-accept":
        additions["CommitmentTermsVersion"] = 1
    for name in before:
        assert len(after[name]) - len(before[name]) == additions.get(name, 0), name
    for name in (
        "LedgerEvent",
        "AuditLog",
        "NotificationEvent",
        "CommitmentTermsVersion",
        "CommitmentInstallment",
        "RepaymentVerification",
    ):
        assert all(row in after[name] for row in before[name]), name


def race(*actions):
    barrier = Barrier(len(actions))

    def run(action):
        barrier.wait(10)
        return action()

    with ThreadPoolExecutor(len(actions)) as pool:
        return [future.result(20) for future in [pool.submit(run, action) for action in actions]]


def parent(env):
    return UUID(env.identifier)
