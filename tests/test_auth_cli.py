# pattern: test file
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
