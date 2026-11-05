"""Browser end-to-end test: live backend serving the built dashboard, a real ECU
update, then Playwright (headless Chromium) checks what an operator sees.

Prerequisites: `make -C ecu`, frontend built into frontend/dist, Node + Playwright.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "runner"))
import stack  # noqa: E402
from stack import Api, Backend, Ecu, SigningKey, make_firmware  # noqa: E402

DIST = ROOT / "frontend" / "dist"


@unittest.skipUnless((DIST / "index.html").exists(), "frontend not built")
class DashboardEndToEnd(unittest.TestCase):
    def test_it010_dashboard_shows_real_update_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            os.environ["AUTOLINK_FRONTEND_DIST"] = str(DIST)
            key = SigningKey("dev-key-1")
            backend = Backend(work, [key])
            backend.bootstrap_users()
            backend.start()
            try:
                api = Api(backend.url)
                ecus = {}
                for vid in ("VIN-DASH-OK", "VIN-DASH-BAD"):
                    ecus[vid] = Ecu(work, vid, api.register_vehicle(vid), backend.url, [key])
                    ecus[vid].run("--cycles", "4")  # a few telemetry samples
                m, img = make_firmware(key, "fw-tcu-110", "1.1.0")
                api.upload_firmware(m, img)
                camp = api.create_and_approve("fw-tcu-110", list(ecus), name="TCU 1.1.0 pilot")
                self.assertEqual(ecus["VIN-DASH-OK"].run().exit_code, 0)
                self.assertEqual(ecus["VIN-DASH-BAD"].run("--corrupt-download").exit_code, 0)
                ecus["VIN-DASH-OK"].run("--cycles", "3")
                env = {**os.environ, "BASE_URL": backend.url, "ADMIN_USER": "admin2", "ADMIN_PASSWORD": stack.ADMIN2_PW,
                       "VEHICLE_ID": "VIN-DASH-OK", "BAD_VEHICLE_ID": "VIN-DASH-BAD", "CAMPAIGN_ID": camp["id"],
                       "SCREENSHOT_DIR": str(ROOT / "docs" / "portfolio" / "screenshots"),
                       "NODE_PATH": os.environ.get("NODE_PATH", str(ROOT / "frontend" / "node_modules"))}
                p = subprocess.run(["node", str(ROOT / "frontend/tests/e2e/dashboard.e2e.mjs")], env=env,
                                   cwd=ROOT / "frontend", capture_output=True, text=True, timeout=180)
                print(p.stdout, p.stderr[-2000:])
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr[-2000:])
            finally:
                backend.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
