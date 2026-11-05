"""Service layer: business rules, authorization-relevant checks, auditing.
API handlers stay thin and call into these services."""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from flask import has_request_context, request

from ..config import Settings
from ..db import Database
from ..errors import ApiError, conflict, forbidden, not_found, unauthorized, validation_error
from ..repositories import (AuditRepository, CampaignRepository, DeploymentRepository, EventRepository,
                            FirmwareRepository, UserRepository, VehicleRepository)
from ..security import passwords, tokens
from ..security.manifest import ManifestError, TrustStore, validate_manifest_structure, verify_signature
from ..storage.blobs import BlobStore
from ..validation import Field, is_safe_id, semver_tuple, validate

ACTIVE_STATUSES = ("PENDING", "IN_PROGRESS")
TERMINAL_STATUSES = {"SUCCEEDED", "REJECTED", "ROLLED_BACK", "FAILED", "RECOVERY_FAILED", "EXPIRED", "CANCELLED"}
FAILED_STATUSES = {"REJECTED", "ROLLED_BACK", "FAILED", "RECOVERY_FAILED", "EXPIRED"}
ECU_STATES = {"IDLE", "UPDATE_AVAILABLE", "DOWNLOADING", "VERIFYING", "STAGING", "READY_TO_ACTIVATE", "ACTIVATING",
              "HEALTH_CHECK", "COMMITTED", "DOWNLOAD_FAILED", "VERIFICATION_FAILED", "STAGING_FAILED",
              "ACTIVATION_FAILED", "RECOVERY_IN_PROGRESS", "ROLLED_BACK", "RECOVERY_FAILED"}
# ECU state -> deployment status. States not listed keep the deployment IN_PROGRESS.
TERMINAL_STATE_MAP = {"COMMITTED": "SUCCEEDED", "VERIFICATION_FAILED": "REJECTED", "STAGING_FAILED": "FAILED",
                      "ROLLED_BACK": "ROLLED_BACK", "RECOVERY_FAILED": "RECOVERY_FAILED"}
TELEMETRY_RANGES = {"speed_kph": (0, 400), "battery_v": (0, 60), "coolant_c": (-60, 200), "rssi_dbm": (-150, 0)}
MAX_EVENTS_PER_BATCH = 256


def _parse_iso(ts: str | None) -> float | None:
    return None if not ts else datetime.fromisoformat(ts).timestamp()


class AuditService:
    def __init__(self, repo: AuditRepository):
        self.repo = repo

    def record(self, actor: str, action: str, target_type: str | None, target_id: str | None,
               outcome: str = "SUCCESS", details: dict | None = None) -> None:
        ip = request.remote_addr if has_request_context() else None
        self.repo.insert(actor, action, target_type, target_id, outcome, details or {}, ip)


class UserService:
    def __init__(self, repo: UserRepository, audit: AuditService, settings: Settings):
        self.repo, self.audit, self.settings = repo, audit, settings

    def create(self, username: str, password: str, role: str) -> dict:
        if role not in ("admin", "engineer", "viewer") or not is_safe_id(username):
            raise validation_error([{"field": "username/role", "message": "invalid"}])
        return self.repo.create(username, passwords.hash_password(password, self.settings.password_iterations), role)

    def get_active(self, uid: str) -> dict | None:
        u = self.repo.get(uid)
        return u if u and u["is_active"] else None

    def login(self, username: str, password: str) -> dict:
        u = self.repo.get_with_hash(username)
        ok = passwords.verify_password(password, u["password_hash"] if u else passwords.DUMMY_HASH)
        if not (u and ok and u["is_active"]):
            self.audit.record(username[:64], "auth.login", "user", None, "DENIED", {})
            raise unauthorized("invalid username or password")
        token = tokens.issue_access_token(self.settings.jwt_secret, u["id"], u["role"], self.settings.access_token_ttl_s)
        self.audit.record(username, "auth.login", "user", u["id"])
        return {"access_token": token, "token_type": "bearer", "expires_in": self.settings.access_token_ttl_s,
                "user": {"id": u["id"], "username": u["username"], "role": u["role"]}}


