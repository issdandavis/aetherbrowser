/**
 * @file SharedContextPanel.js
 * @module extension/components/SharedContextPanel
 *
 * Compact sidebar panel that makes the multi-agent SHARED CONTEXT POOL visible.
 *
 * The backend (`context_pool.py`) keeps ONE process-wide pool shared by every
 * connected sidebar tab/window. This panel surfaces it for the human:
 *   - "N sidebars connected" (the live connection count),
 *   - the current shared `user_intent`,
 *   - the current page title/url every agent is looking at,
 *   - a LIVE FEED of cross-agent activity — messages that originated from
 *     ANOTHER sidebar (the backend fans `command` / `page_context` out to every
 *     OTHER client via `POOL.broadcast(msg, exclude=ws)`, so any such message
 *     ARRIVING here came from a different agent), labelled "↪ from another agent".
 *
 * Two ways it stays current:
 *   - `update(msg)` — called by the sidepanel for each incoming ws message;
 *     cross-agent broadcasts are appended to the live feed immediately.
 *   - `refresh()` / `start()` — polls `GET /context` every ~5s to repopulate the
 *     connected count, shared intent, current page, and recent findings. Uses the
 *     same backend host/port the rest of the sidepanel uses (read lazily so a
 *     settings port change is picked up automatically).
 */

const REFRESH_INTERVAL_MS = 5000;
const MAX_FEED_ITEMS = 8;
const MAX_FINDINGS = 4;

export class SharedContextPanel {
  /**
   * @param {HTMLElement} container - mount point (e.g. #shared-context).
   * @param {object} [opts]
   * @param {() => number} [opts.getPort] - resolves the backend port lazily.
   * @param {number} [opts.port] - static fallback port.
   */
  constructor(container, opts = {}) {
    this.container = container || null;
    this._getPort = typeof opts.getPort === 'function'
      ? opts.getPort
      : () => opts.port || 8002;

    this.connected = 0;
    this.intent = '';
    this.page = { title: '', url: '' };
    this.findings = [];
    this.feed = []; // cross-agent activity, newest last

    this._timer = null;
    this._render();
  }

  // ------------------------------------------------------------------
  // Live ws updates
  // ------------------------------------------------------------------
  /**
   * Called by the sidepanel for every incoming ws message. `command` and
   * `page_context` types are cross-agent broadcasts (the backend never echoes
   * our own back to us), so they drive the live feed + opportunistic intent/page.
   */
  update(msg) {
    if (!msg || typeof msg !== 'object') return;
    if (msg.type !== 'command' && msg.type !== 'page_context') return;

    const payload = (msg.payload && typeof msg.payload === 'object') ? msg.payload : {};

    if (msg.type === 'command') {
      const text = typeof payload.text === 'string' ? payload.text : '';
      if (text) this.intent = text;
      this._pushFeed(text || '(command)');
    } else {
      const title = typeof payload.title === 'string' ? payload.title : '';
      const url = typeof payload.url === 'string' ? payload.url : '';
      if (title || url) this.page = { title, url };
      this._pushFeed(`viewing ${title || url || '(page)'}`);
    }

    this._render();
  }

  // ------------------------------------------------------------------
  // Periodic /context refresh
  // ------------------------------------------------------------------
  start() {
    this.refresh().catch(() => {});
    if (this._timer) return;
    this._timer = setInterval(() => {
      this.refresh().catch(() => {});
    }, REFRESH_INTERVAL_MS);
  }

  stop() {
    if (!this._timer) return;
    clearInterval(this._timer);
    this._timer = null;
  }

  contextUrl() {
    let port = 8002;
    try {
      const resolved = Number(this._getPort());
      if (Number.isFinite(resolved) && resolved > 0) port = resolved;
    } catch { /* keep default */ }
    return `http://127.0.0.1:${port}/context`;
  }

  async refresh() {
    try {
      const response = await fetch(this.contextUrl(), { cache: 'no-store' });
      if (!response.ok) throw new Error(`context ${response.status}`);
      const data = await response.json();
      this._applyContext(data);
    } catch {
      // Backend /context unavailable — keep last-known values and the live ws
      // feed so the panel never goes blank.
    }
    this._render();
  }

