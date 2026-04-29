# pattern: Imperative Shell

import argparse
import hashlib
import secrets
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from pipeline.config import settings
from pipeline.registry_api.db import init_db


def _get_connection() -> sqlite3.Connection:
    """Open a database connection for CLI operations."""
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _hash_token(raw_token: str) -> str:
    """Hash a raw token with SHA-256."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _iso_now() -> str:
    """Get current timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def cmd_add_user(
    args: argparse.Namespace,
    *,
    token_generator: Callable[[int], str] = secrets.token_urlsafe,
) -> int:
    """Create a new token for a user."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()

        # Check if username already has an active token
        cursor.execute(
            "SELECT username, revoked_at FROM tokens WHERE username = ?",
            (args.username,),
        )
        existing = cursor.fetchone()
        if existing is not None and existing["revoked_at"] is None:
            print(f"Error: user '{args.username}' already has an active token", file=sys.stderr)
            return 1

        # If username exists but is revoked, delete the old row to satisfy UNIQUE
        if existing is not None:
            cursor.execute("DELETE FROM tokens WHERE username = ?", (args.username,))

        raw_token = token_generator(32)
        token_hash = _hash_token(raw_token)

        cursor.execute(
            "INSERT INTO tokens (token_hash, username, role, created_at) VALUES (?, ?, ?, ?)",
            (token_hash, args.username, args.role, _iso_now()),
        )
        conn.commit()

        print(raw_token)
        return 0
    finally:
        conn.close()


def cmd_list_users(args: argparse.Namespace) -> int:
    """List all users with their role and status."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT username, role, created_at, revoked_at FROM tokens ORDER BY created_at")
        rows = cursor.fetchall()

        if not rows:
            print("no users found")
            return 0

        # Print header
        print(f"{'USERNAME':<20} {'ROLE':<8} {'CREATED':<28} {'STATUS':<10}")
        print("-" * 70)

        for row in rows:
            status = "revoked" if row["revoked_at"] else "active"
            print(f"{row['username']:<20} {row['role']:<8} {row['created_at']:<28} {status:<10}")

        return 0
    finally:
        conn.close()


def cmd_revoke_user(args: argparse.Namespace) -> int:
    """Revoke a user's token. Idempotent."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()

        # Check if user exists
        cursor.execute("SELECT revoked_at FROM tokens WHERE username = ?", (args.username,))
        row = cursor.fetchone()

        if row is None:
            print(f"Error: user '{args.username}' not found", file=sys.stderr)
            return 1

        # Idempotent: if already revoked, no-op
        if row["revoked_at"] is not None:
            print(f"user '{args.username}' is already revoked")
            return 0

        cursor.execute(
            "UPDATE tokens SET revoked_at = ? WHERE username = ?",
            (_iso_now(), args.username),
        )
        conn.commit()

        print(f"user '{args.username}' revoked")
        return 0
    finally:
        conn.close()


def cmd_rotate_token(
    args: argparse.Namespace,
    *,
    token_generator: Callable[[int], str] = secrets.token_urlsafe,
) -> int:
    """Revoke old token and create a new one for a user."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()

        # Check if user exists
        cursor.execute("SELECT role, revoked_at FROM tokens WHERE username = ?", (args.username,))
        row = cursor.fetchone()

        if row is None:
            print(f"Error: user '{args.username}' not found", file=sys.stderr)
            return 1

        role = row["role"]

        # Delete old row, insert new one (atomic within transaction)
        raw_token = token_generator(32)
        token_hash = _hash_token(raw_token)

        cursor.execute("DELETE FROM tokens WHERE username = ?", (args.username,))
        cursor.execute(
            "INSERT INTO tokens (token_hash, username, role, created_at) VALUES (?, ?, ?, ?)",
            (token_hash, args.username, role, _iso_now()),
        )
        conn.commit()

        print(raw_token)
        return 0
    finally:
        conn.close()


def main() -> None:
    """Entry point for the registry-auth CLI."""
    parser = argparse.ArgumentParser(
        prog="registry-auth",
        description="Manage authentication tokens for the QA Registry API",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # add-user
    add_parser = subparsers.add_parser("add-user", help="Create a new user token")
    add_parser.add_argument("username", help="Username for the new token")
    add_parser.add_argument(
        "--role",
        choices=["admin", "write", "read"],
        default="read",
        help="Role for the new token (default: read)",
    )
    add_parser.set_defaults(func=cmd_add_user)

    # list-users
    list_parser = subparsers.add_parser("list-users", help="List all users")
    list_parser.set_defaults(func=cmd_list_users)

    # revoke-user
    revoke_parser = subparsers.add_parser("revoke-user", help="Revoke a user's token")
    revoke_parser.add_argument("username", help="Username to revoke")
    revoke_parser.set_defaults(func=cmd_revoke_user)

    # rotate-token
    rotate_parser = subparsers.add_parser("rotate-token", help="Rotate a user's token")
    rotate_parser.add_argument("username", help="Username to rotate")
    rotate_parser.set_defaults(func=cmd_rotate_token)

    args = parser.parse_args()
    sys.exit(args.func(args))
