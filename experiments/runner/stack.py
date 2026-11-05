"""Local-stack harness: runs the real backend process and the compiled ECU binary.

Used by tests/integration (end-to-end tests) and experiments/runner/run_matrix.py.
Nothing here is mocked: HTTP goes over real sockets, firmware is really signed,
and the ECU really verifies and stages it.
"""
from __future__ import annotations

import base64
import json
import os
import random
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
ECU_BIN = ROOT / "ecu" / "build-make" / "autolink-ecu"
sys.path.insert(0, str(ROOT / "firmware" / "tools"))
from autolink_fw import build_manifest, public_b64  # noqa: E402

HW = "ALK-TCU-R1"
ADMIN_PW = "admin-" + secrets.token_hex(8)
ADMIN2_PW = "admin2-" + secrets.token_hex(8)
ENGINEER_PW = "engineer-" + secrets.token_hex(8)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class SigningKey:
    key_id: str
    private: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)

    def trust_entry(self) -> dict:
        return {"key_id": self.key_id, "public_key_b64": public_b64(self.private.public_key())}


class Backend:
    def __init__(self, workdir: Path, keys: list[SigningKey]):
        self.workdir = workdir
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        trust = workdir / "backend-trust.json"
        trust.write_text(json.dumps({"keys": [k.trust_entry() for k in keys], "revoked": []}))
        self.env = {**os.environ,
                    "AUTOLINK_ENV": "experiment",
                    "AUTOLINK_JWT_SECRET": secrets.token_urlsafe(48),
                    "AUTOLINK_DATABASE_URL": f"sqlite:///{workdir / 'autolink.db'}",
                    "AUTOLINK_BLOB_DIR": str(workdir / "blobs"),
                    "AUTOLINK_TRUST_STORE": str(trust),
                    "AUTOLINK_CORS_ORIGINS": "http://localhost:5173",
                    "AUTOLINK_PASSWORD_ITERATIONS": "20000",
                    "AUTOLINK_LOG_LEVEL": "WARNING",
                    "AUTOLINK_OFFLINE_AFTER_S": "5",
                    "PYTHONPATH": str(ROOT / "backend")}
        if os.environ.get("AUTOLINK_FRONTEND_DIST"):
            self.env["AUTOLINK_FRONTEND_DIST"] = os.environ["AUTOLINK_FRONTEND_DIST"]
        self._log = open(workdir / "backend.log", "ab")

    def bootstrap_users(self) -> None:
        for name, role, pw in (("admin", "admin", ADMIN_PW), ("admin2", "admin", ADMIN2_PW),
                               ("engineer", "engineer", ENGINEER_PW)):
            subprocess.run([sys.executable, "-m", "app.cli", "create-user", "--username", name, "--role", role,
                            "--password-env", "PW"], cwd=ROOT / "backend", env={**self.env, "PW": pw},
                           check=True, capture_output=True)

    def start(self) -> None:
        self.proc = subprocess.Popen([sys.executable, "-m", "app.cli", "serve", "--port", str(self.port)],
                                     cwd=ROOT / "backend", env=self.env, stdout=self._log, stderr=self._log)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if requests.get(self.url + "/health", timeout=0.5).status_code == 200:
                    return
            except requests.RequestException:
                time.sleep(0.1)
        raise RuntimeError("backend did not become healthy")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def close(self) -> None:
        self.stop()
        self._log.close()


class Api:
    def __init__(self, base: str):
        self.base = base
        self.tokens = {u: self._login(u, pw) for u, pw in
                       (("admin", ADMIN_PW), ("admin2", ADMIN2_PW), ("engineer", ENGINEER_PW))}

    def _login(self, user: str, pw: str) -> str:
        r = requests.post(self.base + "/api/v1/auth/login", json={"username": user, "password": pw}, timeout=10)
        r.raise_for_status()
        return r.json()["access_token"]

    def _h(self, user: str) -> dict:
        return {"Authorization": f"Bearer {self.tokens[user]}"}

    def call(self, method: str, path: str, user: str = "engineer", expect: int | None = None, **kw):
        r = requests.request(method, self.base + path, headers=self._h(user), timeout=15, **kw)
        if expect is not None and r.status_code != expect:
            raise AssertionError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
        return r

    def register_vehicle(self, vid: str, hw: str = HW) -> str:
        r = self.call("POST", "/api/v1/vehicles", expect=201,
                      json={"vehicle_id": vid, "display_name": f"Sim {vid}", "model": "AutoLink Sim",
                            "ecu_id": "ECU-TCU-01", "hardware_id": hw})
        return r.json()["device_token"]

    def upload_firmware(self, manifest: dict, image: bytes, expect: int | None = 201):
        return self.call("POST", "/api/v1/firmware", expect=expect,
                         files={"manifest": ("manifest.json", json.dumps(manifest)), "image": ("fw.bin", image)})

    def create_and_approve(self, firmware_id: str, vids: list[str], name: str = "campaign") -> dict:
        c = self.call("POST", "/api/v1/campaigns", expect=201,
                      json={"name": name, "firmware_id": firmware_id, "vehicle_ids": vids}).json()
        return self.call("POST", f"/api/v1/campaigns/{c['id']}/approve", user="admin2", expect=200).json()

    def deployment(self, did: str) -> dict:
        return self.call("GET", f"/api/v1/deployments/{did}", expect=200).json()

    def vehicle(self, vid: str) -> dict:
        return self.call("GET", f"/api/v1/vehicles/{vid}", expect=200).json()


