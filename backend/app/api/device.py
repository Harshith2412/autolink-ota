"""Vehicle-facing API (/api/v1/device). Authenticated with per-vehicle device tokens."""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request, send_file

from ..errors import bad_request
from ..security.auth import require_device

bp = Blueprint("device", __name__, url_prefix="/api/v1/device")


def svc():
    return current_app.extensions["services"].device


def body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        raise bad_request("request body must be JSON")
    return data


@bp.post("/heartbeat")
@require_device
def heartbeat():
    return jsonify(svc().heartbeat(g.vehicle, body()))


@bp.get("/firmware/<fid>/manifest")
@require_device
def manifest(fid):
    return jsonify(svc().manifest(g.vehicle, fid))


@bp.get("/firmware/<fid>/image")
@require_device
def image(fid):
    # conditional=True enables HTTP Range (206) so interrupted downloads resume.
    return send_file(svc().image_path(g.vehicle, fid), mimetype="application/octet-stream",
                     conditional=True, etag=True, max_age=0)


@bp.post("/events")
@require_device
def events():
    return jsonify(svc().ingest_events(g.vehicle, body()))
