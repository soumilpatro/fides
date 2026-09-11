"""Opaque, typed credentials. Plaintext exists only during issuance/presentation."""

import base64
import hashlib
import hmac
import re
import secrets
from typing import Literal

TokenKind = Literal["access", "refresh"]
_PREFIX = {"access": "fda_", "refresh": "fdr_"}


def generate_token(kind: TokenKind) -> str:
    return _PREFIX[kind] + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def token_digest(credential: object, kind: TokenKind) -> bytes:
    """Validate before hashing; round-trip catches otherwise valid nonzero pad bits."""
    if not isinstance(credential, str) or not re.fullmatch(
        re.escape(_PREFIX[kind]) + r"[A-Za-z0-9_-]{43}", credential, flags=re.ASCII
    ):
        raise ValueError("Invalid credential representation")
    encoded = credential[4:]
    decoded = base64.urlsafe_b64decode(encoded + "=")
    if base64.urlsafe_b64encode(decoded).decode().rstrip("=") != encoded:
        raise ValueError("Invalid credential representation")
    return hashlib.sha256(credential.encode("ascii")).digest()


def digest_matches(presented: bytes, stored: bytes) -> bool:
    return hmac.compare_digest(presented, stored)
