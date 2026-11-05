# Software requirements specification

AutoLink OTA is an educational research prototype. Requirement IDs are referenced by code comments, tests and
`traceability.md`. "Verified" in this project means an automated test or experiment exercises the requirement;
it does not imply certification or production readiness.

## ECU update client

| ID | Requirement |
|---|---|
| REQ-ECU-001 | The ECU shall implement the update states IDLE, UPDATE_AVAILABLE, DOWNLOADING, VERIFYING, STAGING, READY_TO_ACTIVATE, ACTIVATING, HEALTH_CHECK, COMMITTED and the failure states DOWNLOAD_FAILED, VERIFICATION_FAILED, STAGING_FAILED, ACTIVATION_FAILED, RECOVERY_IN_PROGRESS, ROLLED_BACK, RECOVERY_FAILED. |
| REQ-ECU-002 | Only transitions listed in the transition table shall be accepted; any other transition shall be rejected with an error. |
| REQ-ECU-003 | No path shall reach STAGING except through VERIFYING. |
| REQ-ECU-004 | RECOVERY_FAILED shall be a latched state cleared only by an explicit service action. |
| REQ-ECU-005 | Every state change shall be persisted atomically before the next action begins. |
| REQ-ECU-006 | After a restart or power loss the ECU shall resume or roll back an interrupted update based on the persisted state. |
| REQ-ECU-007 | The ECU shall maintain two firmware slots (A/B) and a last-known-good slot pointer. |
| REQ-ECU-008 | A new image shall be committed only after a post-activation health check passes; otherwise the ECU shall revert to the last-known-good slot. |
| REQ-ECU-009 | The ECU shall record diagnostic trouble codes for update failures and recoveries and report them to the cloud. |
| REQ-ECU-010 | The ECU shall publish heartbeat telemetry including firmware version, slot, update state and signals. |
| REQ-ECU-011 | Events that cannot be delivered shall be queued persistently (bounded) and retried. |

## Security

| ID | Requirement |
|---|---|
| REQ-SEC-001 | Firmware manifests shall be signed with Ed25519; the ECU and the backend shall each verify the signature independently. |
| REQ-SEC-002 | The ECU shall verify the image SHA-256 and size against the signed manifest before staging. |
| REQ-SEC-003 | Packages shall be rejected if the signing key is unknown or revoked. |
| REQ-SEC-004 | Packages shall be rejected if the target hardware does not match the ECU. |
| REQ-SEC-005 | Anti-rollback: packages with a version not newer than the installed one, or a security counter below the persisted floor, shall be rejected. The floor shall rise only on commit. |
| REQ-SEC-006 | Install commands shall carry a per-vehicle monotonic sequence number and an expiry; duplicates, replays and expired commands shall not execute. |
| REQ-SEC-007 | Firmware size shall be limited (16 MiB) on the backend and the ECU. |
| REQ-SEC-008 | Identifiers used in paths or URLs shall be validated against a safe character set; storage keys shall not derive from user input. |
| REQ-SEC-009 | Management APIs shall require authentication with short-lived signed tokens; roles shall be re-checked against the database on each request. |
| REQ-SEC-010 | Vehicles shall authenticate with a per-vehicle credential stored only as a hash; a vehicle shall not act as, or read firmware for, another vehicle. |
| REQ-SEC-011 | Campaign approval shall require an administrator other than the campaign's creator. |
| REQ-SEC-012 | Security-relevant actions, including denied ones, shall be written to an audit log. |
| REQ-SEC-013 | No production secret shall be stored in the repository. |

## Cloud backend

| ID | Requirement |
|---|---|
| REQ-BE-001 | The backend shall provide REST APIs for vehicles, firmware, campaigns, deployments, diagnostics, telemetry, audit events and health. |
| REQ-BE-002 | Campaign creation shall validate hardware compatibility, version ordering, minimum installed version and conflicting active deployments. |
| REQ-BE-003 | Device event ingestion shall be idempotent by (vehicle, event_seq). |
| REQ-BE-004 | A deployment's terminal status shall never be overwritten by later or out-of-order events. |
| REQ-BE-005 | The backend's view of a vehicle's firmware version shall converge to the ECU's actual version even when heartbeats are lost. |
| REQ-BE-006 | List endpoints shall paginate and validate their parameters; errors shall use one JSON shape. |
| REQ-BE-007 | Database schema changes shall be applied by ordered migrations. |
| REQ-BE-008 | Out-of-range telemetry shall be discarded and flagged as a diagnostic. |

## Dashboard

| ID | Requirement |
|---|---|
| REQ-UI-001 | The dashboard shall show fleet overview, vehicle detail, firmware, campaigns, diagnostics and audit pages using live backend data. |
| REQ-UI-002 | Controls shall be hidden or refused according to role; refused actions surface the backend's error. |
| REQ-UI-003 | Each deployment's lifecycle and failure point shall be visualised. |
| REQ-UI-004 | Pages shall have loading, error and empty states; destructive or fleet-wide actions shall require confirmation. |
| REQ-UI-005 | Pages shall be usable by keyboard, have labelled controls and not scroll horizontally at 390 px width. |

## Reliability targets (experiments)

| ID | Requirement |
|---|---|
| REQ-REL-001 | Under the defined network faults, updates shall eventually commit. |
| REQ-REL-002 | Under every injected fault the system shall end in a consistent state: ECU idle (or latched), on exactly the old or the new image, with the cloud record agreeing. |
