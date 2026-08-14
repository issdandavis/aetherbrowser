r"""headless_contract.py -- verify the non-UI AetherBrowser agent contract.

Run from C:\dev\aetherbrowser:

    python tests\headless_contract.py

This intentionally avoids live model execution. It proves external agents can:
  1. discover the control-plane contract,
  2. publish page context,
  3. plan a read-only command,
  4. get approval gating for risky commands.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8092
BASE = f"http://127.0.0.1:{PORT}"
STATE_DIR = tempfile.mkdtemp(prefix="aetherbrowser-kernel-contract-")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def request_json(path, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read())


def wait_for_backend():
    for _ in range(40):
        try:
            request_json("/health")
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    print("=" * 64)
    print("  AetherBrowser headless contract test")
    print("=" * 64)
    env = dict(os.environ, PYTHONPATH=ROOT, AETHERBROWSER_STATE_DIR=STATE_DIR)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.aetherbrowser.serve:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        up = wait_for_backend()
        check("backend boots", up)
        if not up:
            return finish(proc)

        capabilities = request_json("/headless/capabilities")
        check(
            "capabilities expose headless-http",
            "headless-http" in capabilities.get("surfaces", []),
            str(capabilities.get("surfaces")),
        )

        page = request_json(
            "/headless/page-context",
            {
                "url": "https://example.com/demo",
                "title": "Example Demo",
                "text": "AetherBrowser mobile and desktop agents share context.",
                "headings": ["Demo"],
                "links": [{"text": "Docs", "href": "https://example.com/docs"}],
                "forms": [],
                "buttons": [],
                "tabs": [],
                "selection": "",
                "page_type": "test",
            },
        )
        check("page context accepted", page.get("status") == "analyzed", page.get("status", ""))
        check(
            "page context updates shared context",
            page.get("context", {}).get("page_context", {}).get("title") == "Example Demo",
        )
        check(
            "page context creates a hashed kernel observation",
            len(page.get("kernel_observation", {}).get("fingerprint", "")) == 64,
        )

        kernel_caps = request_json("/kernel/capabilities")
        check(
            "kernel exposes transaction cycle",
            kernel_caps.get("model") == "observe -> plan -> approve -> dispatch -> verify -> receipt",
        )

        read_plan = request_json(
            "/kernel/plan",
            {"action": {"op": "capture"}, "source": "contract-test"},
        )
        check("read-only kernel action is ready", read_plan.get("status") == "ready", read_plan.get("status", ""))
        read_tx = read_plan.get("transaction_id", "")
        read_dispatch = request_json("/kernel/dispatch", {"transaction_id": read_tx})
        check("ready kernel action dispatches", read_dispatch.get("status") == "dispatched")
        read_verify = request_json(
            "/kernel/verify",
            {
                "transaction_id": read_tx,
                "result": {"status": "success"},
                "observation": {
                    "url": "https://example.com/demo",
                    "title": "Example Demo",
                    "text": "AetherBrowser mobile and desktop agents share context.",
                    "headings": ["Demo"],
                    "links": [{"text": "Docs", "href": "https://example.com/docs"}],
                    "forms": [],
                    "buttons": [],
                    "tabs": [],
                    "selection": "",
                    "page_type": "test",
                },
            },
        )
        check("read-only result verifies", read_verify.get("status") == "verified", read_verify.get("status", ""))

        fill_plan = request_json(
            "/kernel/plan",
            {
                "action": {"op": "smartFill", "query": "Search", "text": "mars drones"},
                "source": "contract-test",
            },
        )
        check(
            "state-changing kernel action is held",
            fill_plan.get("status") == "approval_required",
            fill_plan.get("status", ""),
        )
        fill_tx = fill_plan.get("transaction_id", "")
        held_dispatch = request_json("/kernel/dispatch", {"transaction_id": fill_tx})
        check("held kernel action cannot dispatch", held_dispatch.get("ok") is False)
        approval = request_json(
            "/kernel/approve",
            {"transaction_id": fill_tx, "decision": "approve", "actor": "contract-test"},
        )
        check("explicit approval releases action", approval.get("status") == "approved")
        fill_dispatch = request_json("/kernel/dispatch", {"transaction_id": fill_tx})
        check(
            "approved fill dispatches with ephemeral text",
            fill_dispatch.get("dispatch_action", {}).get("text") == "mars drones",
        )
        fill_verify = request_json(
            "/kernel/verify",
            {
                "transaction_id": fill_tx,
                "result": {"status": "success", "target_found": True},
                "observation": {
                    "url": "https://example.com/demo",
                    "title": "Example Demo",
                    "text": "AetherBrowser mobile and desktop agents share context. mars drones",
                    "headings": ["Demo"],
                    "links": [{"text": "Docs", "href": "https://example.com/docs"}],
                    "forms": [],
                    "buttons": [],
                    "tabs": [],
                    "selection": "",
                    "page_type": "test",
                },
            },
        )
        check("approved state change verifies against new observation", fill_verify.get("status") == "verified")

        denied = request_json(
            "/kernel/plan",
            {"action": {"op": "smartClick", "query": "Delete account"}, "source": "contract-test"},
        )
        check("disabled remote-write action is denied", denied.get("status") == "denied", denied.get("reason", ""))

        named_save = request_json("/kernel/save", {"kind": "named", "name": "contract-green"})
        check("named save is hash-addressed", len(named_save.get("sha256", "")) == 64)
        saves = request_json("/kernel/saves")
        check("named save remains listed", bool(saves.get("saves", {}).get("named")))
        receipts = request_json("/kernel/receipts?limit=100")
        receipt_text = json.dumps(receipts, sort_keys=True)
        check("receipt chain never stores fill text", "mars drones" not in receipt_text)
        kernel_status = request_json("/kernel/status")
        check("receipt hash chain verifies", kernel_status.get("receipt_chain_ok") is True)

        planned = request_json(
            "/headless/command",
            {"text": "summarize this page for an agent", "execute": False, "source": "contract-test"},
        )
        check("headless command plans", planned.get("status") == "planned", planned.get("status", ""))
        check("headless plan has actions", bool(planned.get("plan", {}).get("next_actions")))

        held = request_json(
            "/headless/command",
            {"text": "delete the account and submit the form", "source": "contract-test"},
        )
        check("risky command is held", held.get("status") == "approval_required", held.get("status", ""))

        action = request_json(
            "/headless/browser-action",
            {"action": "navigate", "url": "https://example.com", "source": "contract-test"},
        )
        check("browser action queues", action.get("status") == "queued", action.get("status", ""))
        queued = request_json("/headless/browser-actions")
        check("browser action is visible", bool(queued.get("pending")))

        state = request_json("/headless/controller-state")
        check("controller state exposes game model", state.get("model") == "webpage_as_game_state", state.get("model", ""))
        held_controller = request_json(
            "/headless/controller-event",
            {"event": "primary", "source": "contract-test"},
        )
        check(
            "state-changing controller event is held",
            held_controller.get("status") == "approval_required",
            held_controller.get("status", ""),
        )
        move = request_json(
            "/headless/controller-event",
            {"event": "move_down", "source": "contract-test", "intensity": 0.25},
        )
        check("movement controller event queues", move.get("status") == "queued", move.get("status", ""))
    except Exception as exc:
        check("unexpected exception", False, repr(exc))
    finally:
        finish(proc)


def finish(proc):
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"], capture_output=True, shell=True)
        else:
            proc.terminate()
    except Exception:
        pass
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    passed = sum(1 for _, ok, _ in results if ok)
    print("-" * 64)
    print(f"  {passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) and results else 1)


if __name__ == "__main__":
    main()
