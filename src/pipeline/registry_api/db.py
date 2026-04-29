# pattern: Imperative Shell

import hashlib
import json
import sqlite3
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends


def make_delivery_id(source_path: str) -> str:
    """
    Generate a deterministic delivery ID from a source path.

    Returns the SHA-256 hex digest of the source path.
    """
    return hashlib.sha256(source_path.encode()).hexdigest()


def _migrate_events_check_constraint(conn: sqlite3.Connection) -> None:
    """
    Migrate events table CHECK constraint to include conversion event types.

    This is an idempotent migration that detects old schema and recreates
    the table with the extended constraint. Uses a substring check to detect
    if migration has already been applied.

    Args:
        conn: sqlite3.Connection to migrate
    """
    cursor = conn.cursor()

    # Check if events table exists
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
    )
    row = cursor.fetchone()
    if row is None:
        # Fresh DB with no events table yet, migration not needed
        return

    current_sql = row[0]

    # Check if migration already applied (simple substring check for 'conversion.completed')
    if "conversion.completed" in current_sql:
        # Migration already applied
        return

    # Migration needed: recreate table with extended CHECK constraint
    # Use implicit transaction management (autocommit=False is the default)
    try:
        cursor.execute(
            """
            CREATE TABLE events_new (
                seq         INTEGER PRIMARY KEY,
                event_type  TEXT NOT NULL CHECK (event_type IN ('delivery.created', 'delivery.status_changed', 'conversion.completed', 'conversion.failed')),
                delivery_id TEXT NOT NULL,
                payload     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            "INSERT INTO events_new (seq, event_type, delivery_id, payload, created_at) SELECT seq, event_type, delivery_id, payload, created_at FROM events"
        )
        cursor.execute("DROP TABLE events")
        cursor.execute("ALTER TABLE events_new RENAME TO events")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
                lexicon_id           TEXT NOT NULL,
                status               TEXT NOT NULL,
                metadata             TEXT DEFAULT '{}',
                first_seen_at        TEXT NOT NULL,
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

        # Create the events table with all four allowed event types in CHECK constraint
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq         INTEGER PRIMARY KEY,
                event_type  TEXT NOT NULL CHECK (event_type IN ('delivery.created', 'delivery.status_changed', 'conversion.completed', 'conversion.failed')),
                delivery_id TEXT NOT NULL,
                payload     TEXT NOT NULL,
                username    TEXT,
                created_at  TEXT NOT NULL
            )
            """
        )

        # Run migration to update old schemas
        _migrate_events_check_constraint(conn)

        # Create indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_actionable ON deliveries (lexicon_id, status, parquet_converted_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_dp_wp ON deliveries (dp_id, workplan_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_request_id ON deliveries (request_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_lexicon ON deliveries (lexicon_id)"
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


def get_db() -> Generator[sqlite3.Connection, None, None]:
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


def _deserialize_metadata(row_dict: dict) -> dict:
    """
    Deserialize metadata JSON field in a delivery row.

    Converts the metadata field from JSON string to dict.
    Modifies the dict in-place.
    """
    if "metadata" in row_dict and isinstance(row_dict["metadata"], str):
        try:
            row_dict["metadata"] = json.loads(row_dict["metadata"])
        except (json.JSONDecodeError, TypeError):
            row_dict["metadata"] = {}
    return row_dict


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

    # Serialize metadata to JSON if it's a dict
    metadata = data.get("metadata")
    if metadata is not None and isinstance(metadata, dict):
        metadata = json.dumps(metadata)
    elif metadata is None:
        metadata = "{}"

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
            lexicon_id,
            status,
            metadata,
            first_seen_at,
            parquet_converted_at,
            file_count,
            total_bytes,
            source_path,
            output_path,
            fingerprint,
            last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(delivery_id) DO UPDATE SET
            request_id = excluded.request_id,
            project = excluded.project,
            request_type = excluded.request_type,
            workplan_id = excluded.workplan_id,
            dp_id = excluded.dp_id,
            version = excluded.version,
            scan_root = excluded.scan_root,
            lexicon_id = excluded.lexicon_id,
            status = excluded.status,
            metadata = excluded.metadata,
            first_seen_at = COALESCE(deliveries.first_seen_at, excluded.first_seen_at),
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
            data.get("lexicon_id"),
            data.get("status"),
            metadata,
            now,
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

    if row:
        row_dict = dict(row)
        return _deserialize_metadata(row_dict)
    # Unreachable: the INSERT above guarantees the row exists.
    # Annotated as dict per design (#19 AC1.3); this line is defensive only.
    return None  # type: ignore[return-value]


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
    if row:
        row_dict = dict(row)
        return _deserialize_metadata(row_dict)
    return None


def list_deliveries(conn: sqlite3.Connection, filters: dict) -> tuple[list[dict], int]:
    """
    List deliveries with optional filtering and pagination.

    Supported filter keys:
    - dp_id, project, request_type, workplan_id, request_id, status, lexicon_id, scan_root: exact match with =
    - converted: boolean, if True: parquet_converted_at IS NOT NULL, if False: IS NULL
    - version: if "latest", returns highest version per (dp_id, workplan_id); otherwise exact match
    - limit: max rows to return (default 100)
    - offset: number of rows to skip (default 0)

    All filters combine with AND. Empty filters dict returns all rows (paginated).

    Args:
        conn: sqlite3.Connection
        filters: dict of filter keys and values

    Returns:
        tuple: (list of delivery dicts, total count matching filters)
    """
    cursor = conn.cursor()

    # Build WHERE clause dynamically
    where_clauses = []
    params = []

    exact_match_fields = ["dp_id", "project", "request_type", "workplan_id", "request_id", "status", "lexicon_id", "scan_root"]

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

    # Build WHERE string
    where_str = ""
    if where_clauses:
        where_str = " WHERE " + " AND ".join(where_clauses)

    # Get total count
    count_query = f"SELECT COUNT(*) FROM deliveries{where_str}"
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]

    # Get paginated results
    limit = filters.get("limit", 100)
    offset = filters.get("offset", 0)

    query = f"SELECT * FROM deliveries{where_str} LIMIT ? OFFSET ?"
    cursor.execute(query, params + [limit, offset])
    rows = cursor.fetchall()
    return [_deserialize_metadata(dict(row)) for row in rows], total