def make_firmware(key: SigningKey, fid: str, version: str, hw: str = HW, counter: int = 1,
                  size: int = 256 * 1024, unhealthy: bool = False, seed: int = 0) -> tuple[dict, bytes]:
    rng = random.Random(seed or hash(fid) & 0xFFFF)
    image = f"AUTOLINK SIMULATED FIRMWARE {fid} {version}\n".encode() + rng.randbytes(size)
    return build_manifest(key.private, key.key_id, image, fid, version, hw, counter, "1.0.0",
                          f"release {version}", unhealthy), image


@dataclass
class EcuResult:
    exit_code: int
    duration_s: float
    state: dict | None
    stderr: str


class Ecu:
    def __init__(self, workdir: Path, vid: str, token: str, backend_url: str, trust_keys: list[SigningKey],
                 revoked: list[str] | None = None, heartbeat_ms: int = 100):
        self.dir = workdir / f"ecu-{vid}"
        self.dir.mkdir(parents=True, exist_ok=True)
        trust = self.dir / "trust.json"
        trust.write_text(json.dumps({"keys": [k.trust_entry() for k in trust_keys], "revoked": revoked or []}))
        self.config = self.dir / "ecu.json"
        self.config.write_text(json.dumps({
            "vehicle_id": vid, "ecu_id": "ECU-TCU-01", "hardware_id": HW, "factory_version": "1.0.0",
            "state_dir": str(self.dir / "state"), "backend_url": backend_url, "trust_store": str(trust),
            "heartbeat_ms": heartbeat_ms, "http_timeout_ms": 1500, "backoff_base_ms": 50}))
        self.token = token

    def run(self, *flags: str, timeout: float = 60, cycles: int = 600) -> EcuResult:
        if not ECU_BIN.exists():
            raise RuntimeError(f"ECU binary missing: build with `make -C ecu` ({ECU_BIN})")
        cmd = [str(ECU_BIN), "--config", str(self.config), "--exit-after-update", "--cycles", str(cycles), *flags]
        t0 = time.perf_counter()
        try:
            p = subprocess.run(cmd, env={**os.environ, "AUTOLINK_DEVICE_TOKEN": self.token},
                               capture_output=True, text=True, timeout=timeout)
            code, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            code, out, err = -9, e.stdout or "", (e.stderr or "") if isinstance(e.stderr, str) else ""
        dur = time.perf_counter() - t0
        return EcuResult(code, dur, self.read_state(), err[-2000:] if isinstance(err, str) else "")

    def spawn(self, *flags: str) -> subprocess.Popen:
        cmd = [str(ECU_BIN), "--config", str(self.config), "--exit-after-update", "--cycles", "600", *flags]
        return subprocess.Popen(cmd, env={**os.environ, "AUTOLINK_DEVICE_TOKEN": self.token},
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    def read_state(self) -> dict | None:
        p = self.dir / "state" / "state.json"
        return json.loads(p.read_text()) if p.exists() else None

    def journal(self) -> list[dict]:
        p = self.dir / "state" / "journal.log"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


class FaultProxy:
    """TCP proxy between ECU and backend. Faults are modelled per TCP connection
    (TCP retransmits real packet loss, so loss surfaces to applications as
    stalled/reset connections): drop probability, added latency, blackhole
    windows, and response truncation."""

    def __init__(self, target_port: int, seed: int, drop_prob: float = 0.0, delay_ms: tuple[int, int] = (0, 0),
                 truncate_prob: float = 0.0):
        self.target_port = target_port
        self.port = free_port()
        self.rng = random.Random(seed)
        self.drop_prob, self.delay_ms, self.truncate_prob = drop_prob, delay_ms, truncate_prob
        self.blackhole_until = 0.0
        self.stats = {"connections": 0, "dropped": 0, "truncated": 0, "blackholed": 0}
        self._lock = threading.Lock()
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", self.port))
        self._srv.listen(64)
        self._stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def blackhole(self, seconds: float) -> None:
        self.blackhole_until = time.time() + seconds

    def close(self) -> None:
        self._stop = True
        self._srv.close()

    def _accept(self) -> None:
        while not self._stop:
            try:
                client, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        with self._lock:
            self.stats["connections"] += 1
            r = self.rng.random()
            delay = self.rng.randint(*self.delay_ms) / 1000 if self.delay_ms[1] else 0
            truncate = self.rng.random() < self.truncate_prob
        if time.time() < self.blackhole_until:
            with self._lock:
                self.stats["blackholed"] += 1
            client.close()
            return
        if r < self.drop_prob:
            with self._lock:
                self.stats["dropped"] += 1
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
            client.close()  # RST
            return
        try:
            upstream = socket.create_connection(("127.0.0.1", self.target_port), timeout=5)
        except OSError:
            client.close()
            return
        if delay:
            time.sleep(delay)
        budget = self.rng.randint(2000, 60000) if truncate else None
        if truncate:
            with self._lock:
                self.stats["truncated"] += 1
        socks = [client, upstream]
        try:
            while True:
                readable, _, _ = select.select(socks, [], [], 10)
                if not readable:
                    break
                for s in readable:
                    data = s.recv(65536)
                    if not data:
                        raise EOFError
                    if s is upstream and budget is not None:
                        data = data[:budget]
                        budget -= len(data)
                        (client if s is upstream else upstream).sendall(data)
                        if budget <= 0:
                            raise EOFError
                        continue
                    (client if s is upstream else upstream).sendall(data)
        except (EOFError, OSError):
            pass
        finally:
            client.close()
            upstream.close()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
