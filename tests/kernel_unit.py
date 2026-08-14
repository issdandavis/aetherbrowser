r"""Deterministic edge-case tests for the AetherBrowser transaction kernel."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.aetherbrowser.kernel import BrowserAgentKernel  # noqa: E402


RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def page(text: str = "one", url: str = "https://example.com/page") -> dict:
    return {
        "url": url,
        "title": "Kernel test",
        "text": text,
        "headings": [{"text": "Test", "level": 1}],
        "links": [],
        "forms": [],
        "buttons": [],
        "page_type": "test",
    }


def main() -> None:
    print("=" * 64)
    print("  AetherBrowser kernel unit tests")
    print("=" * 64)
    with tempfile.TemporaryDirectory(prefix="aetherbrowser-kernel-unit-") as temporary:
        root = Path(temporary)
        kernel = BrowserAgentKernel(root)

        unsupported = kernel.plan({"action": {"op": "runJavaScript", "text": "alert(1)"}})
        check("unknown operation denied", unsupported["status"] == "denied", unsupported["reason"])

        local = kernel.plan({"action": {"op": "navigate", "url": "http://127.0.0.1:9000/admin"}})
        check("loopback navigation denied", local["status"] == "denied", local["reason"])

        blind = kernel.plan({"action": {"op": "capture"}})
        check("browser action requires prior observation", blind["status"] == "denied", blind["reason"])

        kernel.observe(page(), source="unit")
        stale = kernel.plan({"action": {"op": "capture"}})
        kernel.observe(page("two"), source="unit")
        stale_dispatch = kernel.dispatch(stale["transaction_id"])
        check("changed precondition makes plan stale", stale_dispatch["status"] == "stale")

        click = kernel.plan({"action": {"op": "smartClick", "query": "Open details"}})
        kernel.approve(click["transaction_id"], decision="approve", actor="unit")
        kernel.dispatch(click["transaction_id"])
        unchanged = kernel.verify(
            click["transaction_id"],
            result={"status": "success", "target_found": True},
            observation=page("two"),
        )
        check("unchanged state fails click verification", unchanged["status"] == "verification_failed")
        check("failed verification recommends rollback", unchanged["rollback_recommended"] is True)

        secret_text = "ephemeral phrase that must not reach disk"
        fill = kernel.plan({"action": {"op": "fill", "query": "Search", "text": secret_text}})
        kernel.approve(fill["transaction_id"], decision="approve", actor="unit")
        on_disk = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.json*"))
        check("fill text absent from persistent state", secret_text not in on_disk)
        restarted = BrowserAgentKernel(root)
        expired = restarted.dispatch(fill["transaction_id"])
        check("restart expires ephemeral fill value", expired["status"] == "expired")

        restarted.observe(page("query privacy"), source="unit")
        private_query = "private lesson wording"
        navigate = restarted.plan(
            {"action": {"op": "navigate", "url": f"https://example.com/search?q={private_query}"}}
        )
        persisted = (root / "state.json").read_text(encoding="utf-8")
        check("URL query value absent from persistent state", private_query not in persisted)
        check("URL query represented by a digest", len(navigate["action"].get("url_detail_sha256", "")) == 64)

        for index in range(30):
            restarted.observe(page(f"autosave {index}"), source="unit")
        for index in range(12):
            restarted.save(kind="checkpoint", name=f"checkpoint-{index}")
        saves = restarted.list_saves()
        check("autosave ring is bounded at 24", len(saves.get("autosave", [])) == 24)
        check("checkpoint stack is bounded at 8", len(saves.get("checkpoint", [])) == 8)

        chain_ok, chain_error = restarted.verify_receipt_chain()
        check("untampered receipt chain verifies", chain_ok, str(chain_error or ""))
        receipt_path = root / "receipts.jsonl"
        lines = receipt_path.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["payload"]["reason"] = "tampered"
        lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
        receipt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tampered_ok, tampered_error = restarted.verify_receipt_chain()
        check("tampering is detected", not tampered_ok, str(tampered_error or ""))

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("-" * 64)
    print(f"  {passed}/{len(RESULTS)} checks passed")
    raise SystemExit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
