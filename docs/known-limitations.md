# Known limitations

This is an educational research prototype. It is not certified, not compliant with any standard, and not
production automotive software.

## Deviations from the original brief (offline build environment)

| Brief | Implemented | Why | Path to the brief's choice |
|---|---|---|---|
| FastAPI + Pydantic | Flask + `app/validation.py` | Not installable offline | Routes are thin; port `api/*.py` to FastAPI routers and `validation.Field` schemas to Pydantic models. Services and repositories stay. |
| SQLAlchemy + Alembic + PostgreSQL | stdlib `sqlite3`, SQL migrations | Not installable; no database server | SQL is mostly portable (`ON CONFLICT DO NOTHING`, no SQLite-only types). Needed: psycopg driver, `%s` placeholders, Alembic baseline from `0001`/`0002`. |
| MQTT | HTTP device channel | No broker or client library | Topic design in `docs/api/vehicle-protocol.md`; implement a `CloudLink` over an MQTT client and a backend subscriber. |
| CMake + GoogleTest | Makefile + GoogleTest-API-compatible harness (verified); CMake file provided | CMake and GoogleTest unavailable | Run the CMake build; tests compile against real GoogleTest unchanged. |
| Vite, React Router, TanStack Query, Recharts, Vitest, RTL | esbuild build, hash router, `useApi` hook, SVG charts, node:test, Playwright | Packages unavailable offline | `package.json` includes Vite; swapping in the libraries is a contained refactor. |
| HTTPS / TLS | Plain HTTP on localhost | No TLS client library headers for the ECU | Terminate TLS at a proxy; add an HTTPS `CloudLink` (libcurl) on the ECU. |

## Unverified artefacts

Never executed: Dockerfiles, `docker-compose.yml`, Terraform, GitHub Actions workflow, CMake build,
`S3BlobStore`, TypeScript type-checking (`tsc`), the Vite build.

## Functional gaps

- Trust-store rotation and key revocation distribution are not implemented (T-14).
- Commands are not signed end-to-end; they rely on the transport (T-05).
- One ECU per vehicle; no multi-ECU orchestration or dependency ordering.
- No delta updates, no download scheduling or battery/driving-state preconditions.
- No rate limiting, login throttling, token revocation or audit-log tamper evidence.
- Telemetry retention and downsampling are not implemented; tables grow without bound.
- Campaign progress is polled by the dashboard (2–5 s), not pushed.
- The Flask development server is used in the verified path; production would use gunicorn (in the Dockerfile).

## Simulation boundaries

Slots are files; "reboot" is a state change; health checks are digest checks plus injected or signed failure
flags; anti-rollback state is in a writable file; DTC codes are invented within a manufacturer-specific range.
Measured latencies are loopback numbers with a 256 KiB image and say nothing about cellular links or flash speed.

## Standards

ISO 26262, ISO/SAE 21434, UNECE R155/R156, Automotive SPICE and AUTOSAR informed the structure (requirements
with IDs, traceability, threat analysis, update recovery and audit), but no work product claims conformance.
See `docs/architecture/standards-notes.md`.
