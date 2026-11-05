"""End-to-end integration tests: real backend process + compiled C++ ECU over HTTP.

Run: python3 -m unittest tests.integration.test_end_to_end   (after `make -C ecu`)
IDs IT-xxx map to docs/requirements/traceability.md.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "runner"))
from stack import Api, Backend, Ecu, SigningKey, make_firmware  # noqa: E402


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        cls.key = SigningKey("dev-key-1")
        cls.backend = Backend(cls.work, [cls.key])
        cls.backend.bootstrap_users()
        cls.backend.start()
        cls.api = Api(cls.backend.url)

    @classmethod
    def tearDownClass(cls):
        cls.backend.close()
        cls.tmp.cleanup()

    def vehicle(self, vid, **ecu_kw):
        token = self.api.register_vehicle(vid)
        return Ecu(self.work, vid, token, self.backend.url, [self.key], **ecu_kw)

    def test_it001_signed_update_completes_end_to_end(self):
        ecu = self.vehicle("VIN-E2E-OK")
        self.assertEqual(ecu.run("--cycles", "2").exit_code, 4)  # registers, reports 1.0.0, no update yet
        m, img = make_firmware(self.key, "fw-e2e-110", "1.1.0")
        self.api.upload_firmware(m, img)
        camp = self.api.create_and_approve("fw-e2e-110", ["VIN-E2E-OK"])
        res = ecu.run()
        self.assertEqual(res.exit_code, 0, res.stderr)
        s = res.state
        self.assertEqual((s["update_state"], s["active_slot"]), ("IDLE", "B"))
        self.assertEqual(s["slot_b"]["version"], "1.1.0")
        dep = self.api.deployment(camp["deployments"][0]["id"])
        self.assertEqual(dep["status"], "SUCCEEDED")
        states = [e["to_state"] for e in dep["events"] if e["kind"] == "STATE"]
        self.assertEqual(states[:9], ["UPDATE_AVAILABLE", "DOWNLOADING", "VERIFYING", "STAGING",
                                      "READY_TO_ACTIVATE", "ACTIVATING", "HEALTH_CHECK", "COMMITTED", "IDLE"])
        v = self.api.vehicle("VIN-E2E-OK")
        self.assertEqual(v["firmware_version"], "1.1.0")
        tel = self.api.call("GET", "/api/v1/vehicles/VIN-E2E-OK/telemetry", expect=200).json()["items"]
        self.assertGreater(len(tel), 2)

    def test_it002_corrupted_image_rejected_by_ecu(self):
        ecu = self.vehicle("VIN-E2E-CORRUPT")
        ecu.run("--cycles", "1")
        m, img = make_firmware(self.key, "fw-e2e-corrupt", "1.2.0")
        self.api.upload_firmware(m, img)
        camp = self.api.create_and_approve("fw-e2e-corrupt", ["VIN-E2E-CORRUPT"])
        res = ecu.run("--corrupt-download")
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.assertEqual(res.state["slot_a"]["version"], "1.0.0")
        self.assertEqual(res.state["active_slot"], "A")
        dep = self.api.deployment(camp["deployments"][0]["id"])
        self.assertEqual((dep["status"], dep["error_code"]), ("REJECTED", "DIGEST_MISMATCH"))
        diags = self.api.call("GET", "/api/v1/vehicles/VIN-E2E-CORRUPT/diagnostics", expect=200).json()
        self.assertIn("U3002", [d["code"] for d in diags["items"]])

    def test_it003_tampered_package_rejected_at_upload(self):
        m, img = make_firmware(self.key, "fw-e2e-tamper", "1.3.0")
        m["version"] = "9.9.9"
        r = self.api.upload_firmware(m, img, expect=422)
        self.assertEqual(r.json()["error"]["details"]["reason"], "BAD_SIGNATURE")

    def test_it004_power_loss_during_activation_recovers(self):
        ecu = self.vehicle("VIN-E2E-POWER")
        ecu.run("--cycles", "1")
        m, img = make_firmware(self.key, "fw-e2e-power", "1.4.0")
        self.api.upload_firmware(m, img)
        camp = self.api.create_and_approve("fw-e2e-power", ["VIN-E2E-POWER"])
        first = ecu.run("--crash-after", "ACTIVATING")
        self.assertEqual(first.exit_code, 86)
        self.assertEqual(first.state["update_state"], "ACTIVATING")
        second = ecu.run()
        self.assertEqual(second.exit_code, 0, second.stderr)
        self.assertEqual((second.state["active_slot"], second.state["slot_a"]["version"]), ("A", "1.0.0"))
        self.assertEqual(self.api.deployment(camp["deployments"][0]["id"])["status"], "ROLLED_BACK")

    def test_it005_ecu_revocation_is_defence_in_depth(self):
        # Backend trusts the key, but this ECU's trust store has revoked it.
        token = self.api.register_vehicle("VIN-E2E-REVOKED")
        ecu = Ecu(self.work, "VIN-E2E-REVOKED", token, self.backend.url, [self.key], revoked=["dev-key-1"])
        ecu.run("--cycles", "1")
        m, img = make_firmware(self.key, "fw-e2e-rev", "1.5.0")
        self.api.upload_firmware(m, img)
        camp = self.api.create_and_approve("fw-e2e-rev", ["VIN-E2E-REVOKED"])
        res = ecu.run()
        self.assertEqual(res.state["slot_a"]["version"], "1.0.0")
        self.assertEqual(self.api.deployment(camp["deployments"][0]["id"])["error_code"], "REVOKED_KEY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
