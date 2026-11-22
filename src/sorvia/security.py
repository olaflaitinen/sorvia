"""Password hashing (scrypt) and JSON Web Tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any

import jwt

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# A hash of a random password; used to keep login timing constant for unknown users.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str
    branch_id: int | None

    @property
    def all_branches(self) -> bool:
        return self.role in ("admin", "manager") and self.branch_id is None


def issue_token(principal: Principal, secret: str, ttl_minutes: int) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(principal.user_id),
        "usr": principal.username,
        "role": principal.role,
        "branch": principal.branch_id,
        "iat": now,
        "exp": now + ttl_minutes * 60,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> Principal:
    payload = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "exp", "iat"]})
    branch = payload.get("branch")
    return Principal(
        user_id=int(payload["sub"]),
        username=str(payload["usr"]),
        role=str(payload["role"]),
        branch_id=int(branch) if branch is not None else None,
    )
