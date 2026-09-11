import hashlib
import hmac
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from app.auth.rate_limits import RateLimiter, client_ip, subject_digest
from app.core.errors import AuthError
from app.models.auth_rate_limit_bucket import AuthRateLimitBucket
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

POLICIES = [
    ("otp_request", "otp_request_phone_10m", 3, 600),
    ("otp_request", "otp_request_phone_24h", 10, 86400),
    ("otp_request", "otp_request_ip_10m", 20, 600),
    ("otp_request", "otp_request_ip_24h", 100, 86400),
    ("otp_verify", "otp_verify_phone_10m", 10, 600),
    ("otp_verify", "otp_verify_ip_1m", 30, 60),
    ("otp_verify", "otp_verify_ip_1h", 200, 3600),
    ("auth_refresh", "auth_refresh_session_1m", 10, 60),
    ("auth_refresh", "auth_refresh_ip_1m", 60, 60),
]


@pytest.mark.parametrize("operation,name,limit,seconds", POLICIES)
def test_every_policy_boundary_retry_and_rollover(engine_env, operation, name, limit, seconds):
    env = engine_env
    limiter = env.limiter
    policies = limiter.policies(operation, phone="+14155552671", ip="192.0.2.1", session_id=uuid4())
    policy = next(policy for policy in policies if policy.name == name)
    assert (policy.limit, policy.seconds) == (limit, seconds)
    # Midnight is aligned for all approved UTC fixed windows.
    env.clock.now = env.clock.now.replace(hour=0)
    start = env.clock.now
    env.clock.now += timedelta(seconds=0.25)
    for _ in range(limit):
        limiter.enforce([policy], "AUTH_RATE_LIMITED")
    with pytest.raises(AuthError) as error:
        limiter.enforce([policy], "AUTH_RATE_LIMITED")
    assert error.value.code == "AUTH_RATE_LIMITED"
    assert error.value.headers["Retry-After"] == str(seconds)
    with env.factory() as db:
        bucket = db.scalar(
            select(AuthRateLimitBucket).where(
                AuthRateLimitBucket.policy == name,
                AuthRateLimitBucket.subject_hash == policy.subject,
            )
        )
        assert bucket.request_count == limit and bucket.window_started_at == start
        assert bucket.expires_at == start + timedelta(seconds=seconds)
    env.clock.now = start + timedelta(seconds=seconds)
    limiter.enforce([policy], "AUTH_RATE_LIMITED")
    with env.factory() as db:
        rows = db.scalars(
            select(AuthRateLimitBucket)
            .where(
                AuthRateLimitBucket.policy == name,
                AuthRateLimitBucket.subject_hash == policy.subject,
            )
            .order_by(AuthRateLimitBucket.window_started_at)
        ).all()
        assert [row.request_count for row in rows] == [limit, 1]


def test_configurable_limits_and_longest_blocker_durable_denials(engine_env):
    env = engine_env
    settings = env.settings.model_copy(
        update={"otp_request_phone_10m_limit": 1, "otp_request_phone_24h_limit": 1}
    )
    limiter = RateLimiter(env.factory, settings, clock=env.clock)
    kwargs = {"phone": "+14155552671", "ip": "192.0.2.1"}
    limiter.otp_request(**kwargs)
    with pytest.raises(AuthError) as error:
        limiter.otp_request(**kwargs)
    assert error.value.code == "OTP_RATE_LIMITED"
    assert error.value.headers["Retry-After"] == "43200"
    with env.factory() as db:
        ip_rows = db.scalars(
            select(AuthRateLimitBucket).where(
                AuthRateLimitBucket.subject_hash == limiter.subject("ip", kwargs["ip"])
            )
        ).all()
        assert len(ip_rows) == 2 and all(row.request_count == 2 for row in ip_rows)


def test_shared_phone_across_intents_and_provider_failure(engine_env):
    env = engine_env
    # No intent exists in the limiter API/key. Requests from either flow share it.
    for _intent in ["signup", "login", "signup"]:
        env.limiter.otp_request(phone="+14155552671", ip="192.0.2.1")
        with env.factory() as db:
            db.rollback()  # represents a failed downstream provider/challenge transaction
    with pytest.raises(AuthError, match="OTP_RATE_LIMITED"):
        env.limiter.otp_request(phone="+14155552671", ip="192.0.2.2")
    with env.factory() as db:
        rows = db.scalars(
            select(AuthRateLimitBucket).where(
                AuthRateLimitBucket.subject_hash == env.limiter.subject("phone", "+14155552671")
            )
        ).all()
        assert {row.request_count for row in rows} == {3, 4}
        assert all(len(row.subject_hash) == 32 for row in rows)
        assert "+14155552671" not in str([row.__dict__ for row in rows])


def test_unknown_verification_counts_ip_only(engine_env):
    env = engine_env
    env.limiter.otp_verify(ip="192.0.2.1")
    with env.factory() as db:
        rows = db.scalars(
            select(AuthRateLimitBucket).where(
                AuthRateLimitBucket.subject_hash == env.limiter.subject("ip", "192.0.2.1")
            )
        ).all()
        assert {row.policy for row in rows} == {"otp_verify_ip_1m", "otp_verify_ip_1h"}


