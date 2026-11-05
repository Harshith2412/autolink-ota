# Resume material

Every number below comes from `docs/verification/test-results.md` or `docs/verification/fault-injection-report.md`.
Latency figures are deliberately left out: they were measured on loopback with a simulated ECU and would mislead
a reader about real vehicles.

## Project description (two lines)

**AutoLink OTA**: secure over-the-air update platform for connected vehicles. C++17 ECU simulator with A/B
partitions and Ed25519-verified updates, Python REST backend, React/TypeScript fleet dashboard, and a
fault-injection harness that exercises power loss, process kills and network faults against the real stack.

## STAR bullets (ATS-friendly)

- Built a C++17 simulated automotive ECU (about 2,500 lines) with a 16-state OTA update state machine, A/B firmware
  slots, OpenSSL Ed25519 signature and SHA-256 verification, anti-rollback counters and atomic crash-safe
  persistence; 32 unit tests, including forked power-loss tests, verify that interrupted updates resume or roll
  back to last-known-good firmware.
- Developed a Python REST backend and React/TypeScript dashboard for vehicle registration, signed firmware upload,
  two-person campaign approval, telemetry and diagnostics, with JWT role-based access control, per-vehicle device
  credentials, idempotent event ingestion and audit logging; covered by 28 API tests, 5 integration tests against
  the compiled ECU, and Playwright browser checks.
- Designed a reproducible fault-injection matrix of 175 seeded executions across 25 scenarios (power loss at 7
  update states, SIGKILL, connection resets, truncated transfers, outages, backend restarts, corrupted and
  mis-signed packages); all 175 met their expected outcome with 0 state-consistency violations, and the
  matrix exposed and drove the fix of a cloud/vehicle version-desynchronisation defect under heartbeat loss.

## Skills line

C++17, OpenSSL, POSIX, Python, Flask, REST, SQL/SQLite, React, TypeScript, Playwright, Ed25519, OTA updates,
A/B partitioning, fault injection, threat modelling (STRIDE), requirements traceability, Terraform (AWS S3,
CloudWatch, IAM), GitHub Actions.

## What to say if asked about the stack

The brief targeted FastAPI, PostgreSQL and MQTT. The project was built in an offline environment, so I used what
could be run and tested (Flask, SQLite, HTTP) and documented the migration path. Be ready to explain that choice:
"I would rather show a working, tested system than code I never ran."
