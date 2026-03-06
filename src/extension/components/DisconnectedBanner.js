/**
 * @file DisconnectedBanner.js
 * @module extension/components/DisconnectedBanner
 *
 * Shows when the WebSocket to the backend is down.
 * Tries Native Messaging first to start the server with one click.
 * Falls back to clipboard-copy if Native Messaging isn't installed.
 */

import { NativeHost, ClipboardFallback } from '../lib/native-host.js';

/**
 * Render the disconnected banner into a container element.
 * @param {HTMLElement} container
 * @param {object} opts
 * @param {number} [opts.port=8002]
 * @param {function(): void} [opts.onServerStarted] - called after successful start
 */
export function renderDisconnectedBanner(container, opts = {}) {
  const port = opts.port || 8002;
  const hasNative = NativeHost.isAvailable();

  container.innerHTML = `
    <div class="ab-disconnected">
      <div class="ab-disconnected__icon">&#9888;</div>
      <div class="ab-disconnected__title">Backend Disconnected</div>
      <div class="ab-disconnected__subtitle">
        AetherBrowser server isn't running at ws://localhost:${port}
      </div>
      <div class="ab-disconnected__actions">
        <button id="ab-start-btn" class="ab-btn ab-btn--primary">
          ${hasNative ? 'Start Server' : 'Copy Start Command'}
        </button>
        <button id="ab-settings-btn" class="ab-btn ab-btn--secondary">
          Change Port
        </button>
      </div>
      <div id="ab-start-status" class="ab-disconnected__status"></div>
      ${!hasNative ? `
        <div class="ab-disconnected__hint">
          For one-click start, run:<br>
          <code>python src/extension/native_messaging/install.py install</code>
        </div>
      ` : ''}
    </div>
  `;

  const startBtn = container.querySelector('#ab-start-btn');
  const statusEl = container.querySelector('#ab-start-status');

  startBtn.addEventListener('click', async () => {
    startBtn.disabled = true;
    statusEl.textContent = '';

    if (hasNative) {
      // Try Native Messaging (one-click server start)
      try {
        statusEl.textContent = 'Starting server...';
        const host = new NativeHost();
        const result = await host.startServer(port);
        host.disconnect();

        if (result.status === 'started') {
          statusEl.textContent = `Server started (PID ${result.pid})`;
          statusEl.classList.add('ab-status--success');
          if (opts.onServerStarted) {
            setTimeout(opts.onServerStarted, 500);
          }
        } else if (result.status === 'already_running') {
          statusEl.textContent = `Already running (PID ${result.pid})`;
          statusEl.classList.add('ab-status--success');
          if (opts.onServerStarted) {
            setTimeout(opts.onServerStarted, 500);
          }
        } else if (result.status === 'failed') {
          statusEl.textContent = `Failed to start: ${result.error || 'check logs'}`;
          statusEl.classList.add('ab-status--error');
        }
      } catch (err) {
        // Native messaging failed — fall back to clipboard
        statusEl.textContent = `Native host error: ${err.message}`;
        statusEl.classList.add('ab-status--error');
        await _fallbackToClipboard(startBtn, statusEl, port);
      }
    } else {
      // No native messaging — clipboard fallback
      await _fallbackToClipboard(startBtn, statusEl, port);
    }

    startBtn.disabled = false;
  });
}

async function _fallbackToClipboard(btn, statusEl, port) {
  const result = await ClipboardFallback.copyStartCommand(port);
  if (result.copied) {
    statusEl.textContent = 'Command copied to clipboard! Paste in your terminal.';
    statusEl.classList.remove('ab-status--error');
    statusEl.classList.add('ab-status--success');
  } else {
    statusEl.innerHTML =
      'Copy this command:<br><code>' + result.command + '</code>';
    statusEl.classList.remove('ab-status--error');
  }
  btn.textContent = 'Copy Start Command';
}
