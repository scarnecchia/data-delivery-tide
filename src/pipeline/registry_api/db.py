import hashlib
import sqlite3
from typing import Annotated

from fastapi import Depends


def make_delivery_id(source_path: str) -> str:
    """
    Generate a deterministic delivery ID from a source path.

    Returns the SHA-256 hex digest of the source path.
    """
    return hashlib.sha256(source_path.encode()).hexdigest()


def init_db(db_path_or_conn: str | sqlite3.Connection) -> None:
    """
    Initialize the database schema.

    Accepts either a file path string or an existing sqlite3.Connection.
    If given a string, opens a connection, runs schema, and closes it.
    If given a connection, runs schema on it directly.
    """
    if isinstance(db_path_or_conn, str):
        conn = sqlite3.connect(db_path_or_conn)
        should_close = True
    else:
        conn = db_path_or_conn
        should_close = False

    try:
        cursor = conn.cursor()

        # Create the deliveries table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS deliveries (
                delivery_id          TEXT PRIMARY KEY,
                request_id           TEXT NOT NULL,
                project              TEXT NOT NULL,
                request_type         TEXT NOT NULL,
                workplan_id          TEXT NOT NULL,
                dp_id                TEXT NOT NULL,
                version              TEXT NOT NULL,
                scan_root            TEXT NOT NULL,
                qa_status            TEXT NOT NULL CHECK (qa_status IN ('pending', 'passed')),
                first_seen_at        TEXT NOT NULL,
                qa_passed_at         TEXT,
                parquet_converted_at TEXT,
                file_count           INTEGER,
                total_bytes          INTEGER,
                source_path          TEXT NOT NULL UNIQUE,
                output_path          TEXT,
                fingerprint          TEXT,
                last_updated_at      TEXT
            )
            """
        )

        # Create indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_actionable ON deliveries (qa_status, parquet_converted_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_dp_wp ON deliveries (dp_id, workplan_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_request_id ON deliveries (request_id)"
        )

        # Enable WAL mode only for file-based databases
        if isinstance(db_path_or_conn, str):
            cursor.execute("PRAGMA journal_mode=WAL;")

        conn.commit()
    finally:
        if should_close:
            conn.close()


def get_connection(db_path: str) -> sqlite3.Connection:
    """
    Open a database connection with thread safety and row factory.

    Returns a connection with:
    - check_same_thread=False for FastAPI dependency injection
    - row_factory set to sqlite3.Row for dict-like access
    - WAL mode enabled
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    return conn


def get_db():
    """
    FastAPI dependency injection generator for database connections.

    Yields a database connection that is automatically closed after the request.
    """
    from pipeline.config import load_config

    settings = load_config()
    conn = get_connection(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


DbDep = Annotated[sqlite3.Connection, Depends(get_db)]
