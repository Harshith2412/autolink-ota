# REST API reference

Base path `/api/v1`. JSON in and out. Errors always have the shape
`{"error": {"code": "...", "message": "...", "details": ...}}`. List endpoints take `limit` (1–200, default 50)
and `offset` (≥ 0) and return `{"items", "total", "limit", "offset"}`. Every response carries `X-Request-Id`.

## Authentication

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/auth/login` | none | `{username, password}` → `{access_token, expires_in, user}`. HS256 JWT, 15 min default, `aud`/`iss` pinned. Failures are audited. |
| GET | `/auth/me` | viewer | Current user. |

Send `Authorization: Bearer <access_token>`. Roles: `viewer` < `engineer` < `admin`. The role is re-read from the
database on each request, so demotion is immediate (BT005).

## Vehicles

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/vehicles` | engineer | `{vehicle_id, display_name, model, ecu_id, hardware_id}` → 201 with `device_token` shown once. 409 if it exists. |
| GET | `/vehicles` | viewer | `q` search, `connectivity` = ONLINE / OFFLINE / NEVER_CONNECTED. |
| GET | `/vehicles/{id}` | viewer | Includes ECU fields, connectivity and recent `deployments`. |
| POST | `/vehicles/{id}/rotate-token` | admin | Issues a new device token; the old one stops working. |
| GET | `/vehicles/{id}/telemetry` | viewer | Latest samples, oldest first (`limit`). |
| GET | `/vehicles/{id}/diagnostics` | viewer | DTCs and cloud events for one vehicle. |
| GET | `/diagnostics` | viewer | Fleet-wide; filters `severity`, `vehicle_id`. |

## Firmware

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/firmware` | engineer | `multipart/form-data` with files `manifest` (JSON) and `image`. 201 on success; 422 `firmware_rejected` with `details.reason` ∈ MALFORMED, TOO_LARGE, UNKNOWN_KEY, REVOKED_KEY, BAD_SIGNATURE, DIGEST_MISMATCH; 409 for duplicate id or (hardware, version). |
| GET | `/firmware` | viewer | Release history, newest first. |
| GET | `/firmware/{id}` | viewer | Metadata plus the signed manifest. |

Manifest fields: `firmware_id, version, hardware_id, sha256, size, security_counter, min_current_version, key_id,
release_notes, simulate_unhealthy, signature`. The signature covers the canonical payload described in
`docs/security/security-design.md`.

## Campaigns and deployments

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/campaigns/validate` | engineer | `{firmware_id, vehicle_ids}` → per-vehicle compatibility and issues. |
| POST | `/campaigns` | engineer | `{name, firmware_id, vehicle_ids}` → 201, status PENDING_APPROVAL. 422 `incompatible_targets` with details. |
| GET | `/campaigns` | viewer | With progress counts. |
| GET | `/campaigns/{id}` | viewer | With deployments. |
| POST | `/campaigns/{id}/approve` | admin | Must not be the creator (403). Issues commands. 409 if not pending or targets changed. |
| POST | `/campaigns/{id}/cancel` | admin | Withdraws commands not yet delivered. |
| GET | `/deployments/{id}` | viewer | Deployment plus its ordered events. |

Deployment status: AWAITING_APPROVAL → PENDING → IN_PROGRESS → SUCCEEDED | REJECTED | ROLLED_BACK | FAILED |
RECOVERY_FAILED | EXPIRED | CANCELLED. Terminal statuses never change (BT024).

## Fleet, audit, system

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/fleet/summary` | viewer | Counts, connectivity, firmware distribution, alerts, recent deployments. |
| GET | `/audit-events` | admin | Filters `action` (prefix), `actor`. |
| GET | `/health` (no prefix) | none | 200 `{status: ok}` or 503. |
| GET | `/metrics` (no prefix) | none | Prometheus text: request counts, device heartbeats and events. Restrict at the proxy in deployment. |

## Example

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"engineer","password":"<from .dev/credentials.txt>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/api/v1/firmware -H "Authorization: Bearer $TOKEN" \
  -F manifest=@manifest.json -F image=@firmware.bin
```
