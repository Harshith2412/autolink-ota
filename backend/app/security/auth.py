"""Request authentication/authorization decorators for users and devices."""
from __future__ import annotations

from functools import wraps

import jwt
from flask import current_app, g, request

from ..errors import forbidden, unauthorized
from . import tokens

ROLE_RANK = {"viewer": 1, "engineer": 2, "admin": 3}


def _bearer() -> str | None:
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.startswith("Bearer ") else None


def require_role(minimum: str):
    """User JWT required; role is re-read from the database on every request so
    revocation/demotion takes effect immediately (claims are not trusted alone)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            token = _bearer()
            if not token:
                raise unauthorized()
            try:
                claims = tokens.decode_access_token(current_app.config["SETTINGS"].jwt_secret, token)
            except jwt.PyJWTError:
                raise unauthorized("invalid or expired token")
            user = current_app.extensions["services"].users.get_active(claims["sub"])
            if user is None:
                raise unauthorized("user disabled or deleted")
            g.user = user
            if ROLE_RANK.get(user["role"], 0) < ROLE_RANK[minimum]:
                current_app.extensions["services"].audit.record(
                    user["username"], "authz.denied", "endpoint", request.path, "DENIED",
                    {"required": minimum, "role": user["role"]})
                raise forbidden()
            return fn(*a, **kw)
        return wrapper
    return deco


def require_device(fn):
    """Device token + X-Vehicle-Id required. Tokens are stored only as SHA-256 hashes."""
    @wraps(fn)
    def wrapper(*a, **kw):
        token, vid = _bearer(), request.headers.get("X-Vehicle-Id", "")
        if not token or not vid:
            raise unauthorized("device credentials required")
        vehicle = current_app.extensions["services"].vehicles.authenticate_device(vid, token)
        if vehicle is None:
            current_app.extensions["services"].audit.record(
                f"vehicle:{vid[:64]}", "device.auth_failed", "vehicle", vid[:64], "DENIED", {})
            raise unauthorized("invalid device credentials")
        g.vehicle = vehicle
        return fn(*a, **kw)
    return wrapper
