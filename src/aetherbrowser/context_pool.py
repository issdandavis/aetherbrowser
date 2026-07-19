"""
Shared Context Pool for AetherBrowser
=====================================

A process-wide singleton that lets multiple Claude-backed sidebar agents —
running in different browser tabs/windows, each on its own ``/ws`` connection —
share ONE live context.

The pool tracks:
  * the set of currently-connected WebSocket clients,
  * a ``shared_context`` dict (user_intent, page_context, findings, decisions),
  * a rolling ``message_log`` (capped) of recent events,

and offers:
  * ``register`` / ``unregister`` for connection lifecycle,
  * ``broadcast`` to fan a message out to every other live client (dead sockets
    are dropped, never allowed to break the loop),
  * mutators (``update_context`` / ``append_finding`` / ``append_decision`` /
    ``log_message``) guarded by an ``asyncio.Lock``,
  * ``get_context_summary`` -> a compact text block to PREPEND to a Claude
    prompt so every agent answers with shared awareness.

Import the module-level singleton ``POOL`` everywhere; do not instantiate your
own ``ContextPool``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

# Caps keep the pool bounded so a long-lived process never grows without limit.
MESSAGE_LOG_CAP = 200
FINDINGS_CAP = 100
DECISIONS_CAP = 100

# How much to surface in the prompt summary.
_SUMMARY_FINDINGS = 4
_SUMMARY_DECISIONS = 3
_SUMMARY_LOG_LINES = 6
_SUMMARY_TEXT_CLIP = 160


def _clip(value: Any, limit: int = _SUMMARY_TEXT_CLIP) -> str:
    """Render ``value`` as a single compact, length-bounded line."""
    text = " ".join(str(value).split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _summarize_log_entry(msg: dict[str, Any]) -> str:
    """Turn a raw ws message dict into one human-readable log line."""
    agent = msg.get("agent", "?")
    mtype = msg.get("type", "?")
    payload = msg.get("payload") or {}
    snippet = ""
    if isinstance(payload, dict):
        if payload.get("text"):
            snippet = str(payload["text"])
        elif payload.get("state"):
            snippet = f"state={payload['state']}"
        elif payload.get("reason"):
            snippet = f"reason={payload['reason']}"
        elif payload.get("action"):
            snippet = f"action={payload['action']}"
    return f"[{agent}/{mtype}] {_clip(snippet)}".rstrip()


class ContextPool:
    """Process-wide shared awareness for all connected sidebar agents."""

    def __init__(self) -> None:
        # Live WebSocket connections. Typed loosely so this module stays
        # decoupled from FastAPI; any object with an async ``send_json`` works.
        self._connections: set[Any] = set()
        self.shared_context: dict[str, Any] = {
            "user_intent": "",
            "page_context": {},
            "findings": [],
            "decisions": [],
            "message_log": [],
        }
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    async def register(self, ws: Any) -> None:
        """Add a freshly-accepted WebSocket to the live set."""
        async with self._lock:
            self._connections.add(ws)

    async def unregister(self, ws: Any) -> None:
        """Remove a WebSocket (on disconnect). Idempotent."""
        async with self._lock:
            self._connections.discard(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------
    async def broadcast(self, message: dict[str, Any], exclude: Any = None) -> int:
        """
        Send ``message`` to every live connection except ``exclude``.

        Each send is isolated in its own try/except so a single dead socket can
        never break the fan-out loop; failed sockets are pruned afterward.
        Returns the number of clients that received the message.
        """
        # Snapshot under the lock so we never iterate while register/unregister
        # mutates the set, and so we don't hold the lock across network I/O.
        async with self._lock:
            targets: Iterable[Any] = [c for c in self._connections if c is not exclude]

        delivered = 0
        dead: list[Any] = []
        for conn in targets:
            try:
                await conn.send_json(message)
                delivered += 1
            except Exception:
                # Socket is gone or broken — mark for removal, keep looping.
                dead.append(conn)

        if dead:
            async with self._lock:
                for conn in dead:
                    self._connections.discard(conn)
        return delivered

    # ------------------------------------------------------------------
    # Mutators (lock-guarded)
    # ------------------------------------------------------------------
    async def update_context(self, key: str, value: Any) -> None:
        """Set a top-level shared_context key (e.g. user_intent, page_context)."""
        async with self._lock:
            self.shared_context[key] = value

    async def append_finding(self, item: Any) -> None:
        """Record a finding (a discovered fact / answer) for other agents."""
        if item in (None, "", {}, []):
            return
        async with self._lock:
            findings = self.shared_context.setdefault("findings", [])
            findings.append(item)
            if len(findings) > FINDINGS_CAP:
                del findings[: len(findings) - FINDINGS_CAP]

    async def append_decision(self, item: Any) -> None:
        """Record a decision (gate verdict, plan choice) for other agents."""
        if item in (None, "", {}, []):
            return
        async with self._lock:
            decisions = self.shared_context.setdefault("decisions", [])
            decisions.append(item)
            if len(decisions) > DECISIONS_CAP:
                del decisions[: len(decisions) - DECISIONS_CAP]

    async def log_message(self, msg: dict[str, Any]) -> None:
        """Append a raw ws message to the rolling, capped message_log."""
        async with self._lock:
            log = self.shared_context.setdefault("message_log", [])
            log.append(msg)
            if len(log) > MESSAGE_LOG_CAP:
                del log[: len(log) - MESSAGE_LOG_CAP]

    # ------------------------------------------------------------------
    # Read-only summary (safe without the lock under cooperative asyncio:
    # this method never awaits, so it cannot be interrupted mid-read)
    # ------------------------------------------------------------------
    def get_context_summary(self) -> str:
        """
        Build a compact text block describing the current shared state, suitable
        to PREPEND to a Claude prompt so every agent shares awareness.
        """
        ctx = self.shared_context
        intent = _clip(ctx.get("user_intent") or "(none yet)")

        page = ctx.get("page_context") or {}
        title = _clip(page.get("title") or "(no page)", 100) if isinstance(page, dict) else "(no page)"
        url = _clip(page.get("url") or "", 120) if isinstance(page, dict) else ""
        page_line = f"{title} — {url}".rstrip(" — ") if url else title

        findings = ctx.get("findings") or []
        decisions = ctx.get("decisions") or []
        log = ctx.get("message_log") or []

        lines: list[str] = [
            "=== SHARED AGENT CONTEXT ===",
            f"Connected agents: {self.connection_count}",
            f"User intent: {intent}",
            f"Page: {page_line}",
        ]

        if findings:
            lines.append("Recent findings:")
            for item in findings[-_SUMMARY_FINDINGS:]:
                lines.append(f"  - {_clip(item)}")

        if decisions:
            lines.append("Recent decisions:")
            for item in decisions[-_SUMMARY_DECISIONS:]:
                lines.append(f"  - {_clip(item)}")

        if log:
            lines.append("Recent activity:")
            for entry in log[-_SUMMARY_LOG_LINES:]:
                lines.append(f"  - {_summarize_log_entry(entry)}")

        lines.append("=== END SHARED CONTEXT ===")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Read-only JSON snapshot (safe without the lock under cooperative
    # asyncio: this method never awaits, so it cannot be interrupted
    # mid-read, mirroring get_context_summary)
    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """
        Return a JSON-serializable snapshot of the shared context for the
        ``/context`` HTTP endpoint.

        Shape::

            {
                "connected": <int live connection count>,
                "user_intent": <str>,
                "page_context": <dict>,
                "findings": <last 20 findings>,
                "decisions": <last 20 decisions>,
                "recent_log": <last 30 message_log entries>,
            }
        """
        ctx = self.shared_context
        findings = ctx.get("findings") or []
        decisions = ctx.get("decisions") or []
        log = ctx.get("message_log") or []
        return {
            "connected": self.connection_count,
            "user_intent": ctx.get("user_intent", ""),
            "page_context": ctx.get("page_context") or {},
            "findings": list(findings[-20:]),
            "decisions": list(decisions[-20:]),
            "recent_log": list(log[-30:]),
        }


# Process-wide singleton. Import this, do not instantiate ContextPool yourself.
POOL = ContextPool()
