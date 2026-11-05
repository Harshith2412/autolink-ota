# Fault-injection report

Generated from `experiments/results/summary.json` and `results.jsonl` (175 executions,
generated 2026-11-05T15:36:20+00:00). Re-run with `make experiments`; seeds are fixed (`base_seed`
20261105, seed = base + 1000 × repetition + scenario index), so `--only <scenario>` reproduces a run.

## Setup

Every execution uses the real backend process (Flask, SQLite) and the compiled C++ ECU binary over HTTP on
loopback, a fresh vehicle, and a 262208-byte signed image. Network faults are
injected by a TCP proxy (`experiments/runner/stack.py: FaultProxy`). Because TCP retransmits lost packets, the proxy
models loss and disconnection per connection (resets, refusals, truncated responses, latency) rather than per
packet. Power loss is the ECU exiting immediately after durably persisting a state (`--crash-after`); process
termination is an external `SIGKILL` at a random time. Environment: Linux-6.18.44-fc-v236-x86_64-with-glibc2.39,
1 CPU.

## Results

**175 of 175 executions met their expected outcome; 0 did not.**

| Metric | Value |
|---|---|
| Successful update rate (normal + network-fault scenarios) | 100.0% |
| Invalid-package rejection rate (cloud and ECU) | 100.0% |
| Recovery success rate (power loss, kill, health-check and recovery faults) | 100.0% |
| State-consistency violations | 0 |
| Duplicate-command handling success | 100.0% |
| Update latency, approval to ECU done (n=56) | mean 0.989 s, p50 0.175 s, p95 2.898 s, max 2.901 s |
| ECU recovery time, first failure state to COMMITTED/ROLLED_BACK (n=57) | mean 88.8 ms, p50 8.0 ms, p95 371.0 ms, max 435 ms |

A consistency check runs after every ECU execution: ECU idle (or latched in RECOVERY_FAILED when expected), active
version is exactly the old or the new image, the active slot's bytes hash to the recorded digest, no undelivered
events remain, the cloud deployment status agrees with the ECU's version, and the cloud's reported firmware
version equals the ECU's.

Latency is dominated by the scenario, not the update: on loopback a clean update takes well under a second, while
the 50–300 ms latency, disconnection and backend-restart scenarios add their injected delays and outages. These figures say nothing about
cellular links, real flash write speeds or production servers.

## Per-scenario outcomes

