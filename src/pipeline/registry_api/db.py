# pattern: Imperative Shell

import hashlib
import sqlite3
from datetime import datetime, timezone
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
                qa_status            TEXT NOT NULL CHECK (qa_status IN ('pending', 'passed', 'failed')),
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

        # Create the tokens table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                token_hash   TEXT PRIMARY KEY,
                username     TEXT NOT NULL UNIQUE,
                role         TEXT NOT NULL CHECK (role IN ('admin', 'write', 'read')),
                created_at   TEXT NOT NULL,
                revoked_at   TEXT
            )
            """
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
    from pipeline.config import settings

    conn = get_connection(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


DbDep = Annotated[sqlite3.Connection, Depends(get_db)]


def _get_iso_now() -> str:
    """Get current timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def upsert_delivery(conn: sqlite3.Connection, data: dict) -> dict:
    """
    Insert or update a delivery record.

    On insert: sets all fields including first_seen_at and last_updated_at to current timestamp.
    On conflict: updates all mutable fields but preserves first_seen_at and conditionally
    updates last_updated_at only when fingerprint changes.

    Args:
        conn: sqlite3.Connection
        data: dict with delivery data. Must contain 'source_path'.

    Returns:
        dict: The full row as a dict (with sqlite3.Row converted to dict).
    """
    delivery_id = make_delivery_id(data["source_path"])
    now = _get_iso_now()

    cursor = conn.cursor()

    # INSERT ... ON CONFLICT statement
    cursor.execute(
        """
        INSERT INTO deliveries (
            delivery_id,
            request_id,
            project,
            request_type,
            workplan_id,
            dp_id,
            version,
            scan_root,
            qa_status,
            first_seen_at,
            qa_passed_at,
            parquet_converted_at,
            file_count,
            total_bytes,
            source_path,
            output_path,
            fingerprint,
            last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(delivery_id) DO UPDATE SET
            request_id = excluded.request_id,
            project = excluded.project,
            request_type = excluded.request_type,
            workplan_id = excluded.workplan_id,
            dp_id = excluded.dp_id,
            version = excluded.version,
            scan_root = excluded.scan_root,
            qa_status = excluded.qa_status,
            first_seen_at = COALESCE(deliveries.first_seen_at, excluded.first_seen_at),
            qa_passed_at = excluded.qa_passed_at,
            parquet_converted_at = excluded.parquet_converted_at,
            file_count = excluded.file_count,
            total_bytes = excluded.total_bytes,
            output_path = excluded.output_path,
            fingerprint = excluded.fingerprint,
            last_updated_at = CASE
                WHEN excluded.fingerprint != deliveries.fingerprint THEN excluded.last_updated_at
                ELSE deliveries.last_updated_at
            END
        """,
        (
            delivery_id,
            data.get("request_id"),
            data.get("project"),
            data.get("request_type"),
            data.get("workplan_id"),
            data.get("dp_id"),
            data.get("version"),
            data.get("scan_root"),
            data.get("qa_status"),
            now,
            data.get("qa_passed_at"),
            data.get("parquet_converted_at"),
            data.get("file_count"),
            data.get("total_bytes"),
            data.get("source_path"),
            data.get("output_path"),
            data.get("fingerprint"),
            now,
        ),
    )

    conn.commit()

    # Fetch and return the row
    cursor.execute("SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,))
    row = cursor.fetchone()

    return dict(row) if row else None


def get_delivery(conn: sqlite3.Connection, delivery_id: str) -> dict | None:
    """
    Retrieve a delivery by ID.

    Args:
        conn: sqlite3.Connection
        delivery_id: The delivery ID to retrieve

    Returns:
        dict: The delivery row as a dict, or None if not found
    """
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def list_deliveries(conn: sqlite3.Connection, filters: dict) -> list[dict]:
    """
    List deliveries with optional filtering.

    Supported filter keys:
    - dp_id, project, request_type, workplan_id, request_id, qa_status, scan_root: exact match with =
    - converted: boolean, if True: parquet_converted_at IS NOT NULL, if False: IS NULL
    - version: if "latest", returns highest version per (dp_id, workplan_id); otherwise exact match

    All filters combine with AND. Empty filters dict returns all rows.

    Args:
        conn: sqlite3.Connection
        filters: dict of filter keys and values

    Returns:
        list: List of delivery dicts
    """
    cursor = conn.cursor()

    # Build WHERE clause dynamically
    where_clauses = []
    params = []

    exact_match_fields = ["dp_id", "project", "request_type", "workplan_id", "request_id", "qa_status", "scan_root"]

    for field in exact_match_fields:
        if field in filters:
            where_clauses.append(f"{field} = ?")
            params.append(filters[field])

    if "converted" in filters:
        if filters["converted"]:
            where_clauses.append("parquet_converted_at IS NOT NULL")
        else:
            where_clauses.append("parquet_converted_at IS NULL")

    if "version" in filters:
        if filters["version"] == "latest":
            # Subquery to get highest version per (dp_id, workplan_id)
            where_clauses.append(
                "version = (SELECT MAX(d2.version) FROM deliveries d2 WHERE d2.dp_id = deliveries.dp_id AND d2.workplan_id = deliveries.workplan_id)"
            )
        else:
            where_clauses.append("version = ?")
            params.append(filters["version"])

    # Build query
    query = "SELECT * FROM deliveries"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_actionable(conn: sqlite3.Connection) -> list[dict]:
    """
    Get actionable deliveries (passed QA but not yet converted to Parquet).

    Returns all deliveries where qa_status='passed' AND parquet_converted_at IS NULL.

    Args:
        conn: sqlite3.Connection

    Returns:
        list: List of actionable delivery dicts
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM deliveries WHERE qa_status = 'passed' AND parquet_converted_at IS NULL"
    )
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def update_delivery(conn: sqlite3.Connection, delivery_id: str, updates: dict) -> dict | None:
    """
    Update a delivery by ID.

    Allowed update keys: parquet_converted_at, output_path, qa_status, qa_passed_at.

    If updates is empty, skips UPDATE and returns the current row via SELECT.

    Args:
        conn: sqlite3.Connection
        delivery_id: The delivery ID to update
        updates: dict of fields to update

    Returns:
        dict: The updated delivery row as a dict, or None if not found
    """
    cursor = conn.cursor()

    # If updates is empty, just query and return the current row
    if not updates:
        cursor.execute("SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    # Allowed update fields
    allowed_fields = {"parquet_converted_at", "output_path", "qa_status", "qa_passed_at"}

    # Filter updates to only allowed fields
    update_dict = {k: v for k, v in updates.items() if k in allowed_fields}

    if not update_dict:
        # No allowed fields, just return current row
        cursor.execute("SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    # Build UPDATE statement
    set_clauses = [f"{field} = ?" for field in update_dict.keys()]
    set_clause = ", ".join(set_clauses)
    params = list(update_dict.values()) + [delivery_id]

    cursor.execute(
        f"UPDATE deliveries SET {set_clause} WHERE delivery_id = ?",
        params,
    )
    conn.commit()

    # Fetch and return updated row
    cursor.execute("SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_token_by_hash(conn: sqlite3.Connection, token_hash: str) -> dict | None:
    """
    Look up a token by its SHA-256 hash.

    Returns the token row as a dict if found, or None if not found.
    Does NOT filter by revoked_at — caller decides how to handle revoked tokens.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tokens WHERE token_hash = ?", (token_hash,))
    row = cursor.fetchone()
    return dict(row) if row else None