class VehicleService:
    def __init__(self, repo: VehicleRepository, deployments: DeploymentRepository, events: EventRepository,
                 audit: AuditService, settings: Settings):
        self.repo, self.deployments, self.events, self.audit, self.settings = (
            repo, deployments, events, audit, settings)

    def connectivity(self, last_heartbeat_at: str | None) -> str:
        ts = _parse_iso(last_heartbeat_at)
        if ts is None:
            return "NEVER_CONNECTED"
        return "ONLINE" if time.time() - ts <= self.settings.offline_after_s else "OFFLINE"

    def _present(self, v: dict) -> dict:
        v = dict(v)
        v["connectivity"] = self.connectivity(v["last_heartbeat_at"])
        return v

    def register(self, actor: dict, payload: dict) -> dict:
        data = validate(payload, {
            "vehicle_id": Field(str, check=is_safe_id, message="1-64 chars [A-Za-z0-9._-]"),
            "display_name": Field(str, max_len=100, check=lambda s: s.strip() != ""),
            "model": Field(str, max_len=100, check=lambda s: s.strip() != ""),
            "ecu_id": Field(str, check=is_safe_id),
            "hardware_id": Field(str, check=is_safe_id),
        })
        if self.repo.exists(data["vehicle_id"]):
            raise conflict("vehicle already registered")
        token = tokens.new_device_token()
        self.repo.create(data["vehicle_id"], data["display_name"].strip(), data["model"].strip(),
                         tokens.hash_device_token(token), data["ecu_id"], data["hardware_id"])
        self.audit.record(actor["username"], "vehicle.register", "vehicle", data["vehicle_id"],
                          details={"hardware_id": data["hardware_id"], "ecu_id": data["ecu_id"]})
        out = self.get(data["vehicle_id"])
        out["device_token"] = token  # shown exactly once; only the hash is stored
        return out

    def rotate_token(self, actor: dict, vid: str) -> dict:
        if not self.repo.exists(vid):
            raise not_found("vehicle")
        token = tokens.new_device_token()
        self.repo.set_token_hash(vid, tokens.hash_device_token(token))
        self.audit.record(actor["username"], "vehicle.rotate_token", "vehicle", vid)
        return {"vehicle_id": vid, "device_token": token}

    def get(self, vid: str) -> dict:
        v = self.repo.get(vid)
        if v is None:
            raise not_found("vehicle")
        v = self._present(v)
        v["deployments"] = self.deployments.for_vehicle(vid)
        return v

    def list(self, limit: int, offset: int, search: str | None, connectivity: str | None) -> dict:
        items, total = self.repo.list(limit, offset, search)
        items = [self._present(v) for v in items]
        if connectivity:
            items = [v for v in items if v["connectivity"] == connectivity]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def authenticate_device(self, vid: str, token: str) -> dict | None:
        if not is_safe_id(vid):
            return None
        stored = self.repo.token_hash(vid)
        if stored is None or not tokens.device_token_matches(token, stored):
            return None
        return self.repo.get(vid)


class FirmwareService:
    def __init__(self, repo: FirmwareRepository, blobs: BlobStore, trust: TrustStore, audit: AuditService,
                 settings: Settings):
        self.repo, self.blobs, self.trust, self.audit, self.settings = repo, blobs, trust, audit, settings

    def upload(self, actor: dict, manifest_raw: bytes, image: bytes) -> dict:
        try:
            m = json.loads(manifest_raw)
            validate_manifest_structure(m, self.settings.max_firmware_bytes)
            verify_signature(m, self.trust)
            if len(image) != m["size"] or hashlib.sha256(image).hexdigest() != m["sha256"]:
                raise ManifestError("DIGEST_MISMATCH", "image does not match manifest size/SHA-256")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._reject(actor, "MALFORMED", "manifest is not valid JSON")
        except ManifestError as e:
            self._reject(actor, e.code, str(e), m.get("firmware_id") if isinstance(m, dict) else None)
        if self.repo.conflict(m["firmware_id"], m["hardware_id"], m["version"]):
            raise conflict("firmware id or (hardware_id, version) already exists")
        key = self.blobs.put(image)
        self.repo.insert(m, key, actor["id"])
        self.audit.record(actor["username"], "firmware.upload", "firmware", m["firmware_id"],
                          details={"version": m["version"], "hardware_id": m["hardware_id"], "sha256": m["sha256"],
                                   "key_id": m["key_id"]})
        return self.get(m["firmware_id"])

    def _reject(self, actor: dict, code: str, message: str, fid: str | None = None):
        self.audit.record(actor["username"], "firmware.upload", "firmware", fid, "DENIED",
                          {"reason": code, "message": message})
        raise ApiError(422, "firmware_rejected", message, {"reason": code})

    def get(self, fid: str) -> dict:
        f = self.repo.get(fid)
        if f is None:
            raise not_found("firmware")
        f.pop("blob_key")
        f["manifest"] = json.loads(f.pop("manifest_json"))
        f["simulate_unhealthy"] = bool(f["simulate_unhealthy"])
        f["signature_verified"] = bool(f["signature_verified"])
        return f

    def list(self, limit: int, offset: int) -> dict:
        items, total = self.repo.list(limit, offset)
        for f in items:
            f["simulate_unhealthy"] = bool(f["simulate_unhealthy"])
            f["signature_verified"] = bool(f["signature_verified"])
        return {"items": items, "total": total, "limit": limit, "offset": offset}


