"""Management REST API (/api/v1) used by the dashboard and operators."""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from ..errors import bad_request, validation_error
from ..security.auth import require_role
from ..validation import Field, is_safe_id, pagination, validate

bp = Blueprint("management", __name__, url_prefix="/api/v1")


def svc():
    return current_app.extensions["services"]


def body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        raise bad_request("request body must be JSON")
    return data


@bp.post("/auth/login")
def login():
    data = validate(body(), {"username": Field(str, max_len=64), "password": Field(str, max_len=256)})
    return jsonify(svc().users.login(data["username"], data["password"]))


@bp.get("/auth/me")
@require_role("viewer")
def me():
    return jsonify({"id": g.user["id"], "username": g.user["username"], "role": g.user["role"]})


# ---------------------------------------------------------------- vehicles
@bp.post("/vehicles")
@require_role("engineer")
def register_vehicle():
    return jsonify(svc().vehicles.register(g.user, body())), 201


@bp.get("/vehicles")
@require_role("viewer")
def list_vehicles():
    limit, offset = pagination(request.args)
    conn = request.args.get("connectivity")
    if conn and conn not in ("ONLINE", "OFFLINE", "NEVER_CONNECTED"):
        raise validation_error([{"field": "connectivity", "message": "invalid filter"}])
    return jsonify(svc().vehicles.list(limit, offset, request.args.get("q", "")[:64] or None, conn))


@bp.get("/vehicles/<vid>")
@require_role("viewer")
def get_vehicle(vid):
    return jsonify(svc().vehicles.get(vid))


@bp.post("/vehicles/<vid>/rotate-token")
@require_role("admin")
def rotate_token(vid):
    return jsonify(svc().vehicles.rotate_token(g.user, vid))


@bp.get("/vehicles/<vid>/telemetry")
@require_role("viewer")
def vehicle_telemetry(vid):
    svc().vehicles.get(vid)
    limit, _ = pagination(request.args)
    return jsonify({"vehicle_id": vid, "items": svc().events.telemetry(vid, limit)})


@bp.get("/vehicles/<vid>/diagnostics")
@require_role("viewer")
def vehicle_diagnostics(vid):
    svc().vehicles.get(vid)
    limit, offset = pagination(request.args)
    items, total = svc().events.diagnostics(vid, limit, offset)
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


@bp.get("/diagnostics")
@require_role("viewer")
def all_diagnostics():
    limit, offset = pagination(request.args)
    sev = request.args.get("severity")
    if sev and sev not in ("INFO", "WARNING", "ERROR", "CRITICAL"):
        raise validation_error([{"field": "severity", "message": "invalid"}])
    vid = request.args.get("vehicle_id")
    if vid and not is_safe_id(vid):
        raise validation_error([{"field": "vehicle_id", "message": "invalid"}])
    items, total = svc().events.diagnostics(vid, limit, offset, sev)
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


# ---------------------------------------------------------------- firmware
@bp.post("/firmware")
@require_role("engineer")
def upload_firmware():
    manifest, image = request.files.get("manifest"), request.files.get("image")
    if manifest is None or image is None:
        raise validation_error([{"field": "manifest/image", "message": "multipart files 'manifest' and 'image' required"}])
    limit = current_app.config["SETTINGS"].max_firmware_bytes
    data = image.stream.read(limit + 1)
    if len(data) > limit:
        raise validation_error([{"field": "image", "message": f"exceeds {limit} bytes"}])
    return jsonify(svc().firmware.upload(g.user, manifest.stream.read(64 * 1024), data)), 201


@bp.get("/firmware")
@require_role("viewer")
def list_firmware():
    limit, offset = pagination(request.args)
    return jsonify(svc().firmware.list(limit, offset))


@bp.get("/firmware/<fid>")
@require_role("viewer")
def get_firmware(fid):
    return jsonify(svc().firmware.get(fid))


# ---------------------------------------------------------------- campaigns
@bp.post("/campaigns/validate")
@require_role("engineer")
def validate_campaign():
    data = validate(body(), {"firmware_id": Field(str, check=is_safe_id),
                             "vehicle_ids": Field(list, check=lambda v: 0 < len(v) <= 500 and all(is_safe_id(x) for x in v))})
    return jsonify(svc().campaigns.compatibility(data["firmware_id"], data["vehicle_ids"]))


@bp.post("/campaigns")
@require_role("engineer")
def create_campaign():
    return jsonify(svc().campaigns.create(g.user, body())), 201


@bp.get("/campaigns")
@require_role("viewer")
def list_campaigns():
    limit, offset = pagination(request.args)
    return jsonify(svc().campaigns.list(limit, offset))


@bp.get("/campaigns/<cid>")
@require_role("viewer")
def get_campaign(cid):
    return jsonify(svc().campaigns.get(cid))


@bp.post("/campaigns/<cid>/approve")
@require_role("admin")
def approve_campaign(cid):
    return jsonify(svc().campaigns.approve(g.user, cid))


@bp.post("/campaigns/<cid>/cancel")
@require_role("admin")
def cancel_campaign(cid):
    return jsonify(svc().campaigns.cancel(g.user, cid))


@bp.get("/deployments/<did>")
@require_role("viewer")
def get_deployment(did):
    return jsonify(svc().campaigns.deployment(did))


# ---------------------------------------------------------------- audit + fleet
@bp.get("/audit-events")
@require_role("admin")
def audit_events():
    limit, offset = pagination(request.args)
    items, total = svc().audit_repo.list(limit, offset, request.args.get("action") or None,
                                         request.args.get("actor") or None)
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


@bp.get("/fleet/summary")
@require_role("viewer")
def fleet_summary():
    return jsonify(svc().fleet.summary())
