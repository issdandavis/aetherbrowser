/**
 * action_gate.js — the SCBE action-governor for AetherBrowser's sidepanel agent.
 *
 * Every action the AI sidepanel drives the browser pane with (scroll / click / type / nav) passes
 * through gate() first: classified, audited to a JSONL log, and enforced against a least-privilege
 * policy. Same principle as the measured intent-governor (loom/pokeslice, 93.6% AgentDojo): a hijacked
 * or injected agent can only do what the gate lets through.
 *
 * v1 is coarse (browser primitives are mostly benign, so the default policy ALLOWs them) — the real
 * teeth are: BLOCK typed text carrying script/exfil markers, BLOCK unrecognized events, and a full
 * audit trail. Tighten by adding classes to HIGH (require confirm) or BLOCK.
 */
const fs = require('fs');
const path = require('path');

const LOG = path.join(process.env.LOCALAPPDATA || __dirname, 'aetherbrowser-action-audit.jsonl');

const INJECT_RE = /javascript:|<script|onerror\s*=|document\.cookie|localStorage|sessionStorage|fetch\(|XMLHttpRequest|\.\.[\\/]/i;

// browser/agent event -> action class (covers the full aether_tools surface too)
function classify(eventName, payload = {}) {
  const e = String(eventName || '').toLowerCase();
  // reads / observation -- safe
  if (['move_up', 'move_down', 'move_left', 'move_right', 'back', 'forward', 'reload',
       'read_page', 'get_text', 'screenshot', 'console', 'network', 'find', 'tabs_list'].includes(e)) return 'READ';
  // pointer
  if (['primary', 'secondary', 'click', 'smart_click'].includes(e)) return 'CLICK';
  // navigation / low-consequence control
  if (['navigate', 'scroll', 'key', 'tabs_create', 'tabs_activate', 'tabs_close'].includes(e)) return 'CONTROL';
  // typed / form input -> screen for injection/exfil markers
  if (e === 'type' || e === 'form_input') {
    if (INJECT_RE.test(String(payload.text || payload.value || ''))) return 'INJECT';
    return 'TYPE';
  }
  // arbitrary JS execution -> screen the code; clean code is EVAL (allowed+audited), dirty is INJECT (blocked)
  if (e === 'eval_js') {
    if (INJECT_RE.test(String(payload.code || ''))) return 'INJECT';
    return 'EVAL';
  }
  if (!e) return 'UNKNOWN';
  return 'CONTROL';
}

// policy: benign primitives flow; injected/unknown are blocked. Add classes to HIGH to require confirm.
const HIGH = new Set([]);                    // e.g. add 'TYPE' to pause on every keystroke-batch
const BLOCK = new Set(['INJECT', 'UNKNOWN']);

function gate(eventName, payload = {}) {
  const cls = classify(eventName, payload);
  if (BLOCK.has(cls)) {
    return { decision: 'BLOCK', cls, reason: cls === 'INJECT'
      ? 'typed text carries script/exfil markers' : `unrecognized action '${eventName}'` };
  }
  if (HIGH.has(cls)) return { decision: 'CONFIRM', cls, reason: `${cls} is high-consequence` };
  return { decision: 'ALLOW', cls, reason: `${cls} within scope` };
}

function log(verdict, payload = {}) {
  try {
    const line = JSON.stringify({ t: new Date().toISOString(), decision: verdict.decision,
      cls: verdict.cls, event: payload.event, reason: verdict.reason }) + '\n';
    fs.appendFile(LOG, line, () => {});
  } catch (_) { /* never let auditing break the app */ }
  if (verdict.decision !== 'ALLOW') {
    console.log(`[action-gate] ${verdict.decision} ${verdict.cls}: ${verdict.reason}`);
  }
}

module.exports = { gate, classify, log, LOG };
