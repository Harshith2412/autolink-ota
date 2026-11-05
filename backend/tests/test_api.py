"""Backend tests (unittest; also collected by pytest). IDs BT-xxx map to requirements."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "firmware" / "tools"))

from app import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.security.manifest import signing_payload  # noqa: E402
from autolink_fw import build_manifest, public_b64, signing_payload as tool_payload  # noqa: E402

HW = "ALK-TCU-R1"
PASSWORD = "correct-horse-battery-staple"


def test_key(label: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(f"autolink-test-only:{label}".encode()).digest())


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.key = test_key("trusted")
        trust = {"keys": [{"key_id": "test-key-1", "public_key_b64": public_b64(self.key.public_key())},
                          {"key_id": "test-key-revoked", "public_key_b64": public_b64(test_key("revoked").public_key())}],
                 "revoked": ["test-key-revoked"]}
        (d / "trust.json").write_text(json.dumps(trust))
        self.settings = Settings(environment="test", database_url=f"sqlite:///{d / 'db.sqlite'}",
                                 jwt_secret="x" * 48, blob_dir=str(d / "blobs"),
                                 trust_store_path=str(d / "trust.json"), cors_origins=("http://localhost:5173",),
                                 password_iterations=1000)
        self.app = create_app(self.settings)
        self.client = self.app.test_client()
        users = self.app.extensions["services"].users
        for name, role in (("admin", "admin"), ("admin2", "admin"), ("engineer", "engineer"), ("viewer", "viewer")):
            users.create(name, PASSWORD, role)
        self.tokens = {n: self.login(n) for n in ("admin", "admin2", "engineer", "viewer")}

    def tearDown(self):
        self.app.extensions["db"].close_thread_connection()
        self.tmp.cleanup()

    # -- helpers
    def login(self, username: str) -> str:
        r = self.client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()["access_token"]

    def h(self, user: str) -> dict:
        return {"Authorization": f"Bearer {self.tokens[user]}"}

    def register(self, vid="VIN-0001", hw=HW) -> str:
        r = self.client.post("/api/v1/vehicles", headers=self.h("engineer"),
                             json={"vehicle_id": vid, "display_name": "Test car", "model": "Sim-1",
                                   "ecu_id": "ECU-TCU-01", "hardware_id": hw})
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["device_token"]

    def dev(self, vid: str, token: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Vehicle-Id": vid}

    def make_fw(self, fid="fw-110", version="1.1.0", hw=HW, key=None, key_id="test-key-1", counter=1, image=None):
        image = image or (f"firmware {fid} {version}\n".encode() * 300)
        m = build_manifest(key or self.key, key_id, image, fid, version, hw, counter, "1.0.0", "notes", False)
        return m, image

    def upload(self, m, image, user="engineer"):
        return self.client.post("/api/v1/firmware", headers=self.h(user), content_type="multipart/form-data",
                                data={"manifest": (io.BytesIO(json.dumps(m).encode()), "manifest.json"),
                                      "image": (io.BytesIO(image), "fw.bin")})

    def heartbeat(self, vid, token, seq=0, version="1.0.0", state="IDLE", telemetry=None):
        return self.client.post("/api/v1/device/heartbeat", headers=self.dev(vid, token), json={
            "vehicle_id": vid, "ecu_id": "ECU-TCU-01", "hardware_id": HW, "firmware_version": version,
            "active_slot": "A", "update_state": state, "last_command_seq": seq,
            "telemetry": telemetry or {"speed_kph": 50, "battery_v": 12.6, "coolant_c": 85, "rssi_dbm": -70}})

    def approved_campaign(self, vid="VIN-0001", fid="fw-110"):
        r = self.client.post("/api/v1/campaigns", headers=self.h("engineer"),
                             json={"name": "Rollout", "firmware_id": fid, "vehicle_ids": [vid]})
        self.assertEqual(r.status_code, 201, r.get_json())
        cid = r.get_json()["id"]
        r = self.client.post(f"/api/v1/campaigns/{cid}/approve", headers=self.h("admin"))
        self.assertEqual(r.status_code, 200, r.get_json())
        return cid, r.get_json()["deployments"][0]["id"]


class AuthTests(ApiTestCase):
    def test_bt001_login_failure_is_audited(self):
        r = self.client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-password!!"})
        self.assertEqual(r.status_code, 401)
        audit = self.client.get("/api/v1/audit-events?action=auth.login", headers=self.h("admin")).get_json()
        self.assertTrue(any(e["outcome"] == "DENIED" for e in audit["items"]))

    def test_bt002_missing_tampered_and_alg_none_tokens_rejected(self):
        self.assertEqual(self.client.get("/api/v1/vehicles").status_code, 401)
        bad = self.tokens["viewer"][:-3] + "abc"
        self.assertEqual(self.client.get("/api/v1/vehicles", headers={"Authorization": f"Bearer {bad}"}).status_code, 401)
        claims = jwt.decode(self.tokens["viewer"], options={"verify_signature": False})
        claims["role"] = "admin"
        forged = jwt.encode(claims, key=None, algorithm="none")
        self.assertEqual(self.client.get("/api/v1/audit-events", headers={"Authorization": f"Bearer {forged}"}).status_code, 401)
        other = jwt.encode(claims, "y" * 48, algorithm="HS256")
        self.assertEqual(self.client.get("/api/v1/audit-events", headers={"Authorization": f"Bearer {other}"}).status_code, 401)

    def test_bt003_expired_token_rejected(self):
        claims = jwt.decode(self.tokens["admin"], options={"verify_signature": False})
        claims["exp"] = int(time.time()) - 10
        tok = jwt.encode(claims, self.settings.jwt_secret, algorithm="HS256")
        self.assertEqual(self.client.get("/api/v1/vehicles", headers={"Authorization": f"Bearer {tok}"}).status_code, 401)

    def test_bt004_role_enforcement(self):
        self.assertEqual(self.client.post("/api/v1/vehicles", headers=self.h("viewer"), json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/audit-events", headers=self.h("engineer")).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/vehicles", headers=self.h("viewer")).status_code, 200)

    def test_bt005_role_reloaded_from_database(self):
        # Demoting a user takes effect immediately, even with a still-valid JWT.
        db = self.app.extensions["db"]
        with db.transaction() as c:
            c.execute("UPDATE users SET role='viewer' WHERE username='admin'")
        self.assertEqual(self.client.get("/api/v1/audit-events", headers=self.h("admin")).status_code, 403)

    def test_bt006_cors_allowlist_only(self):
        r = self.client.get("/health", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "http://localhost:5173")
        r = self.client.get("/health", headers={"Origin": "http://evil.example"})
        self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))


class VehicleAndFirmwareTests(ApiTestCase):
    def test_bt010_vehicle_registration_validation(self):
        self.register()
        r = self.client.post("/api/v1/vehicles", headers=self.h("engineer"),
                             json={"vehicle_id": "VIN-0001", "display_name": "x", "model": "y",
                                   "ecu_id": "E", "hardware_id": HW})
        self.assertEqual(r.status_code, 409)
        r = self.client.post("/api/v1/vehicles", headers=self.h("engineer"),
                             json={"vehicle_id": "../etc", "display_name": "x", "model": "y", "ecu_id": "E",
                                   "hardware_id": HW, "extra": 1})
        self.assertEqual(r.status_code, 422)
        fields = {e["field"] for e in r.get_json()["error"]["details"]}
        self.assertEqual(fields, {"vehicle_id", "extra"})

    def test_bt011_device_token_stored_hashed_only(self):
        token = self.register()
        stored = self.app.extensions["db"].scalar("SELECT device_token_hash FROM vehicles WHERE id='VIN-0001'")
        self.assertNotEqual(stored, token)
        self.assertEqual(stored, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn("device_token", self.client.get("/api/v1/vehicles/VIN-0001", headers=self.h("viewer")).get_json())

    def test_bt012_valid_firmware_upload(self):
        m, img = self.make_fw()
        r = self.upload(m, img)
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertTrue(r.get_json()["signature_verified"])
        self.assertEqual(self.upload(m, img).status_code, 409)

    def test_bt013_invalid_firmware_rejected_and_audited(self):
        m, img = self.make_fw()
        cases = {
            "BAD_SIGNATURE": (dict(m, release_notes="tampered"), img),
            "DIGEST_MISMATCH": (m, img[:-1] + b"X"),
            "UNKNOWN_KEY": self.make_fw(fid="fw-u", key_id="nobody", key=test_key("x")),
            "REVOKED_KEY": self.make_fw(fid="fw-r", key_id="test-key-revoked", key=test_key("revoked")),
            "MALFORMED": (dict(m, firmware_id="../../escape"), img),
        }
        for reason, (mm, ii) in cases.items():
            r = self.upload(mm, ii)
            self.assertEqual(r.status_code, 422, reason)
            self.assertEqual(r.get_json()["error"]["details"]["reason"], reason)
        audit = self.client.get("/api/v1/audit-events?action=firmware.upload", headers=self.h("admin")).get_json()
        self.assertEqual(sum(1 for e in audit["items"] if e["outcome"] == "DENIED"), 5)
        self.assertEqual(self.client.get("/api/v1/firmware", headers=self.h("viewer")).get_json()["total"], 0)

    def test_bt014_viewer_cannot_upload(self):
        m, img = self.make_fw()
        self.assertEqual(self.upload(m, img, user="viewer").status_code, 403)

    def test_bt015_signing_payload_matches_tool_and_ecu_fixture(self):
        m, _ = self.make_fw()
        self.assertEqual(signing_payload(m), tool_payload(m))
        fx = json.loads((ROOT / "ecu/tests/fixtures/v110.manifest.json").read_text())
        sig = base64.b64decode(fx["signature"])
        test_key("trusted").public_key().verify(sig, signing_payload(fx))  # raises if mismatch

    def test_bt016_pagination_validation(self):
        self.assertEqual(self.client.get("/api/v1/vehicles?limit=0", headers=self.h("viewer")).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/vehicles?limit=abc", headers=self.h("viewer")).status_code, 422)
        for i in range(3):
            self.register(f"VIN-P{i}")
        page = self.client.get("/api/v1/vehicles?limit=2&offset=1", headers=self.h("viewer")).get_json()
        self.assertEqual((page["total"], len(page["items"])), (3, 2))


class CampaignTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.token = self.register()
        self.heartbeat("VIN-0001", self.token)
        m, img = self.make_fw()
        self.assertEqual(self.upload(m, img).status_code, 201)

    def test_bt020_incompatible_targets_rejected(self):
        self.register("VIN-OTHER", hw="ALK-OTHER")
        r = self.client.post("/api/v1/campaigns", headers=self.h("engineer"),
                             json={"name": "x", "firmware_id": "fw-110", "vehicle_ids": ["VIN-0001", "VIN-OTHER"]})
        self.assertEqual(r.status_code, 422)
        bad = [v for v in r.get_json()["error"]["details"]["vehicles"] if not v["compatible"]]
        self.assertEqual([v["vehicle_id"] for v in bad], ["VIN-OTHER"])

    def test_bt021_downgrade_rejected_by_compatibility(self):
        self.heartbeat("VIN-0001", self.token, version="1.2.0")
        r = self.client.post("/api/v1/campaigns/validate", headers=self.h("engineer"),
                             json={"firmware_id": "fw-110", "vehicle_ids": ["VIN-0001"]})
        self.assertFalse(r.get_json()["all_compatible"])

    def test_bt022_approval_separation_of_duties(self):
        r = self.client.post("/api/v1/campaigns", headers=self.h("admin"),
                             json={"name": "x", "firmware_id": "fw-110", "vehicle_ids": ["VIN-0001"]})
        cid = r.get_json()["id"]
        self.assertEqual(self.client.post(f"/api/v1/campaigns/{cid}/approve", headers=self.h("engineer")).status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/campaigns/{cid}/approve", headers=self.h("admin")).status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/campaigns/{cid}/approve", headers=self.h("admin2")).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v1/campaigns/{cid}/approve", headers=self.h("admin2")).status_code, 409)

    def test_bt023_no_command_before_approval(self):
        self.client.post("/api/v1/campaigns", headers=self.h("engineer"),
                         json={"name": "x", "firmware_id": "fw-110", "vehicle_ids": ["VIN-0001"]})
        self.assertEqual(self.heartbeat("VIN-0001", self.token).get_json()["commands"], [])

    def test_bt024_full_device_flow_and_idempotent_events(self):
        cid, did = self.approved_campaign()
        cmds = self.heartbeat("VIN-0001", self.token).get_json()["commands"]
        self.assertEqual(len(cmds), 1)
        self.assertEqual((cmds[0]["deployment_id"], cmds[0]["firmware_id"]), (did, "fw-110"))
        hdr = self.dev("VIN-0001", self.token)
        man = self.client.get("/api/v1/device/firmware/fw-110/manifest", headers=hdr).get_json()
        full = self.client.get("/api/v1/device/firmware/fw-110/image", headers=hdr)
        self.addCleanup(full.close)
        self.assertEqual(hashlib.sha256(full.data).hexdigest(), man["sha256"])
        part = self.client.get("/api/v1/device/firmware/fw-110/image", headers={**hdr, "Range": "bytes=100-"})
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part.data, full.data[100:])
        part.close()
        # Consumed command is not re-sent.
        self.assertEqual(self.heartbeat("VIN-0001", self.token, seq=cmds[0]["seq"]).get_json()["commands"], [])

        def ev(seq, frm, to, **kw):
            return {"event_seq": seq, "kind": "STATE", "vehicle_id": "VIN-0001", "ecu_id": "ECU-TCU-01",
                    "deployment_id": did, "from_state": frm, "to_state": to, "detail": "", "error_code": "",
                    "firmware_version": "1.0.0", "timestamp": int(time.time()), **kw}
        batch = [ev(1, "IDLE", "UPDATE_AVAILABLE"), ev(2, "UPDATE_AVAILABLE", "DOWNLOADING"),
                 ev(3, "HEALTH_CHECK", "COMMITTED"),
                 {"event_seq": 4, "kind": "DTC", "vehicle_id": "VIN-0001", "deployment_id": did, "code": "U3031",
                  "severity": "WARNING", "description": "x", "timestamp": int(time.time())}]
        r = self.client.post("/api/v1/device/events", headers=hdr, json={"events": batch})
        self.assertEqual(r.get_json(), {"accepted": 4, "duplicates": 0})
        r = self.client.post("/api/v1/device/events", headers=hdr, json={"events": batch})
        self.assertEqual(r.get_json(), {"accepted": 0, "duplicates": 4})
        # A late out-of-order event must not regress the terminal status.
        self.client.post("/api/v1/device/events", headers=hdr, json={"events": [ev(5, "IDLE", "UPDATE_AVAILABLE")]})
        dep = self.client.get(f"/api/v1/deployments/{did}", headers=self.h("viewer")).get_json()
        self.assertEqual(dep["status"], "SUCCEEDED")
        self.assertEqual(len(dep["events"]), 5)
        diags = self.client.get("/api/v1/vehicles/VIN-0001/diagnostics", headers=self.h("viewer")).get_json()
        self.assertIn("U3031", [d["code"] for d in diags["items"]])

    def test_bt025_device_authentication_and_impersonation(self):
        other_token = self.register("VIN-0002")
        self.assertEqual(self.heartbeat("VIN-0001", "wrong-token").status_code, 401)
        r = self.client.post("/api/v1/device/heartbeat", headers=self.dev("VIN-0002", other_token),
                             json={"vehicle_id": "VIN-0001", "ecu_id": "E", "hardware_id": HW, "firmware_version": "1.0.0",
                                   "active_slot": "A", "update_state": "IDLE", "last_command_seq": 0})
        self.assertEqual(r.status_code, 403)
        # A user JWT is not a device credential.
        self.assertEqual(self.client.post("/api/v1/device/heartbeat", headers={**self.h("admin"), "X-Vehicle-Id": "VIN-0001"},
                                          json={}).status_code, 401)

    def test_bt026_firmware_only_served_to_targeted_vehicles(self):
        other_token = self.register("VIN-0002")
        self.approved_campaign()
        hdr = self.dev("VIN-0002", other_token)
        self.assertEqual(self.client.get("/api/v1/device/firmware/fw-110/manifest", headers=hdr).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/device/firmware/fw-110/image", headers=hdr).status_code, 404)

    def test_bt027_events_cannot_touch_other_vehicles_deployments(self):
        other_token = self.register("VIN-0002")
        _, did = self.approved_campaign()
        ev = {"event_seq": 1, "kind": "STATE", "vehicle_id": "VIN-0002", "deployment_id": did,
              "from_state": "HEALTH_CHECK", "to_state": "COMMITTED", "timestamp": 1}
        self.client.post("/api/v1/device/events", headers=self.dev("VIN-0002", other_token), json={"events": [ev]})
        dep = self.client.get(f"/api/v1/deployments/{did}", headers=self.h("viewer")).get_json()
        self.assertEqual(dep["status"], "PENDING")

    def test_bt028_expired_command_not_delivered(self):
        _, did = self.approved_campaign()
        with self.app.extensions["db"].transaction() as c:
            c.execute("UPDATE deployments SET expires_at=? WHERE id=?", (int(time.time()) - 1, did))
        self.assertEqual(self.heartbeat("VIN-0001", self.token).get_json()["commands"], [])
        dep = self.client.get(f"/api/v1/deployments/{did}", headers=self.h("viewer")).get_json()
        self.assertEqual(dep["status"], "EXPIRED")

    def test_bt029_telemetry_persisted_and_out_of_range_flagged(self):
        self.heartbeat("VIN-0001", self.token, telemetry={"speed_kph": 9999, "battery_v": 12.1})
        tel = self.client.get("/api/v1/vehicles/VIN-0001/telemetry", headers=self.h("viewer")).get_json()["items"]
        self.assertEqual(len(tel), 2)
        self.assertIsNone(tel[-1]["speed_kph"])
        self.assertEqual(tel[-1]["battery_v"], 12.1)
        diags = self.client.get("/api/v1/diagnostics?severity=WARNING", headers=self.h("viewer")).get_json()["items"]
        self.assertEqual(diags[0]["code"], "C0002")

    def test_bt030_fleet_summary(self):
        self.approved_campaign()
        s = self.client.get("/api/v1/fleet/summary", headers=self.h("viewer")).get_json()
        self.assertEqual(s["vehicles_total"], 1)
        self.assertEqual(s["connectivity"]["ONLINE"], 1)
        self.assertEqual(s["active_deployments"], 1)
        self.assertEqual(s["firmware_distribution"], [{"version": "1.0.0", "count": 1}])

    def test_bt031_invalid_event_batch_rejected(self):
        hdr = self.dev("VIN-0001", self.token)
        r = self.client.post("/api/v1/device/events", headers=hdr,
                             json={"events": [{"event_seq": "1", "kind": "STATE"}]})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/v1/device/events", headers=hdr, json={"events": [{}] * 300})
        self.assertEqual(r.status_code, 422)

    def test_bt032_cancel_campaign_withdraws_commands(self):
        cid, _ = self.approved_campaign()
        self.assertEqual(self.client.post(f"/api/v1/campaigns/{cid}/cancel", headers=self.h("admin")).status_code, 200)
        self.assertEqual(self.heartbeat("VIN-0001", self.token).get_json()["commands"], [])


class SystemTests(ApiTestCase):
    def test_bt040_health_and_metrics(self):
        self.assertEqual(self.client.get("/health").get_json()["status"], "ok")
        self.client.get("/api/v1/vehicles")
        self.assertIn("autolink_http_requests_total", self.client.get("/metrics").get_data(as_text=True))

    def test_bt041_errors_have_consistent_shape(self):
        r = self.client.get("/api/v1/vehicles/NOPE", headers=self.h("viewer"))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], "not_found")
        r = self.client.get("/api/v1/does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertIn("error", r.get_json())


if __name__ == "__main__":
    unittest.main(verbosity=2)
