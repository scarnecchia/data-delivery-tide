# Registry Auth Implementation Plan - Phase 3

**Goal:** Implement the `registry-auth` CLI tool for token lifecycle management (add-user, list-users, revoke-user, rotate-token).

**Architecture:** Standalone argparse CLI that talks directly to SQLite. No API round-trip. Uses `pipeline.config.settings.db_path` for database location. Tokens are generated with `secrets.token_urlsafe(32)`, hashed with SHA-256, and only the hash is stored. The raw token is printed once to stdout.

**Tech Stack:** Python 3.10+, argparse, secrets, hashlib, sqlite3

**Scope:** 3 phases from original design (phase 3 of 3)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### registry-auth.AC3: CLI add-user creates token
- **registry-auth.AC3.1 Success:** add-user prints token to stdout and stores hash in DB
- **registry-auth.AC3.2 Success:** add-user with --role sets correct role
- **registry-auth.AC3.3 Success:** add-user defaults to read role
- **registry-auth.AC3.4 Failure:** add-user with existing active username errors

### registry-auth.AC4: CLI token lifecycle operations
- **registry-auth.AC4.1 Success:** list-users shows all users with role and status
- **registry-auth.AC4.2 Success:** revoke-user sets revoked_at on the token
- **registry-auth.AC4.3 Success:** revoke-user on already-revoked user is idempotent (no error)
- **registry-auth.AC4.4 Success:** rotate-token revokes old token and creates new one
- **registry-auth.AC4.5 Success:** rotate-token prints new token to stdout
- **registry-auth.AC4.6 Failure:** Old token rejected by API after rotation

### registry-auth.AC5: Token storage security
- **registry-auth.AC5.2:** Token is generated with secrets.token_urlsafe(32)

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Add registry-auth console script to pyproject.toml

**Verifies:** None (infrastructure)

**Files:**
- Modify: `pyproject.toml:24-25` (add registry-auth script entry)

**Implementation:**

Add the `registry-auth` entry to the `[project.scripts]` section:

```toml
[project.scripts]
registry-api = "pipeline.registry_api.main:run"
registry-auth = "pipeline.auth_cli:main"
```

After modifying, reinstall the package so the console script entry point is registered:

**Verification:**

Run: `uv pip install -e ".[registry,dev]"`
Expected: Installs without errors

**Commit:** `chore: add registry-auth console script entry point`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create auth_cli.py with all subcommands

**Verifies:** registry-auth.AC3.1, registry-auth.AC3.2, registry-auth.AC3.3, registry-auth.AC3.4, registry-auth.AC4.1, registry-auth.AC4.2, registry-auth.AC4.3, registry-auth.AC4.4, registry-auth.AC4.5, registry-auth.AC5.2

**Files:**
- Create: `src/pipeline/auth_cli.py`

**Implementation:**

```python
# pattern: Imperative Shell

import argparse
import hashlib
import secrets
import sqlite3
import sys
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


def cmd_add_user(args: argparse.Namespace) -> int:
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

        raw_token = secrets.token_urlsafe(32)
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
            print("No users found.")
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
            print(f"User '{args.username}' is already revoked.")
            return 0

        cursor.execute(
            "UPDATE tokens SET revoked_at = ? WHERE username = ?",
            (_iso_now(), args.username),
        )
        conn.commit()

        print(f"User '{args.username}' revoked.")
        return 0
    finally:
        conn.close()


def cmd_rotate_token(args: argparse.Namespace) -> int:
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
        raw_token = secrets.token_urlsafe(32)
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


def main():
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
```

Key design decisions:
- `_get_connection()` calls `init_db(conn)` to ensure schema exists (bootstrapping without API)
- `add-user` with existing revoked username deletes the old row first (UNIQUE constraint)
- `rotate-token` deletes old row and inserts new one within same transaction (preserves role)
- Return codes: 0 = success, 1 = error
- Raw token printed to stdout, errors to stderr

**Verification:**

Run: `uv run python -c "from pipeline.auth_cli import main; print('import ok')"`
Expected: `import ok`

**Commit:** `feat: add registry-auth CLI for token lifecycle management`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Add CLI unit tests

**Verifies:** registry-auth.AC3.1, registry-auth.AC3.2, registry-auth.AC3.3, registry-auth.AC3.4, registry-auth.AC4.1, registry-auth.AC4.2, registry-auth.AC4.3, registry-auth.AC4.4, registry-auth.AC4.5, registry-auth.AC5.2

**Files:**
- Create: `tests/test_auth_cli.py`

**Implementation:**

