"""Small declarative validator (Pydantic was unavailable offline; see docs)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .errors import validation_error

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SEMVER = re.compile(r"^(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def is_safe_id(v: Any) -> bool:
    return isinstance(v, str) and bool(SAFE_ID.match(v)) and ".." not in v


def semver_tuple(v: str) -> tuple[int, int, int]:
    m = SEMVER.match(v)
    if not m:
        raise ValueError(f"invalid version {v!r}")
    return int(m[1]), int(m[2]), int(m[3])


@dataclass
class Field:
    type: type | tuple
    required: bool = True
    check: Callable[[Any], bool] | None = None
    message: str = "invalid value"
    max_len: int | None = None


def validate(payload: Any, schema: dict[str, Field], allow_extra: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise validation_error([{"field": "$", "message": "expected a JSON object"}])
    errors, out = [], {}
    for name, f in schema.items():
        if name not in payload or payload[name] is None:
            if f.required:
                errors.append({"field": name, "message": "field required"})
            continue
        v = payload[name]
        if isinstance(v, bool) and f.type in (int, float, (int, float)):
            errors.append({"field": name, "message": "expected number"})
            continue
        if not isinstance(v, f.type):
            errors.append({"field": name, "message": f"expected {getattr(f.type, '__name__', 'value')}"})
            continue
        if f.max_len is not None and hasattr(v, "__len__") and len(v) > f.max_len:
            errors.append({"field": name, "message": f"longer than {f.max_len}"})
            continue
        if f.check and not f.check(v):
            errors.append({"field": name, "message": f.message})
            continue
        out[name] = v
    if not allow_extra:
        for k in payload:
            if k not in schema:
                errors.append({"field": k, "message": "unexpected field"})
    if errors:
        raise validation_error(errors)
    return out


def pagination(args) -> tuple[int, int]:
    try:
        limit = int(args.get("limit", 50))
        offset = int(args.get("offset", 0))
    except ValueError:
        raise validation_error([{"field": "limit/offset", "message": "must be integers"}])
    if not (1 <= limit <= 200) or offset < 0:
        raise validation_error([{"field": "limit/offset", "message": "limit 1..200, offset >= 0"}])
    return limit, offset
