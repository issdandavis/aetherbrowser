"""
Tests for the AetherBrowser Native Messaging Host
===================================================

Tests the Chrome Native Messaging protocol (length-prefixed JSON on stdio)
and the command dispatch logic. Does NOT test actual server start/stop
(that would require the full uvicorn stack).
"""

import json
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.extension.native_messaging.host import (
    read_message,
    send_message,
    handle_message,
    COMMANDS,
    PID_FILE,
)


# ── Protocol tests ──────────────────────────────────────────────────


class TestNativeMessagingProtocol:
    """Test the length-prefixed JSON wire format."""

    def test_encode_message(self, tmp_path):
        """send_message writes 4-byte LE length + JSON."""
        import io

        buf = io.BytesIO()
        msg = {"status": "pong", "pid": 42}
        encoded = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        expected = struct.pack("<I", len(encoded)) + encoded

        with patch("sys.stdout", new=MagicMock(buffer=buf)):
            send_message(msg)

        assert buf.getvalue() == expected

    def test_decode_message(self):
        """read_message parses 4-byte LE length + JSON from stdin."""
        import io

        msg = {"command": "ping"}
        encoded = json.dumps(msg).encode("utf-8")
        raw = struct.pack("<I", len(encoded)) + encoded

        with patch("sys.stdin", new=MagicMock(buffer=io.BytesIO(raw))):
            result = read_message()

        assert result == msg

    def test_decode_empty_stdin(self):
        """read_message returns None on empty stdin."""
        import io

        with patch("sys.stdin", new=MagicMock(buffer=io.BytesIO(b""))):
            result = read_message()

        assert result is None

    def test_decode_truncated_length(self):
        """read_message returns None if length header is incomplete."""
        import io

        with patch("sys.stdin", new=MagicMock(buffer=io.BytesIO(b"\x01\x00"))):
            result = read_message()

        assert result is None

    def test_decode_oversized_message(self):
        """read_message rejects messages over 1MB."""
        import io

        # Claim the payload is 2MB
        raw = struct.pack("<I", 2_097_152) + b"x" * 100
        with patch("sys.stdin", new=MagicMock(buffer=io.BytesIO(raw))):
            result = read_message()

        assert result is None

    def test_roundtrip(self):
        """Encode then decode produces the original message."""
        import io

        original = {"command": "status", "port": 8002}
        encoded = json.dumps(original).encode("utf-8")
        wire = struct.pack("<I", len(encoded)) + encoded

        with patch("sys.stdin", new=MagicMock(buffer=io.BytesIO(wire))):
            decoded = read_message()

        assert decoded == original


# ── Command dispatch tests ───────────────────────────────────────────


class TestCommandDispatch:
    """Test the allow-listed command routing."""

    def test_ping(self):
        result = handle_message({"command": "ping"})
        assert result["status"] == "pong"
        assert "pid" in result

    def test_unknown_command(self):
        result = handle_message({"command": "rm_rf_slash"})
        assert result["status"] == "error"
        assert "Unknown command" in result["error"]
        assert "allowed" in result

    def test_empty_command(self):
        result = handle_message({})
        assert result["status"] == "error"

    def test_allowed_commands_list(self):
        """Only safe commands are in the allow-list."""
        assert set(COMMANDS.keys()) == {"start", "stop", "status", "ping"}

    def test_status_when_not_running(self):
        """status returns stopped when no PID file exists."""
        with patch(
            "src.extension.native_messaging.host._read_pid", return_value=None
        ):
            result = handle_message({"command": "status"})
        assert result["status"] == "stopped"
        assert result["pid"] is None

    def test_status_when_running(self):
        """status returns running with PID when server is up."""
        with patch(
            "src.extension.native_messaging.host._read_pid", return_value=9999
        ):
            result = handle_message({"command": "status"})
        assert result["status"] == "running"
        assert result["pid"] == 9999

    def test_start_when_already_running(self):
        """start returns already_running if PID file is valid."""
        with patch(
            "src.extension.native_messaging.host._read_pid", return_value=1234
        ):
            result = handle_message({"command": "start"})
        assert result["status"] == "already_running"
        assert result["pid"] == 1234

    def test_stop_when_not_running(self):
        """stop returns not_running if no PID file."""
        with patch(
            "src.extension.native_messaging.host._read_pid", return_value=None
        ):
            result = handle_message({"command": "stop"})
        assert result["status"] == "not_running"

    def test_custom_port(self):
        """start and status accept custom port."""
        with patch(
            "src.extension.native_messaging.host._read_pid", return_value=None
        ), patch(
            "subprocess.Popen"
        ) as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 5555
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            result = handle_message({"command": "start", "port": 9999})

        assert result["port"] == 9999


# ── Security tests ───────────────────────────────────────────────────


class TestSecurity:
    """Ensure the host can't be abused."""

    def test_no_arbitrary_commands(self):
        """Cannot execute arbitrary shell commands."""
        result = handle_message({"command": "exec", "payload": "rm -rf /"})
        assert result["status"] == "error"

    def test_no_code_injection_in_command(self):
        """Command field is matched exactly, no eval/exec."""
        result = handle_message({"command": "ping; rm -rf /"})
        assert result["status"] == "error"

    def test_handler_exception_caught(self):
        """If a handler throws, it returns error, doesn't crash."""
        with patch.dict(
            COMMANDS,
            {"start": lambda _: (_ for _ in ()).throw(RuntimeError("boom"))},
        ):
            result = handle_message({"command": "start"})
        assert result["status"] == "error"
        assert "boom" in result["error"]


# ── Install script tests ────────────────────────────────────────────


class TestInstallScript:
    """Test the install.py helper."""

    def test_install_script_importable(self):
        """install.py can be imported without side effects."""
        from src.extension.native_messaging import install

        assert hasattr(install, "HOST_NAME")
        assert install.HOST_NAME == "com.scbe.aetherbrowser"

    def test_manifest_structure(self):
        """Generated manifest has required Chrome NM fields."""
        from src.extension.native_messaging.install import _build_manifest

        manifest = _build_manifest(["chrome-extension://abc123/"])
        assert manifest["name"] == "com.scbe.aetherbrowser"
        assert manifest["type"] == "stdio"
        assert "path" in manifest
        assert manifest["allowed_origins"] == ["chrome-extension://abc123/"]

    def test_registry_key_chrome(self):
        from src.extension.native_messaging.install import _registry_key

        key = _registry_key("chrome")
        assert "Google" in key
        assert "com.scbe.aetherbrowser" in key

    def test_registry_key_edge(self):
        from src.extension.native_messaging.install import _registry_key

        key = _registry_key("edge")
        assert "Microsoft" in key
        assert "com.scbe.aetherbrowser" in key