class CampaignService:
    def __init__(self, db: Database, repo: CampaignRepository, deployments: DeploymentRepository,
                 vehicles: VehicleRepository, firmware: FirmwareRepository, events: EventRepository,
                 audit: AuditService, settings: Settings):
        self.db, self.repo, self.deployments, self.vehicles, self.firmware, self.events = (
            db, repo, deployments, vehicles, firmware, events)
        self.audit, self.settings = audit, settings

    def compatibility(self, firmware_id: str, vehicle_ids: list[str]) -> dict:
        fw = self.firmware.get(firmware_id)
        if fw is None:
            raise not_found("firmware")
        target, min_cur = semver_tuple(fw["version"]), semver_tuple(fw["min_current_version"])
        results = []
        for vid in vehicle_ids:
            v = self.vehicles.get(vid)
            issues = []
            if v is None:
                issues.append("vehicle not registered")
            else:
                if v["hardware_id"] != fw["hardware_id"]:
                    issues.append(f"hardware {v['hardware_id']} does not match {fw['hardware_id']}")
                if v["firmware_version"]:
                    cur = semver_tuple(v["firmware_version"])
                    if target <= cur:
                        issues.append(f"installed {v['firmware_version']} is not older than {fw['version']}")
                    if cur < min_cur:
                        issues.append(f"requires installed version >= {fw['min_current_version']}")
                if self.deployments.active_for_vehicle(vid):
                    issues.append("vehicle already has an active deployment")
            results.append({"vehicle_id": vid, "compatible": not issues, "issues": issues})
        return {"firmware_id": firmware_id, "target_version": fw["version"],
                "all_compatible": all(r["compatible"] for r in results), "vehicles": results}

    def _validate_targets(self, payload: dict) -> dict:
        return validate(payload, {
            "name": Field(str, max_len=120, check=lambda s: s.strip() != ""),
            "firmware_id": Field(str, check=is_safe_id),
            "vehicle_ids": Field(list, check=lambda vs: 1 <= len(vs) <= 500 and len(set(vs)) == len(vs)
                                 and all(is_safe_id(v) for v in vs), message="1-500 unique vehicle ids"),
        })

    def create(self, actor: dict, payload: dict) -> dict:
        data = self._validate_targets(payload)
        compat = self.compatibility(data["firmware_id"], data["vehicle_ids"])
        if not compat["all_compatible"]:
            raise ApiError(422, "incompatible_targets", "one or more vehicles are not compatible", compat)
        with self.db.transaction() as c:
            cid = self.repo.insert(c, data["name"].strip(), data["firmware_id"], actor["id"])
            for vid in data["vehicle_ids"]:
                self.deployments.insert(c, cid, vid, "AWAITING_APPROVAL")
        self.audit.record(actor["username"], "campaign.create", "campaign", cid,
                          details={"firmware_id": data["firmware_id"], "vehicles": data["vehicle_ids"]})
        return self.get(cid)

    def approve(self, actor: dict, cid: str) -> dict:
        camp = self.repo.get(cid)
        if camp is None:
            raise not_found("campaign")
        if camp["status"] != "PENDING_APPROVAL":
            raise conflict(f"campaign is {camp['status']}")
        if camp["created_by"] == actor["id"] and not self.settings.allow_self_approval:
            self.audit.record(actor["username"], "campaign.approve", "campaign", cid, "DENIED",
                              {"reason": "separation of duties"})
            raise forbidden("campaign must be approved by a different administrator than its creator")
        deps = self.deployments.for_campaign(cid)
        compat = self.compatibility(camp["firmware_id"], [d["vehicle_id"] for d in deps])
        if not compat["all_compatible"]:
            raise ApiError(409, "incompatible_targets", "targets changed since creation", compat)
        expires = int(time.time()) + self.settings.command_ttl_s
        with self.db.transaction() as c:
            for d in deps:
                seq = self.vehicles.allocate_command_seq(c, d["vehicle_id"])
                self.deployments.issue(c, d["id"], seq, expires)
            self.repo.set_status(c, cid, "APPROVED", approved_by=actor["id"])
        self.audit.record(actor["username"], "campaign.approve", "campaign", cid,
                          details={"deployments": len(deps), "expires_at": expires})
        return self.get(cid)

    def cancel(self, actor: dict, cid: str) -> dict:
        camp = self.repo.get(cid)
        if camp is None:
            raise not_found("campaign")
        if camp["status"] == "CANCELLED":
            raise conflict("campaign already cancelled")
        with self.db.transaction() as c:
            for d in self.deployments.for_campaign(cid):
                if d["status"] in ("AWAITING_APPROVAL", "PENDING"):
                    self.deployments.update(c, d["id"], "CANCELLED", None, None, True)
            self.repo.set_status(c, cid, "CANCELLED")
        self.audit.record(actor["username"], "campaign.cancel", "campaign", cid)
        return self.get(cid)

    def get(self, cid: str) -> dict:
        camp = self.repo.get(cid)
        if camp is None:
            raise not_found("campaign")
        deps = self.deployments.for_campaign(cid)
        camp["deployments"] = deps
        camp["progress"] = self._progress(deps)
        return camp

    @staticmethod
    def _progress(deps: list[dict]) -> dict:
        counts: dict[str, int] = {}
        for d in deps:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        done = sum(v for k, v in counts.items() if k in TERMINAL_STATUSES)
        return {"total": len(deps), "finished": done, "by_status": counts}

    def list(self, limit: int, offset: int) -> dict:
        items, total = self.repo.list(limit, offset)
        for camp in items:
            camp["progress"] = self._progress(self.deployments.for_campaign(camp["id"]))
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def deployment(self, did: str) -> dict:
        d = self.deployments.get(did)
        if d is None:
            raise not_found("deployment")
        d["events"] = self.events.for_deployment(did)
        return d


