"""Repository layer: the only code that issues SQL. Services depend on these."""
from __future__ import annotations

import json
import uuid
from typing import Any

from ..db import Database, utcnow_iso


def new_id() -> str:
    return uuid.uuid4().hex


def as_dict(row) -> dict | None:
    return None if row is None else dict(row)


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, username: str, password_hash: str, role: str) -> dict:
        uid = new_id()
        with self.db.transaction() as c:
            c.execute("INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                      (uid, username, password_hash, role, utcnow_iso()))
        return self.get(uid)

    def get(self, uid: str) -> dict | None:
        return as_dict(self.db.one("SELECT id, username, role, is_active, created_at FROM users WHERE id=?", (uid,)))

    def get_with_hash(self, username: str) -> dict | None:
        return as_dict(self.db.one("SELECT * FROM users WHERE username=?", (username,)))


class VehicleRepository:
    COLUMNS = ("v.id, v.display_name, v.model, v.last_heartbeat_at, v.firmware_version, v.update_state, "
               "v.last_command_seq, v.created_at, e.ecu_id, e.hardware_id, e.active_slot")

    def __init__(self, db: Database):
        self.db = db

    def create(self, vid: str, display_name: str, model: str, token_hash: str, ecu_id: str, hardware_id: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO vehicles (id, display_name, model, device_token_hash, created_at) VALUES (?,?,?,?,?)",
                      (vid, display_name, model, token_hash, utcnow_iso()))
            c.execute("INSERT INTO ecus (id, vehicle_id, ecu_id, hardware_id) VALUES (?,?,?,?)",
                      (new_id(), vid, ecu_id, hardware_id))

    def exists(self, vid: str) -> bool:
        return self.db.one("SELECT 1 FROM vehicles WHERE id=?", (vid,)) is not None

    def get(self, vid: str) -> dict | None:
        return as_dict(self.db.one(
            f"SELECT {self.COLUMNS} FROM vehicles v JOIN ecus e ON e.vehicle_id=v.id WHERE v.id=?", (vid,)))

    def token_hash(self, vid: str) -> str | None:
        return self.db.scalar("SELECT device_token_hash FROM vehicles WHERE id=?", (vid,))

    def set_token_hash(self, vid: str, token_hash: str) -> None:
        with self.db.transaction() as c:
            c.execute("UPDATE vehicles SET device_token_hash=? WHERE id=?", (token_hash, vid))

    def list(self, limit: int, offset: int, search: str | None) -> tuple[list[dict], int]:
        where, params = "", []
        if search:
            where = "WHERE v.id LIKE ? OR v.display_name LIKE ? OR v.model LIKE ?"
            like = f"%{search}%"
            params = [like, like, like]
        total = self.db.scalar(f"SELECT COUNT(*) FROM vehicles v {where}", tuple(params))
        rows = self.db.query(
            f"SELECT {self.COLUMNS} FROM vehicles v JOIN ecus e ON e.vehicle_id=v.id {where} "
            "ORDER BY v.id LIMIT ? OFFSET ?", tuple(params + [limit, offset]))
        return [dict(r) for r in rows], total

    def all_for_summary(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT id, firmware_version, last_heartbeat_at FROM vehicles")]

    def record_heartbeat(self, c, vid: str, firmware_version: str, update_state: str, active_slot: str,
                         last_command_seq: int) -> None:
        c.execute("UPDATE vehicles SET last_heartbeat_at=?, firmware_version=?, update_state=?, "
                  "last_command_seq=MAX(last_command_seq, ?) WHERE id=?",
                  (utcnow_iso(), firmware_version, update_state, last_command_seq, vid))
        c.execute("UPDATE ecus SET active_slot=? WHERE vehicle_id=?", (active_slot, vid))

    def apply_state_event(self, c, vid: str, event_seq: int, firmware_version: str, update_state: str) -> None:
        """Updates the vehicle's reported firmware/state only for newer events."""
        c.execute("UPDATE vehicles SET firmware_version=?, update_state=?, last_event_seq=? "
                  "WHERE id=? AND last_event_seq < ?",
                  (firmware_version, update_state, event_seq, vid, event_seq))

    def allocate_command_seq(self, c, vid: str) -> int:
        seq = c.execute("SELECT next_command_seq FROM vehicles WHERE id=?", (vid,)).fetchone()[0]
        c.execute("UPDATE vehicles SET next_command_seq=? WHERE id=?", (seq + 1, vid))
        return seq


class FirmwareRepository:
    PUBLIC = ("id, version, hardware_id, sha256, size, security_counter, min_current_version, key_id, "
              "release_notes, simulate_unhealthy, signature_verified, uploaded_by, created_at")

    def __init__(self, db: Database):
        self.db = db

    def insert(self, m: dict, blob_key: str, uploaded_by: str) -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO firmware_packages (id, version, hardware_id, sha256, size, security_counter, "
                "min_current_version, key_id, release_notes, simulate_unhealthy, manifest_json, blob_key, "
                "signature_verified, uploaded_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m["firmware_id"], m["version"], m["hardware_id"], m["sha256"], m["size"], m["security_counter"],
                 m["min_current_version"], m["key_id"], m["release_notes"], int(m["simulate_unhealthy"]),
                 json.dumps(m, sort_keys=True), blob_key, 1, uploaded_by, utcnow_iso()))

    def get(self, fid: str) -> dict | None:
        return as_dict(self.db.one(
            f"SELECT {self.PUBLIC}, manifest_json, blob_key FROM firmware_packages WHERE id=?", (fid,)))

    def conflict(self, fid: str, hw: str, version: str) -> bool:
        return self.db.one("SELECT 1 FROM firmware_packages WHERE id=? OR (hardware_id=? AND version=?)",
                           (fid, hw, version)) is not None

    def list(self, limit: int, offset: int) -> tuple[list[dict], int]:
        total = self.db.scalar("SELECT COUNT(*) FROM firmware_packages")
        rows = self.db.query(
            f"SELECT {self.PUBLIC} FROM firmware_packages ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        return [dict(r) for r in rows], total


class CampaignRepository:
    SELECT = ("SELECT c.*, f.version AS firmware_version, f.hardware_id, u.username AS created_by_name, "
              "a.username AS approved_by_name FROM update_campaigns c "
              "JOIN firmware_packages f ON f.id=c.firmware_id JOIN users u ON u.id=c.created_by "
              "LEFT JOIN users a ON a.id=c.approved_by ")

    def __init__(self, db: Database):
        self.db = db

    def insert(self, c, name: str, firmware_id: str, created_by: str) -> str:
        cid = new_id()
        c.execute("INSERT INTO update_campaigns (id, name, firmware_id, status, created_by, created_at) "
                  "VALUES (?,?,?,?,?,?)", (cid, name, firmware_id, "PENDING_APPROVAL", created_by, utcnow_iso()))
        return cid

    def get(self, cid: str) -> dict | None:
        return as_dict(self.db.one(self.SELECT + "WHERE c.id=?", (cid,)))

    def list(self, limit: int, offset: int) -> tuple[list[dict], int]:
        total = self.db.scalar("SELECT COUNT(*) FROM update_campaigns")
        rows = self.db.query(self.SELECT + "ORDER BY c.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        return [dict(r) for r in rows], total

    def set_status(self, c, cid: str, status: str, approved_by: str | None = None) -> None:
        if approved_by:
            c.execute("UPDATE update_campaigns SET status=?, approved_by=?, approved_at=? WHERE id=?",
                      (status, approved_by, utcnow_iso(), cid))
        else:
            c.execute("UPDATE update_campaigns SET status=? WHERE id=?", (status, cid))


class DeploymentRepository:
    SELECT = ("SELECT d.*, c.name AS campaign_name, c.firmware_id, f.version AS target_version "
              "FROM deployments d JOIN update_campaigns c ON c.id=d.campaign_id "
              "JOIN firmware_packages f ON f.id=c.firmware_id ")

    def __init__(self, db: Database):
        self.db = db

    def insert(self, c, campaign_id: str, vehicle_id: str, status: str) -> str:
        did = new_id()
        c.execute("INSERT INTO deployments (id, campaign_id, vehicle_id, status, created_at) VALUES (?,?,?,?,?)",
                  (did, campaign_id, vehicle_id, status, utcnow_iso()))
        return did

    def get(self, did: str) -> dict | None:
        return as_dict(self.db.one(self.SELECT + "WHERE d.id=?", (did,)))

    def for_campaign(self, cid: str) -> list[dict]:
        return [dict(r) for r in self.db.query(self.SELECT + "WHERE d.campaign_id=? ORDER BY d.vehicle_id", (cid,))]

    def for_vehicle(self, vid: str, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.db.query(
            self.SELECT + "WHERE d.vehicle_id=? ORDER BY d.created_at DESC LIMIT ?", (vid, limit))]

    def active_for_vehicle(self, vid: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            self.SELECT + "WHERE d.vehicle_id=? AND d.status IN ('PENDING','IN_PROGRESS')", (vid,))]

    def recent(self, limit: int) -> list[dict]:
        return [dict(r) for r in self.db.query(self.SELECT + "ORDER BY d.created_at DESC LIMIT ?", (limit,))]

    def issue(self, c, did: str, seq: int, expires_at: int) -> None:
        c.execute("UPDATE deployments SET status='PENDING', command_seq=?, expires_at=? WHERE id=?",
                  (seq, expires_at, did))

    def update(self, c, did: str, status: str, last_state: str | None, error_code: str | None,
               finished: bool) -> None:
        c.execute("UPDATE deployments SET status=?, last_state=COALESCE(?, last_state), "
                  "error_code=COALESCE(?, error_code), "
                  "finished_at=CASE WHEN ?=1 THEN ? ELSE finished_at END WHERE id=?",
                  (status, last_state, error_code or None, 1 if finished else 0, utcnow_iso(), did))

    def counts_by_status(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.db.query("SELECT status, COUNT(*) FROM deployments GROUP BY status")}


class EventRepository:
    def __init__(self, db: Database):
        self.db = db

    def insert_event(self, c, ev: dict) -> bool:
        cur = c.execute(
            "INSERT INTO deployment_events (id, deployment_id, vehicle_id, event_seq, kind, from_state, to_state, "
            "detail, error_code, firmware_version, device_ts, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (vehicle_id, event_seq) DO NOTHING",
            (new_id(), ev.get("deployment_id") or None, ev["vehicle_id"], ev["event_seq"], ev["kind"],
             ev.get("from_state"), ev.get("to_state"), ev.get("detail"), ev.get("error_code") or None,
             ev.get("firmware_version"), ev["timestamp"], utcnow_iso()))
        return cur.rowcount == 1

    def insert_diagnostic(self, c, ev: dict, source: str = "DEVICE") -> None:
        c.execute(
            "INSERT INTO diagnostic_events (id, vehicle_id, deployment_id, event_seq, source, code, severity, "
            "description, device_ts, received_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (vehicle_id, event_seq) DO NOTHING",
            (new_id(), ev["vehicle_id"], ev.get("deployment_id") or None, ev.get("event_seq"), source, ev["code"],
             ev["severity"], ev["description"], ev["timestamp"], utcnow_iso()))

    def for_deployment(self, did: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM deployment_events WHERE deployment_id=? ORDER BY event_seq", (did,))]

    def diagnostics(self, vid: str | None, limit: int, offset: int,
                    severity: str | None = None) -> tuple[list[dict], int]:
        clauses, params = [], []
        if vid:
            clauses.append("vehicle_id=?")
            params.append(vid)
        if severity:
            clauses.append("severity=?")
            params.append(severity)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = self.db.scalar(f"SELECT COUNT(*) FROM diagnostic_events {where}", tuple(params))
        rows = self.db.query(f"SELECT * FROM diagnostic_events {where} ORDER BY received_at DESC, event_seq DESC "
                             "LIMIT ? OFFSET ?", tuple(params + [limit, offset]))
        return [dict(r) for r in rows], total

    def insert_telemetry(self, c, vid: str, t: dict, fw: str, state: str) -> None:
        c.execute("INSERT INTO telemetry_records (id, vehicle_id, received_at, speed_kph, battery_v, coolant_c, "
                  "rssi_dbm, firmware_version, update_state) VALUES (?,?,?,?,?,?,?,?,?)",
                  (new_id(), vid, utcnow_iso(), t.get("speed_kph"), t.get("battery_v"), t.get("coolant_c"),
                   t.get("rssi_dbm"), fw, state))

    def telemetry(self, vid: str, limit: int) -> list[dict]:
        rows = self.db.query("SELECT received_at, speed_kph, battery_v, coolant_c, rssi_dbm, firmware_version, "
                             "update_state FROM telemetry_records WHERE vehicle_id=? "
                             "ORDER BY received_at DESC LIMIT ?", (vid, limit))
        return [dict(r) for r in reversed(rows)]


class AuditRepository:
    def __init__(self, db: Database):
        self.db = db

    def insert(self, actor: str, action: str, target_type: str | None, target_id: str | None, outcome: str,
               details: dict[str, Any], source_ip: str | None) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO audit_events (id, ts, actor, action, target_type, target_id, outcome, details, "
                      "source_ip) VALUES (?,?,?,?,?,?,?,?,?)",
                      (new_id(), utcnow_iso(), actor, action, target_type, target_id, outcome,
                       json.dumps(details, sort_keys=True), source_ip))

    def list(self, limit: int, offset: int, action: str | None, actor: str | None) -> tuple[list[dict], int]:
        clauses, params = [], []
        if action:
            clauses.append("action LIKE ?")
            params.append(f"{action}%")
        if actor:
            clauses.append("actor=?")
            params.append(actor)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = self.db.scalar(f"SELECT COUNT(*) FROM audit_events {where}", tuple(params))
        rows = self.db.query(f"SELECT * FROM audit_events {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
                             tuple(params + [limit, offset]))
        out = []
        for r in rows:
            d = dict(r)
            d["details"] = json.loads(d["details"])
            out.append(d)
        return out, total
