/**
 * @file ws-client.js
 * @module extension/lib/ws-client
 *
 * WebSocket client with exponential backoff reconnection.
 * Includes:
 * - reconnect timer de-duplication
 * - outbound queue while disconnected
 * - bounded inbound buffering for burst traffic
 */

const DEFAULT_URL = 'ws://127.0.0.1:8002/ws';
const MAX_BACKOFF_MS = 30_000;
const DEFAULT_MAX_OUTBOX = 256;
const DEFAULT_MAX_INBOUND = 512;
const DEFAULT_INBOUND_BATCH = 32;

export class WsClient {
  constructor(opts) {
    this.url = opts.url || DEFAULT_URL;
    this.onMessage = opts.onMessage;
    this.onConnectionChange = opts.onConnectionChange || (() => {});
    this.onDrop = opts.onDrop || (() => {});
    this.wsFactory = opts.wsFactory || ((url) => new WebSocket(url));
    this.maxOutbox = Number.isFinite(opts.maxOutbox) ? opts.maxOutbox : DEFAULT_MAX_OUTBOX;
    this.maxInbound = Number.isFinite(opts.maxInbound) ? opts.maxInbound : DEFAULT_MAX_INBOUND;
    this.inboundBatchSize = Number.isFinite(opts.inboundBatchSize)
      ? opts.inboundBatchSize
      : DEFAULT_INBOUND_BATCH;
    this._ws = null;
    this._connected = false;
    this._backoff = 1000;
    this._seq = 0;
    this._shouldReconnect = true;
    this._reconnectTimer = null;
    this._outbox = [];
    this._inbound = [];
    this._inboundDrainScheduled = false;
  }

  connect() {
    this._shouldReconnect = true;
    if (this._ws || this._reconnectTimer) return;
    this._tryConnect();
  }

  _tryConnect() {
    if (this._ws || !this._shouldReconnect) return;
    try {
      this._ws = this.wsFactory(this.url);
    } catch {
      this._ws = null;
      this._scheduleReconnect();
      return;
    }

    this._ws.onopen = () => {
      this._connected = true;
      this._backoff = 1000;
      this.onConnectionChange(true);
      this._flushOutbox();
    };

    this._ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this._enqueueInbound(msg);
      } catch { /* ignore malformed */ }
    };

    this._ws.onclose = () => {
      this._connected = false;
      this._ws = null;
      this.onConnectionChange(false);
      if (this._shouldReconnect) {
        this._scheduleReconnect();
      }
    };

    this._ws.onerror = () => {};
  }

  _scheduleReconnect() {
    if (!this._shouldReconnect || this._reconnectTimer) return;
    const jitter = Math.random() * 500;
    const delayMs = this._backoff + jitter;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this._tryConnect();
    }, delayMs);
    this._backoff = Math.min(this._backoff * 2, MAX_BACKOFF_MS);
  }

  _enqueueInbound(msg) {
    if (this._inbound.length >= this.maxInbound) {
      this._inbound.shift();
      this.onDrop('inbound', 1);
    }
    this._inbound.push(msg);
    this._scheduleInboundDrain();
  }

  _scheduleInboundDrain() {
    if (this._inboundDrainScheduled) return;
    this._inboundDrainScheduled = true;
    setTimeout(() => this._drainInbound(), 0);
  }

  _drainInbound() {
    this._inboundDrainScheduled = false;
    let remaining = this.inboundBatchSize;
    while (remaining > 0 && this._inbound.length > 0) {
      const msg = this._inbound.shift();
      this.onMessage(msg);
      remaining -= 1;
    }
    if (this._inbound.length > 0) {
      this._scheduleInboundDrain();
    }
  }

  _flushOutbox() {
    if (!this._connected || !this._ws) return;
    while (this._outbox.length > 0) {
      const item = this._outbox.shift();
      try {
        this._ws.send(item);
      } catch {
        this._outbox.unshift(item);
        try {
          this._ws.close();
        } catch {
          // ignore close failures
        }
        break;
      }
    }
  }

  send(type, payload = {}) {
    this._seq++;
    const msg = {
      type,
      agent: 'user',
      payload,
      ts: new Date().toISOString(),
      seq: this._seq,
    };
    const encoded = JSON.stringify(msg);
    if (!this._connected || !this._ws) {
      if (this._outbox.length >= this.maxOutbox) {
        this._outbox.shift();
        this.onDrop('outbox', 1);
      }
      this._outbox.push(encoded);
      return true;
    }
    this._ws.send(encoded);
    return true;
  }

  sendCommand(text) { return this.send('command', { text }); }
  sendPageContext(url, title, text) { return this.send('page_context', { url, title, text }); }
  sendZoneResponse(requestSeq, decision) { return this.send('zone_response', { request_seq: requestSeq, decision }); }

  disconnect() {
    this._shouldReconnect = false;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
  }

  get connected() { return this._connected; }
}
