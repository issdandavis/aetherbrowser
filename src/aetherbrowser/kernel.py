"""Governed transaction kernel for AetherBrowser.

The browser, Clay, AetherDesk, and cloud runners all speak through this small
state machine.  It deliberately does *not* execute arbitrary code or accept an
open-ended tool name.  A page observation is fingerprinted, an allowlisted
action is planned, risky actions are held, released actions are dispatched,
and the caller returns a post-action observation for deterministic checks.

Only metadata and hashes are persisted.  In particular, text entered into a
page is held in process memory and represented on disk by its length and
SHA-256 digest.  A restarted process therefore cannot replay sensitive input;
the caller must propose it again.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import uuid4


SCHEMA_VERSION = "aetherbrowser.kernel.v1"
RECEIPT_SCHEMA = "aetherbrowser.receipt-chain.v1"

_ACTION_ALIASES = {
    "capture": "capture",
    "capture_page_context": "capture",
    "read": "read_page",
    "read_page": "read_page",
    "navigate": "navigate",
    "highlight": "highlight",
    "smarthighlight": "highlight",
    "click": "click",
    "smartclick": "click",
    "fill": "fill",
    "smartfill": "fill",
    "scroll": "scroll",
    "done": "done",
    "refuse": "refuse",
}

_READ_ONLY_ACTIONS = {"capture", "read_page", "highlight", "scroll", "done", "refuse"}
_APPROVAL_ACTIONS = {"navigate", "click", "fill"}
_HIGH_IMPACT_MARKERS = {
    "buy",
    "checkout",
    "delete",
    "deploy",
    "password",
    "pay",
    "payment",
    "private key",
    "publish",
    "purchase",
    "secret",
    "submit",
    "token",
    "transfer",
    "wallet",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _compact_text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _safe_name(value: Any, fallback: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return (name[:80] or fallback)


def _structure_list(value: Any, keys: tuple[str, ...]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value[:200]:
        if isinstance(item, dict):
            rows.append({key: _compact_text(item.get(key), 160) for key in keys if item.get(key) not in (None, "")})
        elif item not in (None, ""):
            rows.append({keys[0]: _compact_text(item, 160)})
    return rows


def _url_metadata(value: Any) -> tuple[str, str]:
    """Return a citation-safe URL plus a hash of query/fragment details."""
    raw = str(value or "").strip()
    try:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        try:
            port = parsed.port
        except ValueError:
            port = None
        netloc = f"{host}:{port}" if port else host
        safe = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, "", ""))
        detail = "?" + parsed.query if parsed.query else ""
        if parsed.fragment:
            detail += "#" + parsed.fragment
        return _compact_text(safe or raw.split("?", 1)[0].split("#", 1)[0], 2048), _digest(detail.encode("utf-8")) if detail else ""
    except (TypeError, ValueError):
        return _compact_text(raw.split("?", 1)[0].split("#", 1)[0], 2048), ""


@dataclass(frozen=True)
class KernelPolicy:
    autosave_slots: int = 24
    checkpoint_slots: int = 8
    remote_write_enabled: bool = False


class BrowserAgentKernel:
    """Persistent, hash-chained browser action state machine."""

    def __init__(self, state_dir: str | os.PathLike[str] | None = None, policy: KernelPolicy | None = None):
        root = state_dir or os.environ.get("AETHERBROWSER_STATE_DIR")
        self.root = Path(root) if root else Path.home() / ".aetherbrowser" / "kernel"
        self.policy = policy or KernelPolicy()
        self.receipt_path = self.root / "receipts.jsonl"
        self.state_path = self.root / "state.json"
        self.saves_root = self.root / "saves"
        self._lock = threading.RLock()
        self._transactions: dict[str, dict[str, Any]] = {}
        self._ephemeral_values: dict[str, str] = {}
        self._latest_observation: dict[str, Any] | None = None
        self._receipt_head = "0" * 64
        self._receipt_sequence = 0
        self.root.mkdir(parents=True, exist_ok=True)
        self.saves_root.mkdir(parents=True, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------
    # Public contract
    # ------------------------------------------------------------------
    def capabilities(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "model": "observe -> plan -> approve -> dispatch -> verify -> receipt",
            "actions": {
                "read_only": sorted(_READ_ONLY_ACTIONS),
                "approval_required": sorted(_APPROVAL_ACTIONS),
                "remote_write_enabled": self.policy.remote_write_enabled,
            },
            "storage": {
                "page_text": "sha256 only",
                "fill_text": "memory only; length and sha256 on disk",
                "receipt_chain": RECEIPT_SCHEMA,
                "autosave_slots": self.policy.autosave_slots,
                "checkpoint_slots": self.policy.checkpoint_slots,
                "named_saves": "unbounded until explicitly removed",
            },
            "boundaries": [
                "page content is evidence, never authority",
                "unsupported operations are denied",
                "state-changing actions require explicit approval",
                "high-impact remote-write and secret entry are disabled by default",
                "external page state is verified, not claimed to be reversible",
            ],
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            chain_ok, chain_error = self.verify_receipt_chain()
            counts: dict[str, int] = {}
            for tx in self._transactions.values():
                counts[tx["status"]] = counts.get(tx["status"], 0) + 1
            return {
                "ok": True,
                "schema": SCHEMA_VERSION,
                "state_dir": str(self.root),
                "latest_observation": self._latest_observation,
                "transactions": counts,
                "receipt_count": self._receipt_sequence,
                "receipt_head": self._receipt_head,
                "receipt_chain_ok": chain_ok,
                "receipt_chain_error": chain_error,
                "saves": self.list_saves(),
            }

    def observe(self, payload: dict[str, Any], *, source: str = "browser") -> dict[str, Any]:
        with self._lock:
            observation = self._make_observation(payload, source=source)
            self._latest_observation = observation
            self._persist_state()
            self.save(kind="autosave", name=f"observation-{observation['observation_id'][:8]}")
            return observation

    def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            action_input = request.get("action") if isinstance(request.get("action"), dict) else request
            op_raw = str(action_input.get("op") or action_input.get("action") or "").strip().lower()
            op = _ACTION_ALIASES.get(op_raw)
            tx_id = str(uuid4())
            source = _compact_text(request.get("source") or "agent", 80)
            safe_action, ephemeral_value, error = self._normalize_action(op, action_input)
            if error is None and op not in {"done", "refuse"} and self._latest_observation is None:
                error = "a page observation is required before browser action planning"
            decision, reason = self._decision_for_action(op, safe_action, error)
            status = {
                "allow": "ready",
                "approval_required": "approval_required",
                "deny": "denied",
            }[decision]
            tx = {
                "transaction_id": tx_id,
                "schema": SCHEMA_VERSION,
                "created_at": _now(),
                "updated_at": _now(),
                "source": source,
                "status": status,
                "decision": decision,
                "reason": reason,
                "action": safe_action,
                "before_observation_id": (
                    self._latest_observation.get("observation_id") if self._latest_observation else None
                ),
                "before_fingerprint": (
                    self._latest_observation.get("fingerprint") if self._latest_observation else None
                ),
                "approval": None,
                "verification": None,
            }
            self._transactions[tx_id] = tx
            if ephemeral_value is not None:
                self._ephemeral_values[tx_id] = ephemeral_value
            self._append_receipt("plan", tx_id, {"decision": decision, "reason": reason, "action": safe_action})
            self._persist_state()
            return {"ok": decision != "deny", **self._public_transaction(tx)}

    def approve(self, transaction_id: str, *, decision: str, actor: str = "user") -> dict[str, Any]:
        with self._lock:
            tx = self._transactions.get(transaction_id)
            if tx is None:
                return self._error("unknown_transaction", transaction_id)
            normalized = decision.strip().lower()
            if tx["status"] != "approval_required":
                return self._error("transaction_not_waiting_for_approval", transaction_id, tx["status"])
            if normalized not in {"approve", "deny"}:
                return self._error("approval_must_be_approve_or_deny", transaction_id)
            tx["approval"] = {"decision": normalized, "actor": _compact_text(actor, 80), "at": _now()}
            tx["status"] = "approved" if normalized == "approve" else "denied"
            tx["updated_at"] = _now()
            self._append_receipt("approval", transaction_id, tx["approval"])
            self._persist_state()
            return {"ok": True, **self._public_transaction(tx)}

    def dispatch(self, transaction_id: str) -> dict[str, Any]:
        with self._lock:
            tx = self._transactions.get(transaction_id)
            if tx is None:
                return self._error("unknown_transaction", transaction_id)
            if tx["status"] not in {"ready", "approved"}:
                return self._error("transaction_not_releasable", transaction_id, tx["status"])
            current_fingerprint = self._latest_observation.get("fingerprint") if self._latest_observation else None
            if tx["before_fingerprint"] != current_fingerprint:
                tx["status"] = "stale"
                tx["updated_at"] = _now()
                self._append_receipt(
                    "dispatch_denied",
                    transaction_id,
                    {"reason": "page_changed_since_plan", "current_fingerprint": current_fingerprint},
                )
                self._persist_state()
                return self._error("page_changed_since_plan", transaction_id, "stale")
            action = dict(tx["action"])
            if action.get("op") in {"fill", "navigate"}:
                value = self._ephemeral_values.get(transaction_id)
                if value is None:
                    tx["status"] = "expired"
                    tx["updated_at"] = _now()
                    self._append_receipt("dispatch_denied", transaction_id, {"reason": "ephemeral_value_expired"})
                    self._persist_state()
                    return self._error("ephemeral_value_expired_replan_required", transaction_id, "expired")
                if action.get("op") == "fill":
                    action["text"] = value
                else:
                    action["url"] = value
            tx["status"] = "dispatched"
            tx["updated_at"] = _now()
            self._append_receipt("dispatch", transaction_id, {"action": tx["action"]})
            self._persist_state()
            return {"ok": True, **self._public_transaction(tx), "dispatch_action": action}

    def verify(self, transaction_id: str, *, result: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            tx = self._transactions.get(transaction_id)
            if tx is None:
                return self._error("unknown_transaction", transaction_id)
            if tx["status"] != "dispatched":
                return self._error("transaction_not_dispatched", transaction_id, tx["status"])
            after = self._make_observation(observation, source=f"verify:{transaction_id[:8]}")
            passed, reason = self._verify_action(tx, result, after)
            verification = {
                "passed": passed,
                "reason": reason,
                "result_status": _compact_text(result.get("status"), 40),
                "before_fingerprint": tx.get("before_fingerprint"),
                "after_fingerprint": after["fingerprint"],
                "after_observation_id": after["observation_id"],
                "at": _now(),
            }
            tx["verification"] = verification
            tx["status"] = "verified" if passed else "verification_failed"
            tx["updated_at"] = _now()
            self._latest_observation = after
            self._ephemeral_values.pop(transaction_id, None)
            receipt = self._append_receipt("verification", transaction_id, verification)
            self._persist_state()
            self.save(kind="checkpoint", name=f"{tx['status']}-{transaction_id[:8]}")
            return {
                "ok": passed,
                **self._public_transaction(tx),
                "verification": verification,
                "receipt": receipt,
                "rollback_recommended": not passed,
            }

    def receipts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._read_receipts()
            return rows[-max(1, min(int(limit), 1000)) :]

    def verify_receipt_chain(self) -> tuple[bool, str | None]:
        previous = "0" * 64
        expected_sequence = 1
        try:
            for receipt in self._read_receipts():
                claimed = receipt.get("receipt_hash")
                unsigned = {key: value for key, value in receipt.items() if key != "receipt_hash"}
                if receipt.get("sequence") != expected_sequence:
                    return False, f"sequence {receipt.get('sequence')} != {expected_sequence}"
                if receipt.get("previous_hash") != previous:
                    return False, f"previous hash mismatch at sequence {expected_sequence}"
                actual = _digest(unsigned)
                if claimed != actual:
                    return False, f"receipt hash mismatch at sequence {expected_sequence}"
                previous = claimed
                expected_sequence += 1
        except (OSError, ValueError, TypeError) as exc:
            return False, str(exc)
        return True, None

    def _read_receipts(self) -> list[dict[str, Any]]:
        if not self.receipt_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.receipt_path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def save(self, *, kind: str, name: str = "") -> dict[str, Any]:
        with self._lock:
            normalized_kind = kind.strip().lower()
            if normalized_kind not in {"autosave", "checkpoint", "named", "champion", "rollback"}:
                return self._error("unsupported_save_kind", "", normalized_kind)
            directory = self.saves_root / normalized_kind
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe_name = _safe_name(name, normalized_kind)
            path = directory / f"{stamp}-{uuid4().hex[:8]}-{safe_name}.json"
            snapshot = {
                "schema": SCHEMA_VERSION,
                "kind": normalized_kind,
                "name": safe_name,
                "created_at": _now(),
                "receipt_head": self._receipt_head,
                "receipt_count": self._receipt_sequence,
                "latest_observation": self._latest_observation,
                "transactions": {key: self._public_transaction(value) for key, value in self._transactions.items()},
            }
            path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
            if normalized_kind == "autosave":
                self._prune(directory, self.policy.autosave_slots)
            elif normalized_kind == "checkpoint":
                self._prune(directory, self.policy.checkpoint_slots)
            return {"ok": True, "kind": normalized_kind, "name": safe_name, "path": str(path), "sha256": _digest(path.read_bytes())}

    def list_saves(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        if not self.saves_root.exists():
            return result
        for directory in sorted(path for path in self.saves_root.iterdir() if path.is_dir()):
            result[directory.name] = [
                {"name": path.name, "bytes": path.stat().st_size, "sha256": _digest(path.read_bytes())}
                for path in sorted(directory.glob("*.json"))
            ]
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _make_observation(self, payload: dict[str, Any], *, source: str) -> dict[str, Any]:
        text = str(payload.get("text") or "")
        safe_url, url_detail_hash = _url_metadata(payload.get("url"))
        structure = {
            "url": safe_url,
            "url_detail_sha256": url_detail_hash,
            "title": _compact_text(payload.get("title"), 300),
            "page_type": _compact_text(payload.get("page_type") or "generic", 80),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "word_count": len(text.split()),
            "headings": _structure_list(payload.get("headings"), ("text", "level")),
            "links": _structure_list(payload.get("links"), ("text", "href")),
            "forms": _structure_list(payload.get("forms"), ("name", "action", "method")),
            "buttons": _structure_list(payload.get("buttons"), ("text", "name", "type")),
            "selection_sha256": hashlib.sha256(str(payload.get("selection") or "").encode("utf-8")).hexdigest(),
        }
        return {
            "schema": SCHEMA_VERSION,
            "observation_id": str(uuid4()),
            "created_at": _now(),
            "source": _compact_text(source, 80),
            "url": structure["url"],
            "url_detail_sha256": structure["url_detail_sha256"],
            "title": structure["title"],
            "page_type": structure["page_type"],
            "word_count": structure["word_count"],
            "fingerprint": _digest(structure),
            "structure_hash": _digest({key: value for key, value in structure.items() if key != "text_sha256"}),
        }

    def _normalize_action(
        self, op: str | None, action: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None, str | None]:
        if op is None:
            return {"op": str(action.get("op") or action.get("action") or "")}, None, "unsupported operation"
        safe: dict[str, Any] = {"op": op}
        ephemeral: str | None = None
        if op == "navigate":
            url = str(action.get("url") or action.get("target") or "").strip()
            error = self._validate_navigation_url(url)
            safe_url, url_detail_hash = _url_metadata(url)
            safe["url"] = safe_url
            if url_detail_hash:
                safe["url_detail_sha256"] = url_detail_hash
            return safe, url, error
        if op in {"click", "highlight", "fill"}:
            query = _compact_text(action.get("query") or action.get("target"), 240)
            if not query:
                return safe, None, f"{op} requires a target query"
            safe["query"] = query
        if op == "fill":
            ephemeral = str(action.get("text") if action.get("text") is not None else action.get("value") or "")
            if not ephemeral:
                return safe, None, "fill requires text"
            safe["value_length"] = len(ephemeral)
            safe["value_sha256"] = hashlib.sha256(ephemeral.encode("utf-8")).hexdigest()
        if op == "scroll":
            direction = str(action.get("direction") or "down").strip().lower()
            if direction not in {"up", "down", "left", "right"}:
                return safe, None, "scroll direction must be up, down, left, or right"
            safe["direction"] = direction
        return safe, ephemeral, None

    def _decision_for_action(
        self, op: str | None, action: dict[str, Any], error: str | None
    ) -> tuple[str, str]:
        if error:
            return "deny", error
        if op is None:
            return "deny", "operation is not in the fixed protocol"
        target = " ".join(str(value).lower() for value in action.values())
        high_impact = sorted(marker for marker in _HIGH_IMPACT_MARKERS if marker in target)
        if high_impact and not self.policy.remote_write_enabled:
            return "deny", f"remote-write or secret capability disabled ({', '.join(high_impact)})"
        if op in _APPROVAL_ACTIONS:
            return "approval_required", f"{op} can change browser or page state"
        return "allow", "read-only or internal action"

    @staticmethod
    def _validate_navigation_url(url: str) -> str | None:
        try:
            parsed = urlparse(url)
        except ValueError:
            return "invalid navigation URL"
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "navigation requires an http(s) URL"
        if parsed.username or parsed.password:
            return "embedded URL credentials are forbidden"
        hostname = parsed.hostname.lower().rstrip(".")
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
            return "local network navigation is not available through this lane"
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return None
        if not address.is_global:
            return "private, loopback, link-local, and reserved IP navigation is forbidden"
        return None

    @staticmethod
    def _verify_action(tx: dict[str, Any], result: dict[str, Any], after: dict[str, Any]) -> tuple[bool, str]:
        if str(result.get("status") or "").lower() not in {"ok", "success", "completed"}:
            return False, "executor did not report success"
        op = tx["action"]["op"]
        before = tx.get("before_fingerprint")
        changed = after["fingerprint"] != before
        if op == "navigate":
            target = tx["action"].get("url", "").rstrip("/")
            observed = after.get("url", "").rstrip("/")
            target_detail = tx["action"].get("url_detail_sha256", "")
            observed_detail = after.get("url_detail_sha256", "")
            matched = observed == target and observed_detail == target_detail
            return (matched, "navigation target observed" if matched else "navigation target not observed")
        if op in {"click", "fill"}:
            target_found = result.get("target_found")
            if target_found is False:
                return False, "target was not found"
            return (changed, "page state changed" if changed else "state-changing action produced no observed change")
        if op == "highlight" and result.get("target_found") is False:
            return False, "highlight target was not found"
        return True, "successful read-only or internal action"

    def _append_receipt(self, event: str, transaction_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._receipt_sequence += 1
        unsigned = {
            "schema": RECEIPT_SCHEMA,
            "sequence": self._receipt_sequence,
            "created_at": _now(),
            "event": event,
            "transaction_id": transaction_id,
            "payload": payload,
            "previous_hash": self._receipt_head,
        }
        receipt = {**unsigned, "receipt_hash": _digest(unsigned)}
        with self.receipt_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
        self._receipt_head = receipt["receipt_hash"]
        return receipt

    def _persist_state(self) -> None:
        payload = {
            "schema": SCHEMA_VERSION,
            "updated_at": _now(),
            "receipt_head": self._receipt_head,
            "receipt_sequence": self._receipt_sequence,
            "latest_observation": self._latest_observation,
            "transactions": self._transactions,
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_path)

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
                if payload.get("schema") == SCHEMA_VERSION:
                    self._transactions = payload.get("transactions") or {}
                    self._latest_observation = payload.get("latest_observation")
            except (OSError, ValueError, TypeError):
                self._transactions = {}
                self._latest_observation = None
        if self.receipt_path.exists():
            try:
                lines = [line for line in self.receipt_path.read_text(encoding="utf-8").splitlines() if line]
                if lines:
                    last = json.loads(lines[-1])
                    self._receipt_sequence = int(last.get("sequence", 0))
                    self._receipt_head = str(last.get("receipt_hash") or self._receipt_head)
            except (OSError, ValueError, TypeError):
                self._receipt_sequence = 0
                self._receipt_head = "0" * 64

    @staticmethod
    def _public_transaction(tx: dict[str, Any]) -> dict[str, Any]:
        return {
            "transaction_id": tx["transaction_id"],
            "created_at": tx["created_at"],
            "updated_at": tx["updated_at"],
            "source": tx["source"],
            "status": tx["status"],
            "decision": tx["decision"],
            "reason": tx["reason"],
            "action": tx["action"],
            "before_observation_id": tx.get("before_observation_id"),
            "before_fingerprint": tx.get("before_fingerprint"),
            "approval": tx.get("approval"),
            "verification": tx.get("verification"),
        }

    @staticmethod
    def _error(error: str, transaction_id: str = "", status: str = "error") -> dict[str, Any]:
        return {"ok": False, "status": status, "error": error, "transaction_id": transaction_id}

    @staticmethod
    def _prune(directory: Path, keep: int) -> None:
        paths = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
        for path in paths[: max(0, len(paths) - keep)]:
            path.unlink()
