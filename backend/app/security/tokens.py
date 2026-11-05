"""Short-lived JWT access tokens (HS256) and opaque device tokens."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid

import jwt

ISSUER = "autolink-ota"
AUDIENCE = "autolink-dashboard"


def issue_access_token(secret: str, user_id: str, role: str, ttl_s: int) -> str:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": user_id, "role": role, "typ": "access",
              "iat": now, "nbf": now, "exp": now + ttl_s, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_access_token(secret: str, token: str) -> dict:
    """Raises jwt.PyJWTError on any problem. Algorithm is pinned (no 'none'/alg confusion)."""
    claims = jwt.decode(token, secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
                        options={"require": ["exp", "iat", "sub", "typ"]})
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return claims


def new_device_token() -> str:
    return secrets.token_urlsafe(32)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def device_token_matches(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_device_token(token), stored_hash)
