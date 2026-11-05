#!/usr/bin/env python3
"""One-time local setup. Creates .dev/ (git-ignored) containing:
  - a DEVELOPMENT Ed25519 signing key (never for production) and trust stores
  - backend.env with a freshly generated JWT secret
  - demo user accounts with random passwords (printed once, saved to .dev/credentials.txt)
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / ".dev"
sys.path.insert(0, str(ROOT / "firmware" / "tools"))
from autolink_fw import public_b64  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402


def main() -> None:
    DEV.mkdir(exist_ok=True)
    os.chmod(DEV, 0o700)
    key_path = DEV / "dev-key-1.private.pem"
    if not key_path.exists():
        k = Ed25519PrivateKey.generate()
        key_path.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        os.chmod(key_path, 0o600)
    k = serialization.load_pem_private_key(key_path.read_bytes(), None)
    trust = {"keys": [{"key_id": "dev-key-1", "public_key_b64": public_b64(k.public_key())}], "revoked": [],
             "note": "DEVELOPMENT trust store"}
    (DEV / "trust.json").write_text(json.dumps(trust, indent=2) + "\n")
    env_path = DEV / "backend.env"
    if not env_path.exists():
        env_path.write_text("\n".join([
            "AUTOLINK_ENV=development",
            f"AUTOLINK_JWT_SECRET={secrets.token_urlsafe(48)}",
            f"AUTOLINK_DATABASE_URL=sqlite:///{DEV / 'autolink.db'}",
            f"AUTOLINK_BLOB_DIR={DEV / 'blobs'}",
            f"AUTOLINK_TRUST_STORE={DEV / 'trust.json'}",
            "AUTOLINK_CORS_ORIGINS=http://localhost:5173",
            f"AUTOLINK_FRONTEND_DIST={ROOT / 'frontend' / 'dist'}",
        ]) + "\n")
        os.chmod(env_path, 0o600)
    env = {**os.environ, **dict(l.split("=", 1) for l in env_path.read_text().splitlines() if l)}
    creds = DEV / "credentials.txt"
    saved = creds.read_text() if creds.exists() else ""
    for user, role in (("admin", "admin"), ("approver", "admin"), ("engineer", "engineer"), ("viewer", "viewer")):
        if f"{user} (" in saved:
            continue
        pw = secrets.token_urlsafe(12)
        r = subprocess.run([sys.executable, "-m", "app.cli", "create-user", "--username", user, "--role", role,
                            "--password-env", "PW"], cwd=ROOT / "backend", env={**env, "PW": pw},
                           capture_output=True, text=True, check=True)
        if "already exists" in r.stdout:
            sys.exit(f"user {user} exists but its password is not in {creds}; delete {DEV} and rerun")
        with open(creds, "a") as f:  # saved immediately so a partial run never loses a password
            f.write(f"{user} ({role}): {pw}\n")
        os.chmod(creds, 0o600)
    print(f"Development setup ready in {DEV}\nAccounts:\n{creds.read_text()}")


if __name__ == "__main__":
    main()
