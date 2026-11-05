# Three-minute demo script

Preparation (before the call): `make ecu frontend setup`, then in terminal 1 `make serve`. Open
http://127.0.0.1:8000 and sign in as `approver`. Keep terminal 2 at the repository root.

**0:00 – 0:20 — Frame it.** "AutoLink OTA updates vehicle firmware safely. The vehicle side is a C++ ECU
simulator; the cloud is a Python backend; this is the operator dashboard. The key idea: the vehicle trusts only a
signature, never the server."

**0:20 – 0:50 — Register and connect a vehicle.**
```bash
python3 scripts/demo.py register VIN-DEMO-001
AUTOLINK_DEVICE_TOKEN=$(cat .dev/ecu-VIN-DEMO-001.token) ecu/build-make/autolink-ecu --config .dev/ecu-VIN-DEMO-001.json
```
Show Vehicles: online, firmware 1.0.0, telemetry charts filling in. "The device token was shown once; the backend
stores only its hash."

**0:50 – 1:20 — Release firmware.** In terminal 3:
```bash
python3 scripts/demo.py release 1.1.0
python3 scripts/demo.py release 1.2.0 --corrupt
```
"1.1.0 is signed with Ed25519 and accepted. 1.2.0's bytes no longer match the signed digest, so the backend
rejects it." Show the Firmware page and the denied entry in the Audit log.

**1:20 – 2:10 — Campaign and update.** On Campaigns, draft "TCU 1.1.0 pilot" as engineer (or run
`python3 scripts/demo.py campaign fw-tcu-1.1.0 VIN-DEMO-001`, which drafts and approves with two accounts). Point
out that the creator cannot approve. Approve, then watch the lifecycle rail move through download, verify, stage,
activate, health check and commit. Open the vehicle page: 1.1.0, slot B.

**2:10 – 2:45 — Failure handling.** "What if power fails mid-activation?" Show the fault report, or run:
```bash
python3 experiments/runner/run_matrix.py --only power_loss_activating --reps 1 --out /tmp/demo
```
"The ECU had already switched slots; on reboot the unconfirmed boot is rolled back to last-known-good, and the
cloud records ROLLED_BACK." Mention the matrix: 175 runs, 25 scenarios, 0 consistency violations.

**2:45 – 3:00 — Close honestly.** "It's a prototype: simulated flash, no TLS or MQTT yet, built offline with Flask
and SQLite. The known-limitations doc lists exactly what isn't verified."
