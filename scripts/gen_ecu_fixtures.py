#!/usr/bin/env python3
"""Generates deterministic, signed fixtures for the C++ unit tests.

Keys are derived from public, fixed seeds and are TEST-ONLY. Ed25519
signatures are deterministic, so re-running produces byte-identical output.
"""
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "firmware" / "tools"))
from autolink_fw import build_manifest, public_b64  # noqa: E402

OUT = ROOT / "ecu" / "tests" / "fixtures"
HW = "ALK-TCU-R1"


def key(label: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(f"autolink-test-only:{label}".encode()).digest())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trusted, untrusted, revoked = key("trusted"), key("untrusted"), key("revoked")
    (OUT / "trust.json").write_text(json.dumps({
        "keys": [{"key_id": "test-key-1", "public_key_b64": public_b64(trusted.public_key())},
                 {"key_id": "test-key-revoked", "public_key_b64": public_b64(revoked.public_key())}],
        "revoked": ["test-key-revoked"],
    }, indent=2) + "\n")
    cases = {
        # name: (signing key, key_id, version, hw, counter, min_current, unhealthy)
        "v110": (trusted, "test-key-1", "1.1.0", HW, 1, "1.0.0", False),
        "v120": (trusted, "test-key-1", "1.2.0", HW, 2, "1.0.0", False),
        "v200_counter5": (trusted, "test-key-1", "2.0.0", HW, 5, "1.0.0", False),
        "v300_counter3": (trusted, "test-key-1", "3.0.0", HW, 3, "1.0.0", False),
        "v090_old": (trusted, "test-key-1", "0.9.0", HW, 1, "0.0.0", False),
        "wrong_hw": (trusted, "test-key-1", "1.1.0", "ALK-OTHER-HW", 1, "1.0.0", False),
        "needs_150": (trusted, "test-key-1", "1.6.0", HW, 1, "1.5.0", False),
        "unhealthy": (trusted, "test-key-1", "1.1.0", HW, 1, "1.0.0", True),
        "untrusted_key": (untrusted, "test-key-1", "1.1.0", HW, 1, "1.0.0", False),
        "unknown_key": (untrusted, "test-key-unknown", "1.1.0", HW, 1, "1.0.0", False),
        "revoked_key": (revoked, "test-key-revoked", "1.1.0", HW, 1, "1.0.0", False),
    }
    for name, (k, kid, ver, hw, ctr, minv, bad) in cases.items():
        image = (f"AUTOLINK SIMULATED FIRMWARE {name} {ver}\n".encode() * 200)
        fid = f"fw-{name.replace('_', '-')}"
        m = build_manifest(k, kid, image, fid, ver, hw, ctr, minv, f"fixture {name}", bad)
        (OUT / f"{name}.img").write_bytes(image)
        (OUT / f"{name}.manifest.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(cases)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
