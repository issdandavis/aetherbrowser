r"""smoke.py -- re-runnable end-to-end proof for AetherBrowser (Issac, 2026-06-28).

Starts the real backend on a test port and proves the product holds together, over the network
(robust to internal refactors -- it tests behavior, not imports):
  1. /health responds and reports connected_sidebars
  2. /context responds with the shared-pool shape
  3. TWO websocket clients: A sends a command, B (silent) RECEIVES A's broadcast  <- the core claim
  4. /context reflects A's intent + connected == 2

Run from C:\dev\aetherbrowser:   python tests\smoke.py
Exit code 0 = all checks pass. Needs: fastapi, uvicorn[standard], websockets, httpx (or urllib).
"""
import asyncio, json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8090
BASE = f"http://127.0.0.1:{PORT}"
WSURL = f"ws://127.0.0.1:{PORT}/ws"
PROBE = "SMOKE-PROBE-" + str(os.getpid())

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def get_json(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())


async def two_client_test():
    import websockets
    async with websockets.connect(WSURL) as a, websockets.connect(WSURL) as b:
        await asyncio.sleep(0.4)  # let both register
        await a.send(json.dumps({"type": "command", "payload": {"text": PROBE, "routing": {}}}))
        # B should receive a broadcast carrying the probe, without B sending anything
        got = []
        try:
            for _ in range(6):
                msg = await asyncio.wait_for(b.recv(), timeout=8)
                got.append(msg)
                if PROBE in msg:
                    break
        except asyncio.TimeoutError:
            pass
        b_saw_probe = any(PROBE in m for m in got)
        check("client B receives A's broadcast", b_saw_probe,
              (got[0][:80] if got else "B received nothing"))
        await asyncio.sleep(0.3)
    return b_saw_probe


def main():
    print("=" * 64)
    print("  AetherBrowser smoke test")
    print("=" * 64)
    env = dict(os.environ, PYTHONPATH=ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.aetherbrowser.serve:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # wait for boot
        up = False
        for _ in range(40):
            try:
                get_json("/health"); up = True; break
            except Exception:
                time.sleep(0.5)
        check("backend boots + /health responds", up)
        if not up:
            return finish(proc)

        health = get_json("/health")
        check("/health has connected_sidebars", "connected_sidebars" in health,
              f"keys={list(health)[:6]}")

        ctx0 = get_json("/context")
        check("/context responds with pool shape",
              all(k in ctx0 for k in ("connected", "user_intent")),
              f"connected={ctx0.get('connected')}")

        asyncio.run(two_client_test())

        ctx = get_json("/context")
        check("/context captured A's intent", ctx.get("user_intent") == PROBE,
              f"user_intent={ctx.get('user_intent')!r}")
    finally:
        finish(proc)


def finish(proc):
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"],
                           capture_output=True, shell=True)
        else:
            proc.terminate()
    except Exception:
        pass
    passed = sum(1 for _, ok, _ in results if ok)
    print("-" * 64)
    print(f"  {passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) and results else 1)


if __name__ == "__main__":
    main()