class DeviceService:
    """Vehicle-facing protocol: heartbeat/telemetry, commands, firmware fetch, events."""

    def __init__(self, db: Database, vehicles: VehicleRepository, deployments: DeploymentRepository,
                 firmware: FirmwareRepository, events: EventRepository, blobs: BlobStore,
                 audit: AuditService, settings: Settings):
        self.db, self.vehicles, self.deployments, self.firmware, self.events = (
            db, vehicles, deployments, firmware, events)
        self.blobs, self.audit, self.settings = blobs, audit, settings
        self.metrics = {"heartbeats": 0, "events_accepted": 0, "events_duplicate": 0}

    def _check_identity(self, vehicle: dict, claimed: str) -> None:
        if claimed != vehicle["id"]:
            self.audit.record(f"vehicle:{vehicle['id']}", "device.impersonation_attempt", "vehicle", str(claimed)[:64],
                              "DENIED", {})
            raise forbidden("payload vehicle_id does not match authenticated vehicle")

    def heartbeat(self, vehicle: dict, payload: dict) -> dict:
        data = validate(payload, {
            "vehicle_id": Field(str), "ecu_id": Field(str, check=is_safe_id), "hardware_id": Field(str),
            "firmware_version": Field(str, check=lambda v: _is_semver(v)),
            "active_slot": Field(str, check=lambda s: s in ("A", "B")),
            "update_state": Field(str, check=lambda s: s in ECU_STATES),
            "last_command_seq": Field(int, check=lambda n: n >= 0),
            "telemetry": Field(dict, required=False), "counters": Field(dict, required=False),
        })
        self._check_identity(vehicle, data["vehicle_id"])
        if data["hardware_id"] != vehicle["hardware_id"]:
            raise forbidden("hardware_id does not match registration")
        now = int(time.time())
        was = self.vehicles.get(vehicle["id"])
        prev_ts = _parse_iso(was["last_heartbeat_at"])
        telemetry, rejected = _clean_telemetry(data.get("telemetry") or {})
        with self.db.transaction() as c:
            self.vehicles.record_heartbeat(c, vehicle["id"], data["firmware_version"], data["update_state"],
                                           data["active_slot"], data["last_command_seq"])
            if telemetry:
                self.events.insert_telemetry(c, vehicle["id"], telemetry, data["firmware_version"],
                                             data["update_state"])
            if prev_ts is None or now - prev_ts > self.settings.offline_after_s:
                self.events.insert_diagnostic(c, {"vehicle_id": vehicle["id"], "code": "C0001", "severity": "INFO",
                                                  "description": "vehicle connected" if prev_ts is None
                                                  else f"vehicle reconnected after {int(now - prev_ts)} s offline",
                                                  "timestamp": now}, source="CLOUD")
            if rejected:
                self.events.insert_diagnostic(c, {"vehicle_id": vehicle["id"], "code": "C0002",
                                                  "severity": "WARNING",
                                                  "description": f"telemetry out of range: {', '.join(rejected)}",
                                                  "timestamp": now}, source="CLOUD")
            commands = []
            for d in self.deployments.active_for_vehicle(vehicle["id"]):
                if d["status"] != "PENDING":
                    continue
                if d["expires_at"] < now:
                    self.deployments.update(c, d["id"], "EXPIRED", None, "COMMAND_EXPIRED", True)
                elif d["command_seq"] <= data["last_command_seq"]:
                    self.deployments.update(c, d["id"], "IN_PROGRESS", None, None, False)
                else:
                    commands.append({"seq": d["command_seq"], "type": "install", "vehicle_id": vehicle["id"],
                                     "deployment_id": d["id"], "firmware_id": d["firmware_id"],
                                     "expires_at": d["expires_at"]})
        self.metrics["heartbeats"] += 1
        return {"commands": commands, "server_time": now}

    def _authorized_firmware(self, vehicle: dict, fid: str) -> dict:
        if not is_safe_id(fid):
            raise not_found("firmware")
        allowed = any(d["firmware_id"] == fid for d in self.deployments.active_for_vehicle(vehicle["id"]))
        fw = self.firmware.get(fid)
        if fw is None or not allowed:
            self.audit.record(f"vehicle:{vehicle['id']}", "device.firmware_access", "firmware", fid, "DENIED", {})
            raise not_found("firmware")  # do not reveal existence to unauthorised vehicles
        return fw

    def manifest(self, vehicle: dict, fid: str) -> dict:
        return json.loads(self._authorized_firmware(vehicle, fid)["manifest_json"])

    def image_path(self, vehicle: dict, fid: str):
        return self.blobs.local_path(self._authorized_firmware(vehicle, fid)["blob_key"])

    def ingest_events(self, vehicle: dict, payload: dict) -> dict:
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise validation_error([{"field": "events", "message": "expected list"}])
        evs = payload["events"]
        if len(evs) > MAX_EVENTS_PER_BATCH:
            raise validation_error([{"field": "events", "message": f"at most {MAX_EVENTS_PER_BATCH} per batch"}])
        clean = []
        for i, ev in enumerate(evs):
            if not _valid_event(ev):
                raise validation_error([{"field": f"events[{i}]", "message": "invalid event"}])
            self._check_identity(vehicle, ev.get("vehicle_id"))
            clean.append(ev)
        accepted = dup = 0
        with self.db.transaction() as c:
            for ev in sorted(clean, key=lambda e: e["event_seq"]):
                dep = None
                if ev.get("deployment_id"):
                    dep = self.deployments.get(ev["deployment_id"])
                    if dep is None or dep["vehicle_id"] != vehicle["id"]:
                        dep = None
                        ev["deployment_id"] = None  # never attach events to another vehicle's deployment
                if not self.events.insert_event(c, ev):
                    dup += 1
                    continue
                accepted += 1
                if ev["kind"] == "STATE" and _is_semver(ev.get("firmware_version", "")):
                    self.vehicles.apply_state_event(c, vehicle["id"], ev["event_seq"], ev["firmware_version"],
                                                    ev["to_state"])
                if ev["kind"] == "DTC":
                    self.events.insert_diagnostic(c, ev)
                elif dep is not None:
                    self._apply(c, dep, ev)
        self.metrics["events_accepted"] += accepted
        self.metrics["events_duplicate"] += dup
        return {"accepted": accepted, "duplicates": dup}

    def _apply(self, c, dep: dict, ev: dict) -> None:
        current = self.deployments.get(dep["id"])
        if current["status"] in TERMINAL_STATUSES:
            return  # terminal outcomes never regress (late/out-of-order events)
        if ev["kind"] == "COMMAND_REJECTED":
            self.deployments.update(c, dep["id"], "REJECTED", None, "COMMAND_REJECTED", True)
            return
        to = ev["to_state"]
        if to in TERMINAL_STATE_MAP:
            self.deployments.update(c, dep["id"], TERMINAL_STATE_MAP[to], to, ev.get("error_code"), True)
        elif to == "IDLE":
            self.deployments.update(c, dep["id"], "FAILED", to, ev.get("error_code") or "ABANDONED", True)
        else:
            self.deployments.update(c, dep["id"], "IN_PROGRESS", to, ev.get("error_code"), False)


