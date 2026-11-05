# Vehicle-to-cloud protocol

## Implemented: HTTP device channel

Authentication: `Authorization: Bearer <device_token>` and `X-Vehicle-Id`. Tokens are 256-bit random values
stored as SHA-256 hashes. The payload's `vehicle_id` must equal the authenticated vehicle (403 and an audit entry
otherwise). User JWTs are not accepted here.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/device/heartbeat` | Status + telemetry in, pending commands out. |
| GET | `/api/v1/device/firmware/{id}/manifest` | Signed manifest; 404 unless a live deployment targets this vehicle with this firmware. |
| GET | `/api/v1/device/firmware/{id}/image` | Image bytes; supports `Range` (206) for resume. Same authorization. |
| POST | `/api/v1/device/events` | Batch of up to 256 events from the ECU outbox. |

Heartbeat request:

```json
{"vehicle_id": "VIN-1", "ecu_id": "ECU-TCU-01", "hardware_id": "ALK-TCU-R1", "firmware_version": "1.0.0",
 "active_slot": "A", "update_state": "IDLE", "last_command_seq": 0,
 "telemetry": {"speed_kph": 52.3, "battery_v": 12.48, "coolant_c": 86.1, "rssi_dbm": -66},
 "counters": {"updates_committed": 0, "rollbacks": 0, "boots": 1}}
```

Response: `{"commands": [{"seq": 1, "type": "install", "vehicle_id": "VIN-1", "deployment_id": "…",
"firmware_id": "fw-tcu-1.1.0", "expires_at": 1793000000}], "server_time": 1792913600}`.

Event (`kind` = STATE, DTC or COMMAND_REJECTED):

```json
{"event_seq": 7, "kind": "STATE", "vehicle_id": "VIN-1", "ecu_id": "ECU-TCU-01", "deployment_id": "…",
 "from_state": "HEALTH_CHECK", "to_state": "COMMITTED", "detail": "health check passed", "error_code": "",
 "firmware_version": "1.1.0", "timestamp": 1792913610}
```

## Delivery semantics

The channel is **at-least-once with idempotent consumers**; no part of the system assumes exactly-once delivery.

- Commands: the backend resends a PENDING command on every heartbeat until the ECU's `last_command_seq` passes
  it. The ECU executes a sequence number at most once and ignores lower or equal numbers (UT055,
  EXP:duplicate_commands).
- Events: the ECU keeps events in a persistent outbox (bounded to 256, oldest dropped first) until a POST
  succeeds. The backend deduplicates by `(vehicle_id, event_seq)` and never lets a later or replayed event
  overwrite a terminal deployment status (BT024).
- Heartbeats are best-effort. State the dashboard relies on (installed version) is also derived from the
  reliable event stream (REQ-BE-005).

## Designed, not implemented: MQTT mapping

MQTT was in the original brief but no broker or client library was available in the offline build environment,
so it is **not implemented**. The `CloudLink` interface (`ecu/include/autolink/ota_agent.hpp`) is the seam where an
MQTT transport would plug in; the semantics above carry over unchanged.

| Topic | Direction | QoS | Payload | Notes |
|---|---|---|---|---|
| `vehicles/{vehicle_id}/heartbeat` | vehicle → cloud | 0 | heartbeat body | Loss tolerated. |
| `vehicles/{vehicle_id}/telemetry` | vehicle → cloud | 0 | telemetry object | Could be split from heartbeat. |
| `vehicles/{vehicle_id}/connectivity` | vehicle → cloud | 1, retained | `{"online": bool}` | Set `false` as the Last Will. |
| `vehicles/{vehicle_id}/ota/status` | vehicle → cloud | 1 | STATE / COMMAND_REJECTED events | Dedup by `event_seq`. |
| `vehicles/{vehicle_id}/diagnostics` | vehicle → cloud | 1 | DTC events | Dedup by `event_seq`. |
| `vehicles/{vehicle_id}/ota/commands` | cloud → vehicle | 1, retained | latest pending command | ECU dedups by `seq`; retained so a reconnecting ECU sees it. |

Broker requirements for a real deployment: TLS 1.2+, per-vehicle client certificates or credentials, and ACLs
restricting each client to its own `vehicles/{id}/#` subtree (publish to uplink topics, subscribe to its own
commands). Firmware images stay on HTTPS with Range support; MQTT would carry only control messages.