| Scenario | Fault | Expected | Observed | Passed | Mean update s | Mean recovery ms | Download retries (sum) |
|---|---|---|---|---|---|---|---|
| `baseline_success` | No faults; signed update commits | SUCCEEDED | SUCCEEDED | 7/7 | 0.057 | n/a | 0 |
| `corrupted_artifact` | Image bit-flipped after download | REJECTED | REJECTED | 7/7 | 0.038 | n/a | 0 |
| `ecu_revoked_signing_key` | ECU trust store revokes the signing key the cloud still trusts | REJECTED | REJECTED | 7/7 | 0.042 | n/a | 0 |
| `api_invalid_signature_upload` | Manifest field changed after signing | 422:BAD_SIGNATURE | 422:BAD_SIGNATURE | 7/7 | n/a | n/a | n/a |
| `api_untrusted_key_upload` | Signed by an attacker key reusing a trusted key id | 422:BAD_SIGNATURE | 422:BAD_SIGNATURE | 7/7 | n/a | n/a | n/a |
| `api_wrong_hardware_campaign` | Campaign targets incompatible hardware | 422 | 422 | 7/7 | n/a | n/a | n/a |
| `api_rollback_campaign` | Campaign would downgrade a vehicle | 422 | 422 | 7/7 | n/a | n/a | n/a |
| `interrupted_download` | Transfer aborted after a random byte count; resume with Range | SUCCEEDED | SUCCEEDED | 7/7 | 0.175 | 139 | 7 |
| `power_loss_downloading` | Process exits right after persisting DOWNLOADING; power restored | SUCCEEDED | SUCCEEDED | 7/7 | 0.174 | 143 | 7 |
| `power_loss_verifying` | Process exits right after persisting VERIFYING; power restored | SUCCEEDED | SUCCEEDED | 7/7 | 0.062 | n/a | 0 |
| `power_loss_staging` | Process exits right after persisting STAGING; power restored | SUCCEEDED | SUCCEEDED | 7/7 | 0.061 | n/a | 0 |
| `power_loss_ready_to_activate` | Process exits right after persisting READY_TO_ACTIVATE; power restored | SUCCEEDED | SUCCEEDED | 7/7 | 0.059 | n/a | 0 |
| `power_loss_activating` | Process exits right after persisting ACTIVATING; power restored | ROLLED_BACK | ROLLED_BACK | 7/7 | 0.067 | 8 | 0 |
| `power_loss_health_check` | Process exits right after persisting HEALTH_CHECK; power restored | ROLLED_BACK | ROLLED_BACK | 7/7 | 0.071 | 8 | 0 |
| `power_loss_committed` | Process exits right after persisting COMMITTED; power restored | SUCCEEDED | SUCCEEDED | 7/7 | 0.057 | n/a | 0 |
| `health_check_failure` | Injected health-check failure after activation | ROLLED_BACK | ROLLED_BACK | 7/7 | 0.057 | 7 | 0 |
| `unhealthy_firmware` | Signed release whose self-test fails | ROLLED_BACK | ROLLED_BACK | 7/7 | 0.064 | 7 | 0 |
| `recovery_failure` | Health check fails and last-known-good image is corrupt | RECOVERY_FAILED | RECOVERY_FAILED | 7/7 | 0.052 | 7 | 0 |
| `process_kill` | SIGKILL at a random time while the update is in flight (20-40 ms link latency widens the window), then restart | SUCCEEDED/ROLLED_BACK | SUCCEEDED | 7/7 | 0.563 | 420 | 3 |
| `duplicate_commands` | Every command batch delivered twice | SUCCEEDED | SUCCEEDED | 7/7 | 0.051 | n/a | 0 |
| `network_delay` | 50-300 ms latency per connection | SUCCEEDED | SUCCEEDED | 7/7 | 2.433 | n/a | 0 |
| `packet_loss` | 25% of TCP connections reset | SUCCEEDED | SUCCEEDED | 7/7 | 0.180 | 352 | 4 |
| `truncated_responses` | 30% of responses cut mid-body | SUCCEEDED | SUCCEEDED | 7/7 | 0.172 | 287 | 5 |
| `network_disconnection` | All connections refused for 2 s after approval | SUCCEEDED | SUCCEEDED | 7/7 | 2.897 | n/a | 0 |
| `backend_restart` | Backend + SQLite process stopped for 1.5 s mid-update and restarted | SUCCEEDED | SUCCEEDED | 7/7 | 1.945 | n/a | 0 |

## Outcomes accepted but not observed

- `process_kill` accepts SUCCEEDED or ROLLED_BACK, but this run observed only SUCCEEDED; the ROLLED_BACK path was not exercised by this scenario (it is covered deterministically by the power-loss scenarios).

## Defects found by this matrix (fixed before the recorded run)

1. **Cloud firmware view depended on best-effort heartbeats** (found by `packet_loss`). If the proxy dropped the
   ECU's last heartbeat, the backend showed the old version although the ECU had committed the new one. Fix:
   migration `0002` and `VehicleRepository.apply_state_event` derive the vehicle's version from STATE events,
   which travel through the ECU's persistent, retried outbox and are applied in `event_seq` order.
2. **Harness: disconnection fault never injected.** `proxy={}` was falsy, so `network_disconnection` ran without a
   proxy. Fixed with an explicit `is not None` check.
3. **Harness: kill scenario rarely hit an update.** The ECU finishes a loopback update in under 20 ms, so a timed
   `SIGKILL` almost always landed after completion. The scenario now adds 20–40 ms link latency so kills land
   mid-update (most recorded runs show `INTERRUPTED` downloads that resumed after restart).
4. **Harness: duplicate firmware in `api_wrong_hardware_campaign`.** Repetitions reused one (hardware, version)
   pair, which the backend correctly refused with 409. The first full run recorded 169/175 with these 6 as
   harness errors (`experiments/results/history/run1-summary-with-harness-bug.json`); the scenario now uses a
   unique version per run and the matrix was re-run in full.

## Not covered

Real flash or bootloader behaviour, TLS, MQTT, PostgreSQL restarts (the "backend restart" scenario restarts the
Flask process and reopens SQLite), concurrent fleets (runs are sequential), and long-duration soak testing.