def _valid_event(ev) -> bool:
    """Explicit validation (not `assert`, which is stripped under python -O)."""
    if not isinstance(ev, dict):
        return False
    seq, kind = ev.get("event_seq"), ev.get("kind")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
        return False
    if kind not in ("STATE", "DTC", "COMMAND_REJECTED"):
        return False
    if isinstance(ev.get("timestamp"), bool) or not isinstance(ev.get("timestamp"), int):
        return False
    if not isinstance(ev.get("deployment_id", ""), str):
        return False
    if kind == "STATE" and not (ev.get("to_state") in ECU_STATES and ev.get("from_state") in ECU_STATES):
        return False
    if kind == "DTC":
        if not (isinstance(ev.get("code"), str) and 0 < len(ev["code"]) <= 16):
            return False
        if ev.get("severity") not in ("INFO", "WARNING", "ERROR", "CRITICAL"):
            return False
        ev["description"] = str(ev.get("description", ""))[:500]
    for k in ("detail", "error_code", "firmware_version"):
        if k in ev:
            ev[k] = str(ev[k])[:500]
    return True


def _is_semver(v: str) -> bool:
    try:
        semver_tuple(v)
        return True
    except ValueError:
        return False


def _clean_telemetry(t: dict) -> tuple[dict, list[str]]:
    out, rejected = {}, []
    for k, (lo, hi) in TELEMETRY_RANGES.items():
        v = t.get(k)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
            rejected.append(k)
        else:
            out[k] = float(v)
    return out, rejected


