r"""qa_check.py -- prove the product actually ANSWERS (not just relays plumbing).
Boots the backend, asks the Paris/42 question over the ws, prints the model answer, and PASSES
only if the answer mentions Paris and 42 (i.e. the prompt fix surfaced the real model answer
instead of the orchestration framing). Needs ollama running. Run: python tests\qa_check.py
"""
import asyncio, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8091
Q = "In one short sentence, what is the capital of France and what is 17 plus 25?"


async def ask():
    import websockets
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({"type": "command", "payload": {"text": Q, "routing": {}}}))
        answer, provider = "", ""
        try:
            for _ in range(12):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=40))
                if msg.get("type") == "chat":
                    payload = msg.get("payload", {})
                    answer = payload.get("text", "")
                    provider = (payload.get("execution") or {}).get("model_id", "")
                    if answer:
                        break
        except asyncio.TimeoutError:
            pass
        return answer, provider


def main():
    env = dict(os.environ, PYTHONPATH=ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.aetherbrowser.serve:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import urllib.request
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5); break
            except Exception:
                time.sleep(0.5)
        answer, provider = asyncio.run(ask())
        print("=" * 64)
        print("  Q:", Q)
        print("  provider/model:", provider)
        print("  ANSWER:", answer)
        print("-" * 64)
        ok = ("paris" in answer.lower()) and ("42" in answer)
        from_real_model = "qwen" in provider.lower() or "scbe" in provider.lower()
        print(f"  mentions Paris + 42 : {'PASS' if ok else 'FAIL'}")
        print(f"  from real ollama model: {'PASS' if from_real_model else 'FAIL'} ({provider})")
        sys.exit(0 if (ok and from_real_model) else 1)
    finally:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"],
                               capture_output=True, shell=True)
            else:
                proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
