/**
 * aether_terminal_tools.js — programmatic TMUX + VIM for AetherBrowser's agent (computer-use beyond the web).
 *
 * The agent drives a real terminal via tmux (send-keys / capture-pane) and edits files in vim inside a tmux pane.
 * Every action is audited through action_gate, and destructive shell commands are BLOCKED (Issac's never-delete
 * rule) before they ever reach the shell. Requires `tmux` on PATH (WSL / MSYS2 / git-bash).
 *
 * Tools: term_new, term_send, term_read, term_list, term_kill, vim_open, vim_insert, vim_ex, vim_keys.
 */
'use strict';
const { execFileSync } = require('child_process');

// shell/editor commands that must never run on the agent's own initiative
const DESTRUCTIVE_RE = /\brm\s+-[rf]|\brm\s+-\S*[rf]|\bdd\s+if=|\bmkfs|\bformat\b|\bdel\s+\/|\brmdir\s+\/s|:\s*!\s*rm|>\s*\/dev\/sd|shutdown|reboot|\bkillall\b|\b:wqa!\s*\|/i;

function tmux(args) { return execFileSync('tmux', args, { encoding: 'utf8', timeout: 8000 }); }
function tmuxAvailable() { try { tmux(['-V']); return true; } catch { return false; } }

function register({ ipcMain, actionGate }) {
  ipcMain.handle('aether-terminal-tool', async (_event, msg) => {
    const tool = String(msg && msg.tool || '');
    const args = (msg && msg.args) || {};
    const session = String(args.session || 'aether');

    // audit + destructive screen (own governor, mirrors action_gate)
    const payload = { event: tool, session, keys: args.keys, cmd: args.cmd, file: args.file };
    let decision = 'ALLOW', reason = `${tool} within scope`;
    const risky = String(args.keys || args.cmd || '');
    if ((tool === 'term_send' || tool === 'vim_ex') && DESTRUCTIVE_RE.test(risky)) { decision = 'BLOCK'; reason = 'destructive shell/editor command'; }
    try { actionGate.log({ decision, cls: tool.startsWith('term_read') || tool === 'term_list' ? 'READ' : 'SHELL', reason }, payload); } catch (_) {}
    if (decision === 'BLOCK') return { ok: false, blocked: true, tool, reason };

    if (!tmuxAvailable()) return { ok: false, error: 'tmux not found on PATH (install via WSL / MSYS2 / git-bash)' };
    try {
      switch (tool) {
        case 'term_new': tmux(['new-session', '-d', '-s', session, '-x', '200', '-y', '50']); return { ok: true, session };
        case 'term_send':
          tmux(['send-keys', '-t', session, String(args.keys || '')]);
          if (args.enter !== false) tmux(['send-keys', '-t', session, 'Enter']);
          return { ok: true, session, sent: args.keys };
        case 'term_read': return { ok: true, session, pane: tmux(['capture-pane', '-t', session, '-p']) };
        case 'term_list': return { ok: true, sessions: tmux(['list-sessions']).trim().split('\n').filter(Boolean) };
        case 'term_kill': tmux(['kill-session', '-t', session]); return { ok: true, killed: session };
        // vim, driven inside the tmux pane
        case 'vim_open': tmux(['send-keys', '-t', session, `vim ${String(args.file || '')}`, 'Enter']); return { ok: true, opened: args.file };
        case 'vim_insert':
          tmux(['send-keys', '-t', session, 'i']);
          tmux(['send-keys', '-t', session, String(args.text || '')]);
          tmux(['send-keys', '-t', session, 'Escape']);
          return { ok: true, inserted: (args.text || '').length };
        case 'vim_ex': tmux(['send-keys', '-t', session, `:${String(args.cmd || '')}`, 'Enter']); return { ok: true, ex: args.cmd };
        case 'vim_keys': tmux(['send-keys', '-t', session, String(args.keys || '')]); return { ok: true, keys: args.keys };
        default: return { ok: false, error: 'unknown terminal tool: ' + tool };
      }
    } catch (err) {
      return { ok: false, tool, error: String(err && err.message || err) };
    }
  });
  return { tmuxAvailable, TOOLS: ['term_new', 'term_send', 'term_read', 'term_list', 'term_kill', 'vim_open', 'vim_insert', 'vim_ex', 'vim_keys'] };
}

module.exports = { register, tmuxAvailable, DESTRUCTIVE_RE };

if (require.main === module) {
  console.log('tmux available:', tmuxAvailable());
  console.log('destructive screen blocks "rm -rf /":', DESTRUCTIVE_RE.test('rm -rf /'));
  console.log('destructive screen allows "ls -la":', !DESTRUCTIVE_RE.test('ls -la'));
}
