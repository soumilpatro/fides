import base64
import hashlib

import pytest
from app.auth.tokens import digest_matches, generate_token, token_digest


@pytest.mark.parametrize("kind,prefix", [("access", "fda_"), ("refresh", "fdr_")])
def test_exact_entropy_encoding_and_hash(kind, prefix, monkeypatch):
    calls = []

    def entropy(size):
        calls.append(size)
        return bytes(range(32))

    monkeypatch.setattr("app.auth.tokens.secrets.token_bytes", entropy)
    token = generate_token(kind)
    assert calls == [32]
    assert token == prefix + base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    assert len(token) == 47 and token.isascii()
    digest = token_digest(token, kind)
    assert len(digest) == 32 and digest == hashlib.sha256(token.encode()).digest()
    assert digest_matches(digest, digest)
    assert not digest_matches(digest, bytes(32))


@pytest.mark.parametrize("kind", ["access", "refresh"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        123,
        "",
        "fda_",
        "fdr_",
        "fda_" + "A" * 42,
        "fda_" + "A" * 44,
        "fda_" + "A" * 42 + "B",
        "fdr_" + "A" * 42 + "B",
        "fda_" + "A" * 42 + "=",
        "fdr_" + "A" * 42 + "/",
        "fda_" + "é" * 43,
        "fda_" + "A" * 43 + "\n",
        " fda_" + "A" * 43,
    ],
)
def test_malformed_and_noncanonical(value, kind):
    with pytest.raises(ValueError, match="Invalid credential representation"):
        token_digest(value, kind)


def test_independent_tokens_and_cross_type():
    access, refresh = generate_token("access"), generate_token("refresh")
    assert access[4:] != refresh[4:]
    with pytest.raises(ValueError):
        token_digest(access, "refresh")
    with pytest.raises(ValueError):
        token_digest(refresh, "access")


@pytest.mark.parametrize("kind,prefix", [("access", "fda_"), ("refresh", "fdr_")])
@pytest.mark.parametrize("suffix", ["=", "+", "/", "\t", "\r", "\n", " ", "Ａ"])
def test_canonical_token_rejects_padding_whitespace_and_alphabet_tricks(kind, prefix, suffix):
    with pytest.raises(ValueError):
        token_digest(prefix + "A" * 43 + suffix, kind)
    with pytest.raises(ValueError):
        token_digest(prefix + "A" * 42 + suffix, kind)


@pytest.mark.parametrize("kind", ["access", "refresh"])
def test_all_noncanonical_pad_bits_rejected(kind):
    token = generate_token(kind)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final = alphabet.index(token[-1])
    assert final % 4 == 0
    assert len(base64.urlsafe_b64decode(token[4:] + "=")) == 32
    for low_bits in [1, 2, 3]:
        noncanonical = token[:-1] + alphabet[final + low_bits]
        with pytest.raises(ValueError):
            token_digest(noncanonical, kind)
