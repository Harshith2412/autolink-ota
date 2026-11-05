"""Database access: connection management and the SQL migration runner.

SQLite (stdlib) is the verified backend. A DB-API layer keeps SQL in the
repositories portable; see docs/deployment/postgresql.md for the PostgreSQL
status (not verified in the build environment).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Database:
    def __init__(self, url: str):
        if not url.startswith("sqlite:///"):
            raise ValueError("only sqlite:/// URLs are supported in this build")
        self.path = url[len("sqlite:///"):]
        self._local = threading.local()
        # Serialises writes inside one process; SQLite also locks across processes.
        self.write_lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = self._connect()
        return c

    def close_thread_connection(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.write_lock:
            c = self.conn
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | dict = ()) -> Any:
        row = self.one(sql, params)
        return None if row is None else row[0]

    def migrate(self) -> list[str]:
        """Applies pending migrations in filename order; each runs in one transaction."""
        c = self.conn
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        applied = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
        done = []
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if f.stem in applied:
                continue
            with self.write_lock:
                c.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in _split_sql(f.read_text()):
                        c.execute(stmt)
                    c.execute("INSERT INTO schema_migrations VALUES (?, ?)", (f.stem, utcnow_iso()))
                except BaseException:
                    c.execute("ROLLBACK")
                    raise
                c.execute("COMMIT")
            done.append(f.stem)
        return done


def _split_sql(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
