#!/usr/bin/env python3
"""Scripted demo against a running local backend (see docs/portfolio/demo-script.md).

  python3 scripts/demo.py register  VIN-DEMO-001        -> prints the vehicle's device token, writes ECU config
  python3 scripts/demo.py release   1.1.0 [--corrupt]   -> builds + signs a firmware image and uploads it
  python3 scripts/demo.py campaign  fw-tcu-1.1.0 VIN-DEMO-001   -> engineer drafts, approver approves
  python3 scripts/demo.py status    VIN-DEMO-001        -> vehicle + latest deployment from the API
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / ".dev"
sys.path.insert(0, str(ROOT / "firmware" / "tools"))
from autolink_fw import build_manifest, load_private  # noqa: E402

BASE = os.environ.get("AUTOLINK_URL", "http://127.0.0.1:8000")


def creds() -> dict[str, str]:
    out = {}
    for line in (DEV / "credentials.txt").read_text().splitlines():
        user, pw = line.split(" (")[0], line.split(": ", 1)[1]
        out[user] = pw
    return out


def token(user: str) -> dict:
    r = requests.post(f"{BASE}/api/v1/auth/login", json={"username": user, "password": creds()[user]}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def show(r: requests.Response) -> dict:
    body = r.json()
    if not r.ok:
        sys.exit(f"HTTP {r.status_code}: {json.dumps(body, indent=2)}")
    return body


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else "help"
    if cmd == "register":
        vid = argv[1]
        v = show(requests.post(f"{BASE}/api/v1/vehicles", headers=token("engineer"), timeout=10, json={
            "vehicle_id": vid, "display_name": "Demo car", "model": "AutoLink Sim", "ecu_id": "ECU-TCU-01",
            "hardware_id": "ALK-TCU-R1"}))
        cfg = DEV / f"ecu-{vid}.json"
        cfg.write_text(json.dumps({"vehicle_id": vid, "ecu_id": "ECU-TCU-01", "hardware_id": "ALK-TCU-R1",
                                   "factory_version": "1.0.0", "state_dir": str(DEV / f"ecu-state-{vid}"),
                                   "backend_url": BASE, "trust_store": str(DEV / "trust.json"),
                                   "heartbeat_ms": 1000}, indent=2))
        (DEV / f"ecu-{vid}.token").write_text(v["device_token"])
        os.chmod(DEV / f"ecu-{vid}.token", 0o600)
        print(f"registered {vid}; ECU config {cfg}\nrun: AUTOLINK_DEVICE_TOKEN=$(cat {DEV}/ecu-{vid}.token) "
              f"ecu/build-make/autolink-ecu --config {cfg}")
    elif cmd == "release":
        version = argv[1]
        image = (f"AUTOLINK SIMULATED TCU FIRMWARE {version}\n".encode()) * 4096
        fid = f"fw-tcu-{version}"
        m = build_manifest(load_private(str(DEV / "dev-key-1.private.pem")), "dev-key-1", image, fid, version,
                           "ALK-TCU-R1", int(version.split(".")[0]) * 100 + int(version.split(".")[1]), "1.0.0",
                           f"Demo release {version}", "--unhealthy" in argv)
        if "--corrupt" in argv:
            image = image[:-1] + b"!"  # bytes no longer match the signed digest
        r = requests.post(f"{BASE}/api/v1/firmware", headers=token("engineer"), timeout=30,
                          files={"manifest": ("m.json", json.dumps(m)), "image": ("fw.bin", image)})
        body = r.json()
        print(f"HTTP {r.status_code}: {json.dumps(body if not r.ok else {k: body[k] for k in ('id', 'version', 'sha256', 'signature_verified')}, indent=2)}")
    elif cmd == "campaign":
        fid, vids = argv[1], argv[2:]
        c = show(requests.post(f"{BASE}/api/v1/campaigns", headers=token("engineer"), timeout=10,
                               json={"name": f"{fid} rollout", "firmware_id": fid, "vehicle_ids": vids}))
        c = show(requests.post(f"{BASE}/api/v1/campaigns/{c['id']}/approve", headers=token("approver"), timeout=10))
        print(f"campaign {c['id']} {c['status']}: {[d['status'] for d in c['deployments']]}")
    elif cmd == "status":
        v = show(requests.get(f"{BASE}/api/v1/vehicles/{argv[1]}", headers=token("viewer"), timeout=10))
        latest = v["deployments"][0] if v["deployments"] else None
        print(json.dumps({"firmware_version": v["firmware_version"], "connectivity": v["connectivity"],
                          "latest_deployment": latest and {k: latest[k] for k in ("target_version", "status", "error_code")}},
                         indent=2))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
