/**
 * @file native-host.js
 * @module extension/lib/native-host
 *
 * Chrome Native Messaging client for the AetherBrowser sidebar.
 * Talks to the Python native messaging host (host.py) to start/stop
 * the backend server without requiring the user to open a terminal.
 *
 * Chrome Native Messaging docs:
 *   https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging
 *
 * Usage (from background.js or sidepanel.js):
 *   import { NativeHost } from './lib/native-host.js';
 *
 *   const host = new NativeHost();
 *   const result = await host.startServer();
 *   // { status: "started", pid: 12345, port: 8002 }
 *
 *   const status = await host.status();
 *   // { status: "running", pid: 12345, port: 8002 }
 *
 *   await host.stopServer();
 *   // { status: "stopped", pid: 12345 }
 */

const HOST_NAME = 'com.scbe.aetherbrowser';
const TIMEOUT_MS = 10_000;

export class NativeHost {
  constructor() {
    this._port = null;
    this._pending = new Map(); // id -> { resolve, reject, timer }
    this._nextId = 1;
    this._connected = false;
    this._onDisconnect = null;
  }

  /**
   * Check if Native Messaging is available.
   * Returns false if the host isn't installed or Chrome doesn't support it.
   */
  static isAvailable() {
    return !!(chrome && chrome.runtime && chrome.runtime.connectNative);
  }

  /**
   * Connect to the native host. Reuses existing connection if alive.
   */
  connect() {
    if (this._port && this._connected) {
      return;
    }

    this._port = chrome.runtime.connectNative(HOST_NAME);
    this._connected = true;

    this._port.onMessage.addListener((msg) => {
      this._handleResponse(msg);
    });

    this._port.onDisconnect.addListener(() => {
      const error = chrome.runtime.lastError;
      this._connected = false;
      this._port = null;

      // Reject all pending requests
      for (const [id, entry] of this._pending) {
        clearTimeout(entry.timer);
        entry.reject(
          new Error(error?.message || 'Native host disconnected')
        );
      }
      this._pending.clear();

      if (this._onDisconnect) {
        this._onDisconnect(error?.message || 'disconnected');
      }
    });
  }

  /**
   * Set a callback for when the native host disconnects unexpectedly.
   * @param {function(string): void} callback
   */
  onDisconnect(callback) {
    this._onDisconnect = callback;
  }

  /**
   * Send a command and wait for the response.
   * @param {string} command - One of: start, stop, status, ping
   * @param {object} [params] - Additional parameters (e.g. { port: 8002 })
   * @returns {Promise<object>} Response from the native host
   */
  send(command, params = {}) {
    return new Promise((resolve, reject) => {
      if (!NativeHost.isAvailable()) {
        reject(new Error(
          'Native Messaging not available. ' +
          'Run: python src/extension/native_messaging/install.py install'
        ));
        return;
      }

      this.connect();

      const id = this._nextId++;
      const msg = { id, command, ...params };

      const timer = setTimeout(() => {
        this._pending.delete(id);
        reject(new Error(`Native host timeout (${TIMEOUT_MS}ms) for: ${command}`));
      }, TIMEOUT_MS);

      this._pending.set(id, { resolve, reject, timer });

      try {
        this._port.postMessage(msg);
      } catch (e) {
        clearTimeout(timer);
        this._pending.delete(id);
        reject(e);
      }
    });
  }

  /** @private */
  _handleResponse(msg) {
    // The host doesn't echo back an id, so resolve the oldest pending request.
    // Native messaging is sequential (one message in, one message out).
    const firstEntry = this._pending.entries().next();
    if (firstEntry.done) return;

    const [id, entry] = firstEntry.value;
    clearTimeout(entry.timer);
    this._pending.delete(id);

    if (msg.status === 'error') {
      entry.reject(new Error(msg.error || 'Unknown native host error'));
    } else {
      entry.resolve(msg);
    }
  }

  /**
   * Disconnect from the native host.
   */
  disconnect() {
    if (this._port) {
      this._port.disconnect();
      this._port = null;
      this._connected = false;
    }
  }

  // ── Convenience methods ──────────────────────────────────────────

  /** Start the AetherBrowser backend server. */
  async startServer(port = 8002) {
    return this.send('start', { port });
  }

  /** Stop the AetherBrowser backend server. */
  async stopServer() {
    return this.send('stop');
  }

  /** Check if the backend is running. */
  async status(port = 8002) {
    return this.send('status', { port });
  }

  /** Ping the native host (verify it's registered and working). */
  async ping() {
    return this.send('ping');
  }
}

/**
 * Fallback for when Native Messaging isn't installed.
 * Copies the start command to clipboard and shows instructions.
 */
export class ClipboardFallback {
  static async copyStartCommand(port = 8002) {
    const cmd = `python -m uvicorn src.aetherbrowser.serve:app --host 127.0.0.1 --port ${port}`;
    try {
      await navigator.clipboard.writeText(cmd);
      return { copied: true, command: cmd };
    } catch {
      return { copied: false, command: cmd };
    }
  }
}
