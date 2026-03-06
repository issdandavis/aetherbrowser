#!/usr/bin/env python3
"""
AetherBrowser Native Messaging Host
====================================

Chrome Native Messaging protocol: messages are length-prefixed JSON on stdin/stdout.

  [4-byte LE length][JSON payload]

This host receives commands from the Chrome extension and executes them
on the local OS -- primarily starting/stopping the AetherBrowser backend.

Security:
  - Only accepts messages from the registered extension ID
  - Commands are allow-listed (no arbitrary shell execution)
  - Server process is tracked by PID file to prevent duplicates
  - All output is structured JSON (no raw shell output leaks)
"""

from __future__ import annotations

import json
import os
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # src/extension/native_messaging -> repo root
PID_FILE = PROJECT_ROOT / "artifacts" / "aetherbrowser.pid"
LOG_FILE = PROJECT_ROOT / "artifacts" / "aetherbrowser.log"
DEFAULT_PORT = 8002
PYTHON = sys.executable  # use the same Python that runs this host

# ---------------------------------------------------------------------------
# Chrome Native Messaging I/O
# ---------------------------------------------------------------------------

def read_message() -> dict | None:
    """Read a single native-messaging packet from stdin."""
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) < 4:
        return None
    length = struct.unpack("<I", raw_length)[0]
    if length > 1_048_576:  # 1 MB sanity cap
        return None
    raw = sys.stdin.buffer.read(length)
    if len(raw) < length:
        return None
    return json.loads(raw.decode("utf-8"))


def send_message(msg: dict) -> None:
    """Write a single native-messaging packet to stdout."""
    encoded = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------

def _read_pid() -> int | None:
    """Read the PID from the pid file, return None if stale or missing."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        # Check if process is still alive (signal 0 = existence check)
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return None


def _write_pid(pid: int) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def start_server(port: int = DEFAULT_PORT) -> dict:
    """Start the AetherBrowser FastAPI backend if not already running."""
    existing = _read_pid()
    if existing:
        return {
            "status": "already_running",
            "pid": existing,
            "port": port,
        }

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOG_FILE, "a", encoding="utf-8")

    # Launch the backend as a detached subprocess
    cmd = [
        PYTHON, "-m", "uvicorn",
        "src.aetherbrowser.serve:app",
        "--host", "127.0.0.1",
        "--port", str(port),
        "--log-level", "info",
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # detach from this process
    )

    _write_pid(proc.pid)

    # Brief wait to confirm it didn't crash immediately
    time.sleep(1.0)
    poll = proc.poll()
    if poll is not None:
        PID_FILE.unlink(missing_ok=True)
        # Read last few lines of log for error context
        error_tail = ""
        try:
            lines = LOG_FILE.read_text().splitlines()
            error_tail = "\n".join(lines[-10:])
        except Exception:
            pass
        return {
            "status": "failed",
            "exit_code": poll,
            "error": error_tail,
        }

    return {
        "status": "started",
        "pid": proc.pid,
        "port": port,
    }


def stop_server() -> dict:
    """Stop the AetherBrowser backend if running."""
    pid = _read_pid()
    if not pid:
        return {"status": "not_running"}

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
            )
        else:
            os.kill(pid, signal.SIGTERM)
            # Give it a moment to shut down gracefully
            time.sleep(1.0)
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    except OSError:
        pass

    PID_FILE.unlink(missing_ok=True)
    return {"status": "stopped", "pid": pid}


def server_status(port: int = DEFAULT_PORT) -> dict:
    """Check if the backend is running."""
    pid = _read_pid()
    return {
        "status": "running" if pid else "stopped",
        "pid": pid,
        "port": port,
        "log_file": str(LOG_FILE),
    }


# ---------------------------------------------------------------------------
# Command dispatch (allow-list)
# ---------------------------------------------------------------------------

COMMANDS = {
    "start": lambda msg: start_server(msg.get("port", DEFAULT_PORT)),
    "stop": lambda _: stop_server(),
    "status": lambda msg: server_status(msg.get("port", DEFAULT_PORT)),
    "ping": lambda _: {"status": "pong", "pid": os.getpid()},
}


def handle_message(msg: dict) -> dict:
    """Dispatch a command from the extension."""
    cmd = msg.get("command", "")
    handler = COMMANDS.get(cmd)
    if not handler:
        return {
            "status": "error",
            "error": f"Unknown command: {cmd}",
            "allowed": list(COMMANDS.keys()),
        }
    try:
        return handler(msg)
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    """Read messages from Chrome, handle them, send responses."""
    while True:
        msg = read_message()
        if msg is None:
            break  # stdin closed (extension disconnected)
        response = handle_message(msg)
        send_message(response)


if __name__ == "__main__":
    main()