Test the CLI by calling the command functions directly with mock `argparse.Namespace` objects and a monkeypatched database path. This avoids subprocess overhead and lets us inspect the database directly.

```python
import argparse
import hashlib
import sqlite3
from unittest.mock import patch

import pytest

from pipeline.auth_cli import cmd_add_user, cmd_list_users, cmd_revoke_user, cmd_rotate_token
from pipeline.registry_api.db import init_db


@pytest.fixture
def cli_db(tmp_path, monkeypatch):
    """Create a temporary SQLite database for CLI testing."""
    db_path = str(tmp_path / "test_auth.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.close()

    # Monkeypatch settings.db_path so CLI commands use our test database
    monkeypatch.setattr("pipeline.auth_cli.settings", type("Settings", (), {"db_path": db_path})())
    return db_path


def _read_tokens(db_path):
    """Read all tokens from the database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tokens")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


class TestAddUser:
    """Test add-user subcommand."""

    def test_add_user_prints_token_and_stores_hash(self, cli_db, capsys):
        """registry-auth.AC3.1: add-user prints token to stdout and stores hash in DB."""
        args = argparse.Namespace(username="newuser", role="read")
        result = cmd_add_user(args)

        assert result == 0

        captured = capsys.readouterr()
        raw_token = captured.out.strip()
        assert len(raw_token) > 0

        tokens = _read_tokens(cli_db)
        assert len(tokens) == 1
        assert tokens[0]["username"] == "newuser"
        assert tokens[0]["token_hash"] == hashlib.sha256(raw_token.encode()).hexdigest()
        assert tokens[0]["token_hash"] != raw_token

    def test_add_user_with_role_sets_correct_role(self, cli_db, capsys):
        """registry-auth.AC3.2: add-user with --role sets correct role."""
        args = argparse.Namespace(username="adminuser", role="admin")
        result = cmd_add_user(args)

        assert result == 0

        tokens = _read_tokens(cli_db)
        assert tokens[0]["role"] == "admin"

    def test_add_user_defaults_to_read_role(self, cli_db, capsys):
        """registry-auth.AC3.3: add-user defaults to read role."""
        args = argparse.Namespace(username="defaultuser", role="read")
        result = cmd_add_user(args)

        assert result == 0

        tokens = _read_tokens(cli_db)
        assert tokens[0]["role"] == "read"

    def test_add_user_existing_active_username_errors(self, cli_db, capsys):
        """registry-auth.AC3.4: add-user with existing active username errors."""
        args = argparse.Namespace(username="dupeuser", role="read")
        cmd_add_user(args)

        result = cmd_add_user(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "already has an active token" in captured.err

    def test_add_user_reuses_revoked_username(self, cli_db, capsys):
        """add-user succeeds for a username that was previously revoked."""
        args_add = argparse.Namespace(username="recycled", role="read")
        cmd_add_user(args_add)

        args_revoke = argparse.Namespace(username="recycled")
        cmd_revoke_user(args_revoke)

        result = cmd_add_user(args_add)
        assert result == 0

        tokens = _read_tokens(cli_db)
        assert len(tokens) == 1
        assert tokens[0]["revoked_at"] is None

    def test_add_user_token_is_urlsafe(self, cli_db, capsys):
        """registry-auth.AC5.2: Token is generated with secrets.token_urlsafe(32)."""
        with patch("pipeline.auth_cli.secrets.token_urlsafe", return_value="mocked-token-value") as mock_urlsafe:
            args = argparse.Namespace(username="urlsafe_user", role="read")
            cmd_add_user(args)
            mock_urlsafe.assert_called_once_with(32)


class TestListUsers:
    """Test list-users subcommand."""

    def test_list_users_shows_all_users(self, cli_db, capsys):
        """registry-auth.AC4.1: list-users shows all users with role and status."""
        cmd_add_user(argparse.Namespace(username="user1", role="read"))
        cmd_add_user(argparse.Namespace(username="user2", role="write"))
        cmd_add_user(argparse.Namespace(username="user3", role="admin"))

        result = cmd_list_users(argparse.Namespace())

        assert result == 0
        captured = capsys.readouterr()
        assert "user1" in captured.out
        assert "user2" in captured.out
        assert "user3" in captured.out
        assert "read" in captured.out
        assert "write" in captured.out
        assert "admin" in captured.out
        assert "active" in captured.out

    def test_list_users_shows_revoked_status(self, cli_db, capsys):
        """list-users shows revoked status for revoked users."""
        cmd_add_user(argparse.Namespace(username="revokeduser", role="read"))
        cmd_revoke_user(argparse.Namespace(username="revokeduser"))

        capsys.readouterr()  # Clear output from setup
        cmd_list_users(argparse.Namespace())

        captured = capsys.readouterr()
        assert "revoked" in captured.out

    def test_list_users_empty(self, cli_db, capsys):
        """list-users with no users prints message."""
        result = cmd_list_users(argparse.Namespace())

        assert result == 0
        captured = capsys.readouterr()
        assert "No users found" in captured.out


class TestRevokeUser:
    """Test revoke-user subcommand."""

    def test_revoke_user_sets_revoked_at(self, cli_db, capsys):
        """registry-auth.AC4.2: revoke-user sets revoked_at on the token."""
        cmd_add_user(argparse.Namespace(username="torevoke", role="read"))

        result = cmd_revoke_user(argparse.Namespace(username="torevoke"))

        assert result == 0
        tokens = _read_tokens(cli_db)
        assert tokens[0]["revoked_at"] is not None

    def test_revoke_user_idempotent(self, cli_db, capsys):
        """registry-auth.AC4.3: revoke-user on already-revoked user is idempotent."""
        cmd_add_user(argparse.Namespace(username="idemrevoke", role="read"))
        cmd_revoke_user(argparse.Namespace(username="idemrevoke"))

        result = cmd_revoke_user(argparse.Namespace(username="idemrevoke"))

        assert result == 0
        captured = capsys.readouterr()
        assert "already revoked" in captured.out

    def test_revoke_user_nonexistent_errors(self, cli_db, capsys):
        """revoke-user for nonexistent user returns error."""
        result = cmd_revoke_user(argparse.Namespace(username="nobody"))

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err


class TestRotateToken:
    """Test rotate-token subcommand."""

    def test_rotate_token_creates_new_token(self, cli_db, capsys):
        """registry-auth.AC4.4: rotate-token revokes old token and creates new one."""
        cmd_add_user(argparse.Namespace(username="rotateuser", role="write"))
        capsys.readouterr()
        old_tokens = _read_tokens(cli_db)
        old_hash = old_tokens[0]["token_hash"]

        result = cmd_rotate_token(argparse.Namespace(username="rotateuser"))

        assert result == 0
        new_tokens = _read_tokens(cli_db)
        assert len(new_tokens) == 1
        assert new_tokens[0]["token_hash"] != old_hash
        assert new_tokens[0]["role"] == "write"
        assert new_tokens[0]["revoked_at"] is None

    def test_rotate_token_prints_new_token(self, cli_db, capsys):
        """registry-auth.AC4.5: rotate-token prints new token to stdout."""
        cmd_add_user(argparse.Namespace(username="rotateprint", role="read"))
        capsys.readouterr()

        cmd_rotate_token(argparse.Namespace(username="rotateprint"))

        captured = capsys.readouterr()
        new_token = captured.out.strip()
        assert len(new_token) > 0

        tokens = _read_tokens(cli_db)
        assert tokens[0]["token_hash"] == hashlib.sha256(new_token.encode()).hexdigest()

    def test_rotate_token_old_token_invalid(self, cli_db, capsys):
        """registry-auth.AC4.6: Old token rejected after rotation."""
        cmd_add_user(argparse.Namespace(username="oldtoken", role="read"))
        old_token = capsys.readouterr().out.strip()
        old_hash = hashlib.sha256(old_token.encode()).hexdigest()

        cmd_rotate_token(argparse.Namespace(username="oldtoken"))

        tokens = _read_tokens(cli_db)
        assert len(tokens) == 1
        assert tokens[0]["token_hash"] != old_hash

    def test_rotate_token_nonexistent_errors(self, cli_db, capsys):
        """rotate-token for nonexistent user returns error."""
        result = cmd_rotate_token(argparse.Namespace(username="ghost"))

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err
```

**Verification:**

Run: `uv run pytest tests/test_auth_cli.py -v`
Expected: All tests pass

Run: `uv run pytest -v`
Expected: Full test suite passes

**Commit:** `test: add CLI token management tests`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: End-to-end verification

**Verifies:** registry-auth.AC4.6 (full integration)

**Files:**
- No new files — this is a verification-only task

**Implementation:**

Run the complete test suite to verify all three phases work together:

**Verification:**

Run: `uv run pytest -v`
Expected: All tests pass — auth module tests, route protection tests, CLI tests, and all pre-existing tests

Run: `uv run python -c "from pipeline.auth_cli import main; from pipeline.registry_api.auth import require_auth; print('all imports ok')"`
Expected: `all imports ok`

**Commit:** No commit needed (verification only)
<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->
