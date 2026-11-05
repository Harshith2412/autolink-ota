"""Health and metrics endpoints."""
from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify

bp = Blueprint("system", __name__)


@bp.get("/health")
def health():
    db = current_app.extensions["db"]
    try:
        db.scalar("SELECT 1")
        status, code = "ok", 200
    except Exception:  # noqa: BLE001 - report unhealthy rather than crash
        status, code = "degraded", 503
    return jsonify({"status": status, "database": status == "ok"}), code


@bp.get("/metrics")
def metrics():
    m = current_app.extensions["metrics"]
    dev = current_app.extensions["services"].device.metrics
    lines = ["# TYPE autolink_http_requests_total counter"]
    for (method, status), n in sorted(m["requests"].items()):
        lines.append(f'autolink_http_requests_total{{method="{method}",status="{status}"}} {n}')
    for k, v in dev.items():
        lines.append(f"# TYPE autolink_device_{k}_total counter")
        lines.append(f"autolink_device_{k}_total {v}")
    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")