def get_actionable(conn: sqlite3.Connection, lexicon_actionable: dict[str, list[str]]) -> list[dict]:
    """
    Get actionable deliveries matching per-lexicon actionable statuses.

    Accepts a mapping of lexicon_id → list of actionable statuses. Returns all deliveries
    where (lexicon_id matches AND status in that lexicon's actionable_statuses)
    AND parquet_converted_at IS NULL.

    Args:
        conn: sqlite3.Connection
        lexicon_actionable: dict mapping lexicon_id to list of actionable status values

    Returns:
        list: List of actionable delivery dicts
    """
    cursor = conn.cursor()

    if not lexicon_actionable:
        return []

    conditions = []
    params = []
    for lex_id, statuses in lexicon_actionable.items():
        placeholders = ", ".join("?" for _ in statuses)
        conditions.append(f"(lexicon_id = ? AND status IN ({placeholders}))")
        params.append(lex_id)
        params.extend(statuses)

    where = " OR ".join(conditions)
    cursor.execute(
        f"SELECT * FROM deliveries WHERE ({where}) AND parquet_converted_at IS NULL",
        params,
    )

    rows = cursor.fetchall()
    return [_deserialize_metadata(dict(row)) for row in rows]


def update_delivery(conn: sqlite3.Connection, delivery_id: str, updates: dict) -> dict | None:
    """
    Update a delivery by ID.

    Allowed update keys: parquet_converted_at, output_path, status, metadata.

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
        if row:
            return _deserialize_metadata(dict(row))
        return None

    # Allowed update fields
    allowed_fields = {"parquet_converted_at", "output_path", "status", "metadata"}

    # Filter updates to only allowed fields
    update_dict = {k: v for k, v in updates.items() if k in allowed_fields}

    if not update_dict:
        # No allowed fields, just return current row
        cursor.execute("SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,))
        row = cursor.fetchone()
        if row:
            return _deserialize_metadata(dict(row))
        return None

    # Serialize metadata if present
    if "metadata" in update_dict:
        metadata = update_dict["metadata"]
        if isinstance(metadata, dict):
            update_dict["metadata"] = json.dumps(metadata)

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
    if row:
        return _deserialize_metadata(dict(row))
    return None


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


def insert_event(
    conn: sqlite3.Connection,
    event_type: str,
    delivery_id: str,
    payload: dict,
    username: str | None = None,
) -> dict:
    """
    Insert an event record and return it with the assigned sequence number.

    Args:
        conn: sqlite3.Connection
        event_type: One of 'delivery.created', 'delivery.status_changed',
                    'conversion.completed', or 'conversion.failed'
        delivery_id: The delivery ID this event relates to
        payload: Event payload (shape varies by event_type):
            - 'delivery.created' / 'delivery.status_changed': full delivery record
              (DeliveryResponse.model_dump() output)
            - 'conversion.completed': converter-computed dict with row_count,
              bytes_written, output_path, etc.
            - 'conversion.failed': converter-computed dict with error_class,
              error_message, etc.
        username: The authenticated user who triggered this event (optional)

    Returns:
        dict: The inserted event row as a dict, including the auto-assigned seq.
    """
    now = _get_iso_now()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO events (event_type, delivery_id, payload, username, created_at) VALUES (?, ?, ?, ?, ?)",
        (event_type, delivery_id, json.dumps(payload), username, now),
    )
    conn.commit()

    seq = cursor.lastrowid
    return {
        "seq": seq,
        "event_type": event_type,
        "delivery_id": delivery_id,
        "payload": payload,
        "username": username,
        "created_at": now,
    }


def get_events_after(
    conn: sqlite3.Connection,
    after_seq: int,
    limit: int = 100,
) -> list[dict]:
    """
    Retrieve events with seq greater than after_seq, ordered by seq ascending.

    Args:
        conn: sqlite3.Connection
        after_seq: Return events with seq strictly greater than this value
        limit: Maximum number of events to return (default 100, max 1000)

    Returns:
        list[dict]: List of event dicts with payload deserialised from JSON.
    """
    capped_limit = min(limit, 1000)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?",
        (after_seq, capped_limit),
    )
    rows = cursor.fetchall()

    result = []
    for row in rows:
        event = dict(row)
        event["payload"] = json.loads(event["payload"])
        result.append(event)
    return result


def delivery_exists(conn: sqlite3.Connection, delivery_id: str) -> bool:
    """
    Check if a delivery exists by ID.

    Args:
        conn: sqlite3.Connection
        delivery_id: The delivery ID to check

    Returns:
        bool: True if the delivery exists, False otherwise.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM deliveries WHERE delivery_id = ? LIMIT 1", (delivery_id,))
    return cursor.fetchone() is not None