class FleetService:
    def __init__(self, vehicles: VehicleRepository, vehicle_service: VehicleService,
                 deployments: DeploymentRepository, events: EventRepository):
        self.vehicles, self.vs, self.deployments, self.events = vehicles, vehicle_service, deployments, events

    def summary(self) -> dict:
        vs = self.vehicles.all_for_summary()
        conn: dict[str, int] = {"ONLINE": 0, "OFFLINE": 0, "NEVER_CONNECTED": 0}
        versions: dict[str, int] = {}
        for v in vs:
            conn[self.vs.connectivity(v["last_heartbeat_at"])] += 1
            key = v["firmware_version"] or "unknown"
            versions[key] = versions.get(key, 0) + 1
        by_status = self.deployments.counts_by_status()
        alerts, _ = self.events.diagnostics(None, 50, 0)
        alerts = [a for a in alerts if a["severity"] in ("WARNING", "ERROR", "CRITICAL")][:10]
        return {
            "vehicles_total": len(vs), "connectivity": conn,
            "firmware_distribution": [{"version": k, "count": n} for k, n in sorted(versions.items())],
            "deployments_by_status": by_status,
            "active_deployments": sum(by_status.get(s, 0) for s in ACTIVE_STATUSES),
            "failed_deployments": sum(by_status.get(s, 0) for s in FAILED_STATUSES),
            "recent_alerts": alerts, "recent_deployments": self.deployments.recent(8),
        }


@dataclass
class Services:
    audit: AuditService
    users: UserService
    vehicles: VehicleService
    firmware: FirmwareService
    campaigns: CampaignService
    device: DeviceService
    fleet: FleetService
    events: EventRepository
    audit_repo: AuditRepository

    @staticmethod
    def build(db: Database, settings: Settings, blobs: BlobStore, trust: TrustStore) -> "Services":
        users, vehicles, fw = UserRepository(db), VehicleRepository(db), FirmwareRepository(db)
        camps, deps, evs, aud = CampaignRepository(db), DeploymentRepository(db), EventRepository(db), AuditRepository(db)
        audit = AuditService(aud)
        vsvc = VehicleService(vehicles, deps, evs, audit, settings)
        return Services(
            audit=audit,
            users=UserService(users, audit, settings),
            vehicles=vsvc,
            firmware=FirmwareService(fw, blobs, trust, audit, settings),
            campaigns=CampaignService(db, camps, deps, vehicles, fw, evs, audit, settings),
            device=DeviceService(db, vehicles, deps, fw, evs, blobs, audit, settings),
            fleet=FleetService(vehicles, vsvc, deps, evs),
            events=evs, audit_repo=aud,
        )
