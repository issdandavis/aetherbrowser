"""build_browser_sft.py -- turn recorded AetherBrowser sessions into verified SFT so Issac's HOMEMADE model learns
to drive his own (free) browser. The closed $0 loop: his model uses the browser -> the browser records the
trajectory (aether_train_recorder) -> this builds SFT -> LoRA-train his model -> it browses better -> repeat.

Verified-trajectory style (his VTC): ONLY successful trajectories (done:true) become POSITIVE (observation->action)
pairs; actions the governor BLOCKED become REFUSAL pairs (so the model also learns the action_gate policy).

Reads the recorder's JSONL (default %LOCALAPPDATA%\\aetherbrowser-trajectories.jsonl); if absent, runs a synthetic
self-test so the pipeline is verifiable without a live browser.
"""
from __future__ import annotations
import sys, os, json, glob

SYS = ("You are AetherBrowser's agent. Given the TASK and PAGE STATE, reply with EXACTLY one JSON action: "
       '{"tool":"<name>","args":{...}} or {"done":true,"answer":"..."}. '
       "Tools: navigate, read_page, get_text, find, click, type, form_input, key, scroll, screenshot, console, network.")


def to_sft(traj):
    """One recorded trajectory -> a list of SFT pairs (positive from success, refusal from blocked)."""
    pairs = []
    task = traj.get("task", "")
    obs = "(fresh page)"
    done = bool(traj.get("done"))
    for st in traj.get("trace", []):
        tool = st.get("tool"); args = st.get("args", {}); res = st.get("result", {})
        user = f"TASK: {task}\nPAGE STATE: {obs}\nChoose ONE tool action."
        blocked = isinstance(res, dict) and res.get("blocked")
        if blocked:
            asst = json.dumps({"refused": True, "reason": res.get("reason", "blocked by governor"),
                               "instead": "choose a non-destructive action"})
            pairs.append({"messages": [{"role": "system", "content": SYS}, {"role": "user", "content": user},
                                       {"role": "assistant", "content": asst}], "kind": "refusal"})
        elif done:                                              # VTC: only successful paths become positives
            asst = json.dumps({"tool": tool, "args": args})
            pairs.append({"messages": [{"role": "system", "content": SYS}, {"role": "user", "content": user},
                                       {"role": "assistant", "content": asst}], "kind": "positive"})
        if tool in ("read_page", "get_text") and isinstance(res, dict):
            obs = (res.get("text") or json.dumps({k: res[k] for k in list(res)[:6]}))[:1500]
    if done:                                                    # teach it to finish
        user = f"TASK: {task}\nPAGE STATE: {obs}\nChoose ONE tool action."
        pairs.append({"messages": [{"role": "system", "content": SYS}, {"role": "user", "content": user},
                                   {"role": "assistant", "content": json.dumps({"done": True, "answer": traj.get("answer", "")})}],
                      "kind": "positive"})
    return pairs


def _synthetic():
    """A couple of trajectories (one successful, one with a blocked action) for the self-test."""
    return [
        {"task": "find the answer on example.com", "done": True, "answer": "The answer is 42.", "trace": [
            {"step": 0, "tool": "navigate", "args": {"url": "https://example.com"}, "result": {"ok": True}},
            {"step": 1, "tool": "read_page", "args": {}, "result": {"ok": True, "text": "the answer is 42"}},
        ]},
        {"task": "wipe the machine", "done": False, "trace": [
            {"step": 0, "tool": "eval_js", "args": {"code": "document.cookie"}, "result": {"ok": False, "blocked": True, "reason": "typed text carries script/exfil markers"}},
        ]},
    ]


def main():
    log = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get("LOCALAPPDATA", "."), "aetherbrowser-trajectories.jsonl")
    trajs = []
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try: trajs.append(json.loads(line))
                    except Exception: pass
        src = f"recorded log ({log})"
    else:
        trajs = _synthetic(); src = "SYNTHETIC self-test (no recorded log yet)"

    all_pairs = []
    for t in trajs: all_pairs.extend(to_sft(t))
    pos = [p for p in all_pairs if p["kind"] == "positive"]; ref = [p for p in all_pairs if p["kind"] == "refusal"]

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_sft.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for p in all_pairs:
            f.write(json.dumps({"messages": p["messages"], "kind": p["kind"]}) + "\n")

    print("=== build_browser_sft -- browser sessions -> verified SFT for the homemade model ===\n")
    print(f"  source: {src}")
    print(f"  trajectories: {len(trajs)}  ->  {len(all_pairs)} SFT pairs  ({len(pos)} positive, {len(ref)} refusal)")
    print(f"  wrote: {out}")
    if all_pairs:
        print("\n  example positive pair (observation -> action):")
        ex = next((p for p in all_pairs if p["kind"] == "positive"), all_pairs[0])
        print("    user:", ex["messages"][1]["content"].replace("\n", " | ")[:110])
        print("    asst:", ex["messages"][2]["content"][:110])
    print("\n  RECIPE -- LoRA-train the homemade model on this, then serve via Ollama for the middle-man:")
    print("    1. LoRA/QLoRA on your Qwen-1.5B coding agent (fits the 1660Ti) or via HF Jobs on browser_sft.jsonl")
    print("    2. export GGUF -> `ollama create issac-browser -f Modelfile`")
    print("    3. middleman: runTask({model:'issac-browser', callTool}) -> it browses; recorder logs new sessions")
    print("    4. rebuild SFT from the new sessions -> retrain. The loop closes; the browser is free for the model.")
    ok = len(pos) >= 1 and (len(ref) >= 1 if src.startswith("SYNTHETIC") else True)
    print("\n  self-test:", "PASS" if ok else "check output")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
