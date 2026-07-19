// welcome.js — first-run onboarding: live backend health + copy-command.
const $ = (id) => document.getElementById(id);

async function checkBackend() {
  const s = $('status');
  try {
    const r = await fetch('http://127.0.0.1:8002/health', { cache: 'no-store' });
    if (!r.ok) throw new Error('bad status');
    const j = await r.json();
    const agents = (j.agents && j.agents.length) || 0;
    const providers = (j.providers && j.providers.length) || 0;
    s.innerHTML =
      '<div class="ok">● Backend connected</div>' +
      '<div class="dim">status ' + (j.status || 'ok') + ' · agents ' + agents +
      ' · providers ' + providers + ' · version ' + (j.version || '?') + '</div>' +
      '<p style="margin:8px 0 0">You’re set — click the AetherBrowser icon in your toolbar to open the side panel.</p>';
  } catch (e) {
    s.innerHTML =
      '<div class="warn">○ Backend not running yet</div>' +
      '<div class="dim">Run the command below; this turns green automatically once it’s up.</div>';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const btn = $('copy');
  if (btn) btn.addEventListener('click', () => {
    navigator.clipboard.writeText($('cmd').textContent).then(() => {
      btn.textContent = 'Copied';
      setTimeout(() => (btn.textContent = 'Copy'), 1500);
    });
  });
  checkBackend();
  setInterval(checkBackend, 4000);
});
