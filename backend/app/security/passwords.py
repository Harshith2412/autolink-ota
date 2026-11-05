"""PBKDF2-HMAC-SHA256 password hashing (stdlib). Format: pbkdf2_sha256$iter$salt$hash."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGO = "pbkdf2_sha256"


def hash_password(password: str, iterations: int) -> str:
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{ALGO}${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = encoded.split("$")
        if algo != ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


# Used to equalise timing when the username does not exist.
DUMMY_HASH = f"{ALGO}$1000${base64.b64encode(b'0' * 16).decode()}${base64.b64encode(b'0' * 32).decode()}"