def test_hmac_domains_normalization_and_key_rotation():
    secret = "test-secret"
    phone = subject_digest(secret, "phone", " +14155552671 ")
    assert phone == hmac.digest(secret.encode(), b"fides:auth:v1:phone\0+14155552671", "sha256")
    assert phone != hashlib.sha256(b"+14155552671").digest()
    assert phone != subject_digest("another-secret", "phone", "+14155552671")
    identifier = uuid4()
    assert subject_digest(secret, "session", identifier) == subject_digest(
        secret, "session", str(identifier)
    )
    assert (
        len(
            {
                phone,
                subject_digest(secret, "ip", "192.0.2.1"),
                subject_digest(secret, "session", identifier),
            }
        )
        == 3
    )
    assert subject_digest(secret, "ip", "2001:db8:abcd:1234::1") == subject_digest(
        secret, "ip", "2001:db8:abcd:1234:ffff::2"
    )
    assert subject_digest(secret, "ip", "2001:db8:abcd:1234::1") != subject_digest(
        secret, "ip", "2001:db8:abcd:1235::1"
    )
    assert subject_digest(secret, "ip", "192.0.2.1") != subject_digest(secret, "ip", "192.0.2.2")
    assert subject_digest(secret, "ip", "::ffff:192.0.2.1") == subject_digest(
        secret, "ip", "192.0.2.1"
    )
    with pytest.raises(ValueError):
        subject_digest("", "phone", "+14155552671")
    with pytest.raises(ValueError):
        subject_digest(secret, "signup", "+14155552671")


@pytest.mark.parametrize(
    "peer,xff,trusted,expected",
    [
        ("192.0.2.1", "198.51.100.1", (), "192.0.2.1"),
        ("192.0.2.1", "malicious", ("10.0.0.0/8",), "192.0.2.1"),
        ("10.0.0.1", "192.0.2.5", ("10.0.0.0/8",), "192.0.2.5"),
        ("10.0.0.1", "forged, 192.0.2.5, 10.0.0.2", ("10.0.0.0/8",), "192.0.2.5"),
        ("::ffff:192.0.2.1", None, (), "192.0.2.1"),
        ("2001:db8::1", None, (), "2001:db8::1"),
    ],
)
def test_proxy_trust(peer, xff, trusted, expected):
    assert client_ip(peer, xff, trusted_proxies=trusted) == expected


@pytest.mark.parametrize("value", ["bad", "", "192.0.2.1:80", "fe80::1%eth0", "," * 33])
def test_invalid_trusted_proxy_input_fails_closed(value):
    with pytest.raises(ValueError):
        client_ip("10.0.0.1", value, trusted_proxies=["10.0.0.0/8"])


def test_concurrent_limiter_instances_do_not_exceed_limit(engine_env):
    env = engine_env
    gate = threading.Barrier(8, timeout=10)

    def attempt(index):
        limiter = RateLimiter(env.factory, env.settings, clock=env.clock)
        policies = limiter.policies("otp_request", phone="+14155552671", ip="192.0.2.1")
        # Reverse input order for half the callers to exercise deterministic locking.
        gate.wait()
        try:
            limiter.enforce(policies if index % 2 else policies[::-1], "OTP_RATE_LIMITED")
            return "allowed"
        except AuthError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(8)))
    assert results.count("allowed") == 3
    assert results.count("OTP_RATE_LIMITED") == 5


def test_storage_failure_fails_closed(engine_env, monkeypatch):
    def fail():
        raise OperationalError("secret SQL", {}, Exception("connection secret"))

    with monkeypatch.context() as patch:
        patch.setattr(engine_env.limiter.sessions, "begin", fail)
        with pytest.raises(AuthError) as error:
            engine_env.limiter.otp_request(phone="+14155552671", ip="192.0.2.1")
    assert error.value.code == "SERVICE_UNAVAILABLE"
    assert "secret" not in str(error.value)


def test_multi_policy_storage_failure_is_atomic(engine_env):
    env = engine_env
    engine = env.factory.kw["bind"]
    inserts = 0

    def fail_second_insert(connection, cursor, statement, parameters, context, executemany):
        nonlocal inserts
        if statement.startswith("INSERT INTO auth_rate_limit_buckets"):
            inserts += 1
            if inserts == 2:
                raise OperationalError("test failure", {}, Exception())

    event.listen(engine, "before_cursor_execute", fail_second_insert)
    try:
        with pytest.raises(AuthError, match="SERVICE_UNAVAILABLE"):
            env.limiter.otp_request(phone="+14155552671", ip="192.0.2.1")
    finally:
        event.remove(engine, "before_cursor_execute", fail_second_insert)
    with env.factory() as db:
        assert not db.scalars(
            select(AuthRateLimitBucket).where(
                AuthRateLimitBucket.subject_hash.in_(
                    [
                        env.limiter.subject("phone", "+14155552671"),
                        env.limiter.subject("ip", "192.0.2.1"),
                    ]
                )
            )
        ).all()


def test_verification_phone_budget_shared_across_intents_and_ips(engine_env):
    env = engine_env
    for index in range(10):
        env.limiter.otp_verify(phone="+14155552671", ip=f"192.0.2.{index + 1}")
    with pytest.raises(AuthError, match="OTP_RATE_LIMITED"):
        env.limiter.otp_verify(phone="+14155552671", ip="192.0.2.99")


def test_empty_policies_cannot_silently_allow(engine_env):
    with pytest.raises(ValueError, match="At least one"):
        engine_env.limiter.enforce([], "AUTH_RATE_LIMITED")


@pytest.mark.parametrize("cidr", ["10.1.2.3/8", "2001:db8::1/32", "bad", "10.0.0.0/99"])
def test_proxy_allowlist_rejects_malformed_networks(cidr):
    with pytest.raises(ValueError):
        client_ip("192.0.2.1", "198.51.100.1", trusted_proxies=[cidr])


def test_equivalent_ipv6_text_has_same_subject():
    assert subject_digest("secret", "ip", "2001:DB8:ABCD:1234::1") == subject_digest(
        "secret", "ip", "2001:0db8:abcd:1234:0000:0000:0000:0001"
    )
