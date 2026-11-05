"""Operational CLI: python -m app.cli {migrate|create-user|serve}."""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from .config import Settings


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    cu = sub.add_parser("create-user")
    cu.add_argument("--username", required=True)
    cu.add_argument("--role", choices=["admin", "engineer", "viewer"], required=True)
    cu.add_argument("--password-env", help="read password from this environment variable instead of a prompt")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    from . import create_app  # noqa: PLC0415
    app = create_app(Settings.from_env())  # create_app runs migrations
    if a.cmd == "migrate":
        print("migrations up to date")
    elif a.cmd == "create-user":
        pw = os.environ.get(a.password_env, "") if a.password_env else getpass.getpass("password: ")
        if not pw:
            sys.exit("empty password")
        svc = app.extensions["services"].users
        if svc.repo.get_with_hash(a.username):
            print(f"user {a.username} already exists")
            return
        u = svc.create(a.username, pw, a.role)
        print(f"created {u['username']} ({u['role']})")
    elif a.cmd == "serve":
        # Development server (threaded). Production: gunicorn 'app:create_app()' behind TLS.
        app.run(host=a.host, port=a.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
