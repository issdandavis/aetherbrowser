/**
 * aether_ollama_middleman.js — an OPTIONAL, headless local-model agent for AetherBrowser.
 *
 * A middle-man brain (NOT forced): a local Ollama model (Kimi K, Qwen, Llama — any pulled model) drives the
 * browser tools, which is how it gets "internet access" — its eyes and hands are the AetherBrowser page.
 * The app can always call tools directly; this just adds an autonomous local loop when you want one.
 *
 * Wiring:
 *   - in the Electron renderer/sidepanel:  callTool = (tool, args) => ipcRenderer.invoke('aether-tool', {tool, args})
 *   - headless / testing:  pass any callTool(tool, args) -> {ok, ...}  (a mock is included for a self-test)
 *
 * Model-agnostic: point `model` at 'kimi-k...', 'qwen2.5-coder:1.5b', etc. Everything is local ($0).
 */
'use strict';

const TOOLS_DOC = [
  "navigate {url}            - load a page",
  "read_page {}             - structured text + links + buttons + inputs of the current page",
  "get_text {}              - raw visible text",
  "find {text}              - locate clickable elements by text -> their x,y",
  "click {x,y} | {selector}- click a point or a CSS selector",
  "type {text}              - type into the focused element",
  "form_input {selector,value} - set a field's value",
  "key {key}                - press a key (Return, Tab, ...)",
  "scroll {dy}              - scroll by dy pixels",
  "screenshot {}            - PNG of the page (base64)",
  "console {limit} / network {limit} - recent console msgs / network requests",
].join("\n");

function systemPrompt() {
  return `You are AetherBrowser's local agent. You browse the web to accomplish the user's task by calling ONE tool at a time.
Available tools:
${TOOLS_DOC}

Rules:
- Reply with EXACTLY ONE JSON object per turn and nothing else.
- To act: {"thought":"...","tool":"<name>","args":{...}}
- When the task is complete: {"thought":"...","done":true,"answer":"<final answer for the user>"}
- Prefer read_page/find before clicking. Use navigate to reach a site. Keep going until done.`;
}

async function ollamaChat(ollama, model, messages) {
  const res = await fetch(`${ollama}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages, stream: false, options: { temperature: 0.2 } }),
  });
  if (!res.ok) throw new Error(`ollama ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return (data.message && data.message.content) || "";
}

function parseAction(text) {
  const m = text.match(/\{[\s\S]*\}/);           // first JSON object
  if (!m) return { raw: text };
  try { return JSON.parse(m[0]); } catch { return { raw: text }; }
}

/** Run the agent loop. callTool(tool,args) must return a JSON-able result. */
async function runTask({ task, callTool, model = "qwen2.5-coder:1.5b", ollama = "http://localhost:11434",
                         maxSteps = 12, log = () => {} }) {
  const messages = [{ role: "system", content: systemPrompt() }, { role: "user", content: task }];
  const trace = [];
  for (let step = 0; step < maxSteps; step++) {
    const reply = await ollamaChat(ollama, model, messages);
    messages.push({ role: "assistant", content: reply });
    const act = parseAction(reply);
    log(`step ${step}: ${act.tool || (act.done ? "DONE" : "?")}${act.thought ? "  // " + act.thought : ""}`);
    if (act.done) return { done: true, answer: act.answer, steps: step + 1, trace };
    if (!act.tool) {
      messages.push({ role: "user", content: 'Reply with ONE JSON action: {"tool":...,"args":...} or {"done":true,"answer":...}' });
      continue;
    }
    let result;
    try { result = await callTool(act.tool, act.args || {}); }
    catch (e) { result = { ok: false, error: String(e && e.message || e) }; }
    trace.push({ step, tool: act.tool, args: act.args, result });
    const shown = JSON.stringify(result).slice(0, 4000);
    messages.push({ role: "user", content: "TOOL RESULT: " + shown });
  }
  return { done: false, reason: "max steps reached", steps: maxSteps, trace };
}

// ---- self-test with a MOCK browser (no Ollama / no Electron needed): verifies the loop wiring ----
async function _selfTest() {
  let page = { url: "about:blank", text: "" };
  const mockTool = async (tool, args) => {
    if (tool === "navigate") { page = { url: args.url, text: `You are now on ${args.url}. It says: the answer is 42.` }; return { ok: true, url: page.url }; }
    if (tool === "read_page" || tool === "get_text") return { ok: true, url: page.url, text: page.text };
    return { ok: true, tool };
  };
  // a scripted "model" so the self-test needs no Ollama: navigate then finish
  const scripted = [
    '{"thought":"go to the site","tool":"navigate","args":{"url":"https://example.com"}}',
    '{"thought":"read it","tool":"read_page","args":{}}',
    '{"thought":"found it","done":true,"answer":"The answer is 42."}',
  ];
  let i = 0;
  const origFetch = global.fetch;
  global.fetch = async () => ({ ok: true, json: async () => ({ message: { content: scripted[Math.min(i++, scripted.length - 1)] } }) });
  const out = await runTask({ task: "find the answer", callTool: mockTool, model: "mock", maxSteps: 6, log: (m) => console.log("  " + m) });
  global.fetch = origFetch;
  console.log("  ->", JSON.stringify({ done: out.done, answer: out.answer, steps: out.steps }));
  console.log("  self-test:", out.done && /42/.test(out.answer || "") ? "PASS" : "FAIL");
}

module.exports = { runTask, systemPrompt, parseAction };

if (require.main === module) {
  console.log("=== aether_ollama_middleman self-test (mock browser + scripted model) ===");
  _selfTest();
}
