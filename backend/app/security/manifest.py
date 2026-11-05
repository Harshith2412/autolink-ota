"""Server-side firmware manifest validation and Ed25519 verification.

The canonical payload must match ecu/src/manifest.cpp and
firmware/tools/autolink_fw.py byte-for-byte (cross-checked in tests).
"""
from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..validation import SEMVER, SHA256_HEX, is_safe_id

PAYLOAD_FIELDS = ("firmware_id", "version", "hardware_id", "sha256", "size", "security_counter",
                  "min_current_version", "key_id", "release_notes", "simulate_unhealthy")
REQUIRED = {"firmware_id": str, "version": str, "hardware_id": str, "sha256": str, "size": int,
            "security_counter": int, "min_current_version": str, "key_id": str, "signature": str,
            "release_notes": str, "simulate_unhealthy": bool}


class ManifestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def signing_payload(m: dict) -> bytes:
    parts = ["AUTOLINK-FW-MANIFEST-V1\n"]
    for name in PAYLOAD_FIELDS:
        v = m[name]
        s = ("true" if v else "false") if isinstance(v, bool) else str(v)
        parts.append(f"{name}={len(s.encode())}:{s}\n")
    return "".join(parts).encode()


@dataclass
class TrustStore:
    keys: dict[str, Ed25519PublicKey]
    revoked: set[str]

    @staticmethod
    def load(path: str) -> "TrustStore":
        doc = json.loads(Path(path).read_text())
        keys = {k["key_id"]: Ed25519PublicKey.from_public_bytes(base64.b64decode(k["public_key_b64"]))
                for k in doc["keys"]}
        return TrustStore(keys, set(doc.get("revoked", [])))


def validate_manifest_structure(m: dict, max_bytes: int) -> None:
    if not isinstance(m, dict):
        raise ManifestError("MALFORMED", "manifest must be a JSON object")
    for k, t in REQUIRED.items():
        v = m.get(k)
        if not isinstance(v, t) or (t is int and isinstance(v, bool)):
            raise ManifestError("MALFORMED", f"manifest field '{k}' missing or wrong type")
    extra = set(m) - set(REQUIRED)
    if extra:
        raise ManifestError("MALFORMED", f"unexpected manifest fields: {sorted(extra)}")
    if not (is_safe_id(m["firmware_id"]) and is_safe_id(m["key_id"]) and is_safe_id(m["hardware_id"])):
        raise ManifestError("MALFORMED", "identifier contains unsafe characters")
    if not (SEMVER.match(m["version"]) and SEMVER.match(m["min_current_version"])):
        raise ManifestError("MALFORMED", "invalid semantic version")
    if not SHA256_HEX.match(m["sha256"]):
        raise ManifestError("MALFORMED", "sha256 must be 64 lowercase hex characters")
    if not 0 < m["size"] <= max_bytes:
        raise ManifestError("TOO_LARGE", f"size must be 1..{max_bytes} bytes")
    if m["security_counter"] < 0 or len(m["release_notes"]) > 2000:
        raise ManifestError("MALFORMED", "security_counter/release_notes out of range")


def verify_signature(m: dict, trust: TrustStore) -> None:
    if m["key_id"] in trust.revoked:
        raise ManifestError("REVOKED_KEY", "signing key has been revoked")
    key = trust.keys.get(m["key_id"])
    if key is None:
        raise ManifestError("UNKNOWN_KEY", "signing key is not in the trust store")
    try:
        sig = base64.b64decode(m["signature"], validate=True)
        key.verify(sig, signing_payload(m))
    except (InvalidSignature, binascii.Error, ValueError):
        raise ManifestError("BAD_SIGNATURE", "Ed25519 signature verification failed")
