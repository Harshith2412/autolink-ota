#!/usr/bin/env python3
"""Fault-injection experiment runner.

Runs every scenario in experiments/scenarios/matrix.json `repetitions` times
against the real local stack, records one JSON line per execution, and writes
summary.json with metrics computed only from those records.

Usage: python3 experiments/runner/run_matrix.py [--reps N] [--only SCENARIO] [--out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import signal
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack import HW, ROOT, Api, Backend, Ecu, FaultProxy, SigningKey, make_firmware  # noqa: E402

TARGET = "1.1.0"
UNHEALTHY_TARGET = "1.2.0"
BASE = "1.0.0"
TERMINAL = {"SUCCEEDED", "REJECTED", "ROLLED_BACK", "FAILED", "RECOVERY_FAILED", "EXPIRED", "CANCELLED"}


class Runner:
    def __init__(self, work: Path):
        self.work = work
        self.key = SigningKey("dev-key-1")
        self.backend = Backend(work, [self.key])
        self.backend.bootstrap_users()
        self.backend.start()
        self.api = Api(self.backend.url)
        m, img = make_firmware(self.key, "fw-exp-110", TARGET, seed=1)
        self.api.upload_firmware(m, img)
        m, img = make_firmware(self.key, "fw-exp-120-unhealthy", UNHEALTHY_TARGET, unhealthy=True, seed=2)
        self.api.upload_firmware(m, img)
        self.counter = 0

    def close(self):
        self.backend.close()

    # ------------------------------------------------------------------ helpers
    def new_vehicle(self, sid: str, url: str | None = None, **kw) -> tuple[str, Ecu]:
        self.counter += 1
        vid = f"VIN-{sid[:20]}-{self.counter:04d}".replace("_", "-")
        token = self.api.register_vehicle(vid)
        ecu = Ecu(self.work, vid, token, url or self.backend.url, [self.key], **kw)
        r = ecu.run("--cycles", "1")  # provision + first heartbeat (reports 1.0.0)
        if r.state is None:
            raise RuntimeError(f"ECU failed to provision: {r.stderr}")
        return vid, ecu

    def wait_terminal(self, did: str, timeout: float = 10) -> dict:
        deadline = time.time() + timeout
        while True:
            d = self.api.deployment(did)
            if d["status"] in TERMINAL or time.time() > deadline:
                return d
            time.sleep(0.1)

    # ------------------------------------------------------------------ execution
    def execute(self, sc: dict, seed: int) -> dict:
        rng = random.Random(seed)
        kind = sc["kind"]
        rec = {"scenario_id": sc["id"], "seed": seed, "config": sc, "expected": sc["expected"]}
        t_start = time.perf_counter()
        try:
            if kind == "api":
                actual = self.api_scenario(sc, rng)
                rec.update(actual=actual, passed=actual == sc["expected"]["result"], error_category=None
                           if actual == sc["expected"]["result"] else "UNEXPECTED_API_RESULT",
                           update_duration_s=None, recovery_duration_ms=None, final_ecu_state=None,
                           final_firmware_version=None, consistency_violations=[])
                return rec
            rec.update(self.ecu_scenario(sc, rng))
        except Exception as e:  # noqa: BLE001 - every failure is recorded, none hidden
            rec.update(passed=False, actual={"exception": f"{type(e).__name__}: {e}"}, error_category="HARNESS_ERROR",
                       consistency_violations=[], update_duration_s=None, recovery_duration_ms=None,
                       final_ecu_state=None, final_firmware_version=None)
        rec["wall_time_s"] = round(time.perf_counter() - t_start, 3)
        return rec

    def api_scenario(self, sc: dict, rng: random.Random) -> str:
        n = self.counter = self.counter + 1
        if sc["id"] == "api_invalid_signature_upload":
            m, img = make_firmware(self.key, f"fw-bad-{n}", f"5.{n}.0", seed=rng.randint(1, 1 << 30))
            m["release_notes"] = "tampered after signing"
            r = self.api.upload_firmware(m, img, expect=None)
            return f"{r.status_code}:{r.json()['error']['details']['reason']}"
        if sc["id"] == "api_untrusted_key_upload":
            rogue = SigningKey("dev-key-1")  # same key id, different (attacker) key
            m, img = make_firmware(rogue, f"fw-rogue-{n}", f"6.{n}.0", seed=rng.randint(1, 1 << 30))
            r = self.api.upload_firmware(m, img, expect=None)
            return f"{r.status_code}:{r.json()['error']['details']['reason']}"
        vid, _ = self.new_vehicle(sc["id"])
        if sc["id"] == "api_wrong_hardware_campaign":
            m, img = make_firmware(self.key, f"fw-hw-{n}", f"1.1.{n}", hw="ALK-OTHER-HW", seed=n)
            self.api.upload_firmware(m, img)
            fid = m["firmware_id"]
        else:  # api_rollback_campaign: vehicle already ahead of the package
            fid = "fw-exp-110"
            ecu_token = self.api.call("POST", f"/api/v1/vehicles/{vid}/rotate-token", user="admin", expect=200).json()
            ecu = Ecu(self.work, vid + "-x", ecu_token["device_token"], self.backend.url, [self.key])
            # report a newer installed version via an authenticated heartbeat
            import requests  # noqa: PLC0415
            requests.post(self.backend.url + "/api/v1/device/heartbeat", timeout=5,
                          headers={"Authorization": f"Bearer {ecu.token}", "X-Vehicle-Id": vid},
                          json={"vehicle_id": vid, "ecu_id": "ECU-TCU-01", "hardware_id": HW,
                                "firmware_version": "2.0.0", "active_slot": "A", "update_state": "IDLE",
                                "last_command_seq": 0}).raise_for_status()
        r = self.api.call("POST", "/api/v1/campaigns", json={"name": sc["id"], "firmware_id": fid,
                                                             "vehicle_ids": [vid]})
        return str(r.status_code)

    def ecu_scenario(self, sc: dict, rng: random.Random) -> dict:
        proxy = None
        if sc.get("proxy") is not None:
            p = sc["proxy"]
            proxy = FaultProxy(self.backend.port, rng.randint(1, 1 << 30), drop_prob=p.get("drop_prob", 0),
                               delay_ms=tuple(p.get("delay_ms", [0, 0])), truncate_prob=p.get("truncate_prob", 0))
        try:
            ecu_kw = {"revoked": ["dev-key-1"]} if sc.get("ecu_revokes_key") else {}
            vid, ecu = self.new_vehicle(sc["id"], url=proxy.url if proxy else None, **ecu_kw)
            fid = "fw-exp-120-unhealthy" if sc.get("unhealthy_firmware") else "fw-exp-110"
            target = UNHEALTHY_TARGET if sc.get("unhealthy_firmware") else TARGET
            flags = list(sc.get("ecu_flags", []))
            if sc.get("interrupt_bytes"):
                flags += ["--interrupt-download-after", str(rng.randint(*sc["interrupt_bytes"]))]
            camp = self.api.create_and_approve(fid, [vid], name=sc["id"])
            did = camp["deployments"][0]["id"]
            t0 = time.perf_counter()
            runs = []
            if proxy and sc.get("blackhole_s"):
                proxy.blackhole(sc["blackhole_s"])
            if sc.get("backend_restart"):
                proc = ecu.spawn(*flags)
                time.sleep(rng.uniform(0.05, 0.4))
                self.backend.stop()
                time.sleep(sc["backend_restart"])
                self.backend.start()
                proc.wait(90)
                runs.append(proc.returncode)
            elif sc.get("kill_ms"):
                proc = ecu.spawn(*flags)
                time.sleep(rng.randint(*sc["kill_ms"]) / 1000)
                proc.send_signal(signal.SIGKILL)
                proc.wait(10)
                runs.append(proc.returncode)
                if proc.returncode == -signal.SIGKILL:
                    # Restart; a short budget covers the case where the kill landed after completion.
                    runs.append(ecu.run(cycles=30).exit_code)
            else:
                first = ecu.run(*flags)
                runs.append(first.exit_code)
                if first.exit_code == 86:  # simulated power loss: power back on
                    runs.append(ecu.run().exit_code)
            update_duration = time.perf_counter() - t0
            dep = self.wait_terminal(did)
            state = ecu.read_state()
            return self.evaluate(sc, ecu, vid, dep, state, target, runs, update_duration, proxy)
        finally:
            if proxy:
                proxy.close()

    def evaluate(self, sc, ecu, vid, dep, state, target, runs, duration, proxy) -> dict:
        active = state["slot_a"] if state["active_slot"] == "A" else state["slot_b"]
        version = active["version"]
        violations = []
        expected_status = sc["expected"]["deployment_status"]
        expected_states = {"RECOVERY_FAILED"} if expected_status == ["RECOVERY_FAILED"] else {"IDLE"}
        if state["update_state"] not in expected_states:
            violations.append(f"ecu state {state['update_state']}")
        if version not in (BASE, target):
            violations.append(f"unexpected version {version}")
        if dep["status"] not in TERMINAL:
            violations.append(f"deployment not terminal: {dep['status']}")
        if dep["status"] != "RECOVERY_FAILED" and (dep["status"] == "SUCCEEDED") != (version == target):
            violations.append(f"cloud status {dep['status']} inconsistent with ECU version {version}")
        if state["outbox"]:
            violations.append("undelivered events in outbox")
        slot_file = ecu.dir / "state" / f"slot_{state['active_slot']}.img"
        if state["update_state"] != "RECOVERY_FAILED" and \
                hashlib.sha256(slot_file.read_bytes()).hexdigest() != active["sha256"]:
            violations.append("active slot digest mismatch")
        if state["update_state"] != "RECOVERY_FAILED":
            cloud_version = self.api.vehicle(vid)["firmware_version"]
            if cloud_version != version:
                violations.append(f"cloud firmware_version {cloud_version} != ECU {version}")
        if sc.get("ecu_flags") and "--replay-commands" in sc["ecu_flags"]:
            if state["counters"]["updates_attempted"] != 1 or state["counters"]["duplicate_commands"] < 1:
                violations.append("duplicate command was executed or not detected")

        journal = ecu.journal()
        recovery_ms = None
        fail_ts = next((e["ts_ms"] for e in journal if e.get("event") == "TRANSITION"
                        and e["to"] in ("DOWNLOAD_FAILED", "ACTIVATION_FAILED")), None)
        end_ts = next((e["ts_ms"] for e in reversed(journal) if e.get("event") == "TRANSITION"
                       and e["to"] in ("COMMITTED", "ROLLED_BACK", "RECOVERY_FAILED")), None)
        if fail_ts and end_ts and end_ts >= fail_ts:
            recovery_ms = end_ts - fail_ts
        status_ok = dep["status"] in expected_status
        want = sc["expected"]["final_version"]
        version_ok = want == "any" or version == (target if want == "target" else BASE)
        passed = status_ok and version_ok and not violations
        category = None
        if not passed:
            category = "STATE_INCONSISTENCY" if violations else ("UNEXPECTED_OUTCOME" if not status_ok else "WRONG_VERSION")
        return {
            "actual": {"deployment_status": dep["status"], "error_code": dep.get("error_code"),
                       "ecu_exit_codes": runs, "proxy_stats": proxy.stats if proxy else None,
                       "download_retries": state["counters"]["download_retries"],
                       "duplicate_commands": state["counters"]["duplicate_commands"]},
            "passed": passed, "error_category": category, "consistency_violations": violations,
            "update_duration_s": round(duration, 3), "recovery_duration_ms": recovery_ms,
            "final_ecu_state": state["update_state"], "final_firmware_version": version,
        }


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


def summarize(records: list[dict], env: dict) -> dict:
    def rate(rs, pred):
        return None if not rs else round(sum(1 for r in rs if pred(r)) / len(rs), 4)

    ecu_recs = [r for r in records if r["config"]["kind"] == "ecu"]
    happy = [r for r in ecu_recs if r["config"]["category"] in ("normal", "network")]
    invalid = [r for r in records if r["config"]["category"] == "invalid_package"]
    recovery = [r for r in ecu_recs if r["config"]["category"] == "recovery"]
    durations = [r["update_duration_s"] for r in happy if r.get("update_duration_s") is not None
                 and r.get("actual", {}).get("deployment_status") == "SUCCEEDED"]
    rec_ms = [r["recovery_duration_ms"] for r in ecu_recs if r.get("recovery_duration_ms") is not None]
    dup = [r for r in records if r["scenario_id"] == "duplicate_commands"]
    per = {}
    for r in records:
        p = per.setdefault(r["scenario_id"], {"runs": 0, "passed": 0})
        p["runs"] += 1
        p["passed"] += int(r["passed"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": env,
        "executions": len(records),
        "passed": sum(1 for r in records if r["passed"]),
        "failed": sum(1 for r in records if not r["passed"]),
        "metrics": {
            "successful_update_rate_normal_and_network_faults": rate(
                happy, lambda r: r.get("actual", {}).get("deployment_status") == "SUCCEEDED"),
            "invalid_package_rejection_rate": rate(invalid, lambda r: r["passed"]),
            "recovery_success_rate": rate(recovery, lambda r: r["passed"]),
            "update_latency_s": {"n": len(durations), "mean": round(statistics.mean(durations), 3) if durations else None,
                                 "p50": pct(durations, .5), "p95": pct(durations, .95), "max": pct(durations, 1)},
            "recovery_time_ms": {"n": len(rec_ms), "mean": round(statistics.mean(rec_ms), 1) if rec_ms else None,
                                 "p50": pct(rec_ms, .5), "p95": pct(rec_ms, .95), "max": pct(rec_ms, 1)},
            "state_consistency_violations": sum(len(r.get("consistency_violations", [])) for r in records),
            "duplicate_command_handling_success_rate": rate(dup, lambda r: r["passed"]),
        },
        "per_scenario": per,
        "failures": [{"scenario_id": r["scenario_id"], "seed": r["seed"], "category": r["error_category"],
                      "actual": r.get("actual"), "violations": r.get("consistency_violations")}
                     for r in records if not r["passed"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default=str(ROOT / "experiments/scenarios/matrix.json"))
    ap.add_argument("--reps", type=int, default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--out", default=str(ROOT / "experiments/results"))
    a = ap.parse_args()
    matrix = json.loads(Path(a.matrix).read_text())
    reps = a.reps or matrix["repetitions"]
    scenarios = [s for s in matrix["scenarios"] if not a.only or s["id"] == a.only]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    env = {"python": platform.python_version(), "platform": platform.platform(), "cpus": __import__("os").cpu_count(),
           "ecu_binary": "ecu/build-make/autolink-ecu", "base_seed": matrix["base_seed"], "repetitions": reps,
           "image_size_bytes": 256 * 1024 + 64, "transport": "HTTP/1.1 over loopback (no TLS)"}
    records = []
    with tempfile.TemporaryDirectory() as tmp:
        runner = Runner(Path(tmp))
        try:
            with open(out / "results.jsonl", "w") as f:
                for sc in scenarios:
                    for rep in range(reps):
                        seed = matrix["base_seed"] + rep * 1000 + matrix["scenarios"].index(sc)
                        rec = runner.execute(sc, seed)
                        records.append(rec)
                        f.write(json.dumps(rec) + "\n")
                        f.flush()
                        print(f"{'PASS' if rec['passed'] else 'FAIL'} {sc['id']:<32} seed={seed} "
                              f"{rec.get('actual')}", flush=True)
        finally:
            runner.close()
    summary = summarize(records, env)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("executions", "passed", "failed", "metrics")}, indent=2))


if __name__ == "__main__":
    main()