  _applyContext(data) {
    if (!data || typeof data !== 'object') return;
    const ctx = (data.shared_context && typeof data.shared_context === 'object')
      ? data.shared_context
      : data;

    const connected = firstNumber(
      data.connected, data.connection_count, ctx.connected, ctx.connection_count,
    );
    if (connected !== null) this.connected = connected;

    const intent = pickString(data.user_intent, ctx.user_intent);
    if (intent !== null) this.intent = intent;

    const page = (data.page_context && typeof data.page_context === 'object')
      ? data.page_context
      : (ctx.page_context && typeof ctx.page_context === 'object' ? ctx.page_context : null);
    if (page) {
      this.page = {
        title: typeof page.title === 'string' ? page.title : '',
        url: typeof page.url === 'string' ? page.url : '',
      };
    }

    const findings = Array.isArray(data.findings)
      ? data.findings
      : (Array.isArray(ctx.findings) ? ctx.findings : null);
    if (findings) {
      this.findings = findings.slice(-MAX_FINDINGS).map(stringifyFinding).filter(Boolean);
    }
  }

  // ------------------------------------------------------------------
  // Internal helpers
  // ------------------------------------------------------------------
  _pushFeed(text) {
    this.feed.push({ text: String(text), ts: new Date() });
    if (this.feed.length > MAX_FEED_ITEMS) {
      this.feed.splice(0, this.feed.length - MAX_FEED_ITEMS);
    }
  }

  _render() {
    if (!this.container) return;
    const count = Number.isFinite(this.connected) ? this.connected : 0;
    const countLabel = `${count} sidebar${count === 1 ? '' : 's'} connected`;
    const pageLine = this._pageLine();

    const feedItems = this.feed.slice().reverse();
    const findingsRows = this.findings.length
      ? `
        <div class="ab-shared__section">
          <div class="ab-shared__section-title">Recent findings</div>
          ${this.findings.slice().reverse().map((f) => `
            <div class="ab-shared__finding">${escapeHtml(f)}</div>
          `).join('')}
        </div>`
      : '';

    this.container.innerHTML = `
      <div class="ab-shared">
        <div class="ab-shared__head">
          <span class="ab-shared__title">Shared Context</span>
          <span class="ab-shared__count">
            <span class="ab-shared__dot${count > 0 ? ' ab-shared__dot--live' : ''}"></span>
            ${escapeHtml(countLabel)}
          </span>
        </div>
        <div class="ab-shared__row">
          <span class="ab-shared__label">Intent</span>
          <span class="ab-shared__value">${escapeHtml(this.intent || '(none yet)')}</span>
        </div>
        <div class="ab-shared__row">
          <span class="ab-shared__label">Page</span>
          <span class="ab-shared__value" title="${escapeHtml(this.page.url || '')}">${escapeHtml(pageLine)}</span>
        </div>
        ${findingsRows}
        <div class="ab-shared__section">
          <div class="ab-shared__section-title">Cross-agent activity</div>
          ${feedItems.length
            ? feedItems.map((item) => `
              <div class="ab-shared__item">
                <span class="ab-shared__from">↪ from another agent</span>
                <span class="ab-shared__item-text">${escapeHtml(item.text)}</span>
              </div>
            `).join('')
            : `<div class="ab-shared__empty">No activity from other sidebars yet.</div>`}
        </div>
      </div>
    `;
  }

  _pageLine() {
    const title = this.page.title || '';
    const url = this.page.url || '';
    if (title && url) return `${title} — ${url}`;
    return title || url || '(no page)';
  }
}

// ----------------------------------------------------------------------------
// Pure helpers
// ----------------------------------------------------------------------------
function firstNumber(...values) {
  for (const value of values) {
    const num = Number(value);
    if (Number.isFinite(num) && value !== null && value !== undefined && value !== '') {
      return num;
    }
  }
  return null;
}

function pickString(...values) {
  for (const value of values) {
    if (typeof value === 'string') return value;
  }
  return null;
}

function stringifyFinding(item) {
  if (typeof item === 'string') return item;
  if (item && typeof item === 'object') {
    const label = item.text || item.label || item.summary || item.title;
    if (label) return String(label);
    try { return JSON.stringify(item); } catch { return ''; }
  }
  if (item === null || item === undefined) return '';
  return String(item);
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
