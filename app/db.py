"""SQLite connection handling and the atomic-transaction helper."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _connect(path):
    # isolation_level=None -> we control transactions explicitly (BEGIN/COMMIT/ROLLBACK).
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def get_db():
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(path):
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
    finally:
        conn.close()


@contextmanager
def atomic(conn):
    """Run the enclosed block as a single all-or-nothing database transaction.

    BEGIN IMMEDIATE takes the write lock up-front, so concurrent writers are
    serialised: balance checks and updates can never interleave.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
