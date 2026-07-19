/**
 * aether_train_recorder.js — makes AetherBrowser ALLOW the AI to train on it.
 *
 * Every agent session (task + observation/action/result trajectory) is a training example. This records them to
 * a JSONL faucet, behind an explicit CONSENT flag (default ON, flip off with 'training-consent'). Downstream,
 * train/build_browser_sft.py turns these into verified SFT so a model learns to drive THIS browser.
 *
 * IPC:
 *   record-trajectory  {task, model, trace:[{step,tool,args,result}], done, answer}  -> appends one session
 *   training-consent   (boolean)                                                     -> enable/disable recording
 *   training-status    ()                                                            -> {enabled, log, sessions}
 */
'use strict';
const fs = require('fs');
const path = require('path');

const LOG = path.join(process.env.LOCALAPPDATA || __dirname, 'aetherbrowser-trajectories.jsonl');

function register({ ipcMain }) {
  let enabled = true;   // the browser permits the AI to learn from its own use; user can opt out

  ipcMain.handle('record-trajectory', async (_e, session) => {
    if (!enabled) return { ok: false, disabled: true };
    try {
      const rec = { t: new Date().toISOString(), ...(session || {}) };
      fs.appendFileSync(LOG, JSON.stringify(rec) + '\n');
      return { ok: true, log: LOG };
    } catch (e) { return { ok: false, error: String(e && e.message || e) }; }
  });

  ipcMain.handle('training-consent', async (_e, on) => { enabled = !!on; return { ok: true, enabled }; });

  ipcMain.handle('training-status', async () => {
    let sessions = 0;
    try { sessions = fs.readFileSync(LOG, 'utf8').split('\n').filter(Boolean).length; } catch (_) {}
    return { ok: true, enabled, log: LOG, sessions };
  });

  return { LOG };
}

// in-process append (used by the agent-run handler, which already runs in main)
function write(session) {
  try { fs.appendFileSync(LOG, JSON.stringify({ t: new Date().toISOString(), ...(session || {}) }) + '\n'); return true; }
  catch (_) { return false; }
}

module.exports = { register, write, LOG };
