"""AutoLink OTA backend application factory."""
from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import logging_setup
from .config import Settings
from .db import Database
from .errors import ApiError
from .security.manifest import TrustStore
from .services import Services
from .storage.blobs import LocalBlobStore

log = logging.getLogger("autolink.api")


def create_app(settings: Settings | None = None) -> Flask:
    logging_setup.configure()
    settings = settings or Settings.from_env()
    app = Flask(__name__, static_folder=None)
    app.config["SETTINGS"] = settings
    app.config["MAX_CONTENT_LENGTH"] = settings.max_firmware_bytes + 256 * 1024
    app.json.sort_keys = False

    db = Database(settings.database_url)
    db.migrate()
    services = Services.build(db, settings, LocalBlobStore(settings.blob_dir), TrustStore.load(settings.trust_store_path))
    app.extensions.update(db=db, services=services, metrics={"requests": Counter()})

    from .api import device, management, system  # noqa: PLC0415
    app.register_blueprint(management.bp)
    app.register_blueprint(device.bp)
    app.register_blueprint(system.bp)

    @app.before_request
    def _start():
        g.request_id = request.headers.get("X-Request-Id", "")[:64] or uuid.uuid4().hex
        g.t0 = time.perf_counter()

    @app.after_request
    def _finish(resp):
        origin = request.headers.get("Origin")
        if origin and origin in settings.cors_origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Request-Id"] = g.get("request_id", "")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        app.extensions["metrics"]["requests"][(request.method, resp.status_code)] += 1
        log.info("request", extra={"request_id": g.get("request_id"), "method": request.method,
                                   "path": request.path, "status": resp.status_code,
                                   "duration_ms": round((time.perf_counter() - g.get("t0", time.perf_counter())) * 1000, 2)})
        return resp

    @app.teardown_appcontext
    def _close(_exc):
        pass  # connections are per-thread and reused; closed at shutdown

    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return jsonify(e.to_dict()), e.status

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        return jsonify({"error": {"code": e.name.lower().replace(" ", "_"), "message": e.description}}), e.code

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        log.exception("unhandled error", extra={"request_id": g.get("request_id")})
        return jsonify({"error": {"code": "internal_error", "message": "internal server error",
                                  "request_id": g.get("request_id")}}), 500

    if settings.frontend_dist:
        dist = Path(settings.frontend_dist).resolve()

        @app.get("/")
        @app.get("/<path:path>")
        def _spa(path: str = ""):
            if path.startswith("api/"):
                return jsonify({"error": {"code": "not_found", "message": "not found"}}), 404
            candidate = (dist / path).resolve()
            if path and dist in candidate.parents and candidate.is_file():
                return send_from_directory(dist, path)
            return send_from_directory(dist, "index.html")

    return app
