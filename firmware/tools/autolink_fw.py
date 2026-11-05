#!/usr/bin/env python3
"""AutoLink firmware release tool: key generation, signing, verification.

Signs firmware manifests with Ed25519 (via the `cryptography` package). The
signature covers a canonical, length-prefixed payload that the C++ ECU
(ecu/src/manifest.cpp) and the backend (backend/app/security/manifest.py)
reconstruct byte-for-byte.

Commands:
  keygen  --key-id ID --out-dir DIR          create a DEVELOPMENT key pair
  sign    --key PRIV --key-id ID --image F --firmware-id ID --version X.Y.Z
          --hardware-id HW --security-counter N [--min-current-version X.Y.Z]
          [--notes TEXT] [--simulate-unhealthy] --out MANIFEST.json
  verify  --manifest M --image F --public-key PUB
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

MAX_FIRMWARE_BYTES = 16 * 1024 * 1024
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SEMVER = re.compile(r"^(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})$")
PAYLOAD_FIELDS = (
    "firmware_id", "version", "hardware_id", "sha256", "size", "security_counter",
    "min_current_version", "key_id", "release_notes", "simulate_unhealthy",
)


def signing_payload(m: dict) -> bytes:
    def fmt(v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    out = ["AUTOLINK-FW-MANIFEST-V1\n"]
    for name in PAYLOAD_FIELDS:
        value = fmt(m.get(name, "" if name == "release_notes" else False if name == "simulate_unhealthy" else None))
        out.append(f"{name}={len(value.encode())}:{value}\n")
    return "".join(out).encode()


def _check_id(name: str, value: str) -> None:
    if not SAFE_ID.match(value) or ".." in value:
        raise SystemExit(f"invalid {name}: {value!r}")


def build_manifest(priv: Ed25519PrivateKey, key_id: str, image: bytes, firmware_id: str, version: str,
                   hardware_id: str, security_counter: int, min_current_version: str = "0.0.0",
                   notes: str = "", simulate_unhealthy: bool = False) -> dict:
    _check_id("firmware_id", firmware_id)
    _check_id("key_id", key_id)
    for v in (version, min_current_version):
        if not SEMVER.match(v):
            raise SystemExit(f"invalid semantic version: {v!r}")
    if not 0 < len(image) <= MAX_FIRMWARE_BYTES:
        raise SystemExit("image size out of bounds")
    m = {
        "firmware_id": firmware_id,
        "version": version,
        "hardware_id": hardware_id,
        "sha256": hashlib.sha256(image).hexdigest(),
        "size": len(image),
        "security_counter": int(security_counter),
        "min_current_version": min_current_version,
        "key_id": key_id,
        "release_notes": notes,
        "simulate_unhealthy": bool(simulate_unhealthy),
    }
    m["signature"] = base64.b64encode(priv.sign(signing_payload(m))).decode()
    return m


def verify_manifest(m: dict, image: bytes, pub: Ed25519PublicKey) -> None:
    pub.verify(base64.b64decode(m["signature"], validate=True), signing_payload(m))
    if hashlib.sha256(image).hexdigest() != m["sha256"] or len(image) != m["size"]:
        raise ValueError("image does not match manifest digest/size")


def load_private(path: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("not an Ed25519 private key")
    return key


def public_b64(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def cmd_keygen(a) -> None:
    _check_id("key_id", a.key_id)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    priv_path = out / f"{a.key_id}.private.pem"
    fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()))
    pub = {"key_id": a.key_id, "public_key_b64": public_b64(priv.public_key()),
           "note": "DEVELOPMENT KEY - never use for production releases"}
    (out / f"{a.key_id}.public.json").write_text(json.dumps(pub, indent=2) + "\n")
    print(f"wrote {priv_path} (mode 0600) and {a.key_id}.public.json")


def cmd_sign(a) -> None:
    image = Path(a.image).read_bytes()
    m = build_manifest(load_private(a.key), a.key_id, image, a.firmware_id, a.version, a.hardware_id,
                       a.security_counter, a.min_current_version, a.notes, a.simulate_unhealthy)
    Path(a.out).write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    print(f"signed {a.firmware_id} {a.version} sha256={m['sha256']} -> {a.out}")


def cmd_verify(a) -> None:
    m = json.loads(Path(a.manifest).read_text())
    pub_doc = json.loads(Path(a.public_key).read_text())
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_doc["public_key_b64"]))
    try:
        verify_manifest(m, Path(a.image).read_bytes(), pub)
    except Exception as e:  # noqa: BLE001 - report any verification failure
        print(f"INVALID: {type(e).__name__}: {e}")
        sys.exit(1)
    print("VALID")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--key-id", required=True)
    k.add_argument("--out-dir", required=True)
    s = sub.add_parser("sign")
    for f in ("--key", "--key-id", "--image", "--firmware-id", "--version", "--hardware-id", "--out"):
        s.add_argument(f, required=True)
    s.add_argument("--security-counter", type=int, required=True)
    s.add_argument("--min-current-version", default="0.0.0")
    s.add_argument("--notes", default="")
    s.add_argument("--simulate-unhealthy", action="store_true")
    v = sub.add_parser("verify")
    for f in ("--manifest", "--image", "--public-key"):
        v.add_argument(f, required=True)
    a = p.parse_args(argv)
    {"keygen": cmd_keygen, "sign": cmd_sign, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    main()
