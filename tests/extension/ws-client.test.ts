import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { WsClient } from '../../src/extension/lib/ws-client.js';

type MessageHandler = ((evt: { data: string }) => void) | null;
type VoidHandler = (() => void) | null;

class MockSocket {
  onopen: VoidHandler = null;
  onmessage: MessageHandler = null;
  onclose: VoidHandler = null;
  onerror: VoidHandler = null;
  sent: string[] = [];
  closed = false;

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
    if (this.onclose) this.onclose();
  }

  emitOpen(): void {
    if (this.onopen) this.onopen();
  }

  emitMessage(data: unknown): void {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(data) });
  }
}

describe('extension WsClient', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('queues outbound messages while disconnected and flushes on connect', () => {
    const ws = new MockSocket();
    const client = new WsClient({
      url: 'ws://test/ws',
      wsFactory: () => ws,
      onMessage: () => {},
      onConnectionChange: () => {},
    });

    const accepted = client.sendCommand('hello from queue');
    expect(accepted).toBe(true);
    expect(ws.sent).toHaveLength(0);

    client.connect();
    ws.emitOpen();
    expect(ws.sent).toHaveLength(1);

    const sentPayload = JSON.parse(ws.sent[0]);
    expect(sentPayload.type).toBe('command');
    expect(sentPayload.payload.text).toBe('hello from queue');
  });

  it('schedules only one reconnect timer while offline', () => {
    const wsFactory = vi.fn(() => {
      throw new Error('offline');
    });
    vi.spyOn(Math, 'random').mockReturnValue(0);

    const client = new WsClient({
      url: 'ws://offline/ws',
      wsFactory,
      onMessage: () => {},
      onConnectionChange: () => {},
    });

    client.connect();
    client.connect();
    client.connect();

    expect(wsFactory).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(999);
    expect(wsFactory).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(1);
    expect(wsFactory).toHaveBeenCalledTimes(2);
  });

  it('drains inbound messages in FIFO order during bursts', () => {
    const ws = new MockSocket();
    const received: number[] = [];
    const client = new WsClient({
      url: 'ws://test/ws',
      wsFactory: () => ws,
      inboundBatchSize: 2,
      onMessage: (msg) => received.push(msg.payload.idx),
      onConnectionChange: () => {},
    });

    client.connect();
    ws.emitOpen();

    ws.emitMessage({ type: 'chat', payload: { idx: 1 } });
    ws.emitMessage({ type: 'chat', payload: { idx: 2 } });
    ws.emitMessage({ type: 'chat', payload: { idx: 3 } });
    ws.emitMessage({ type: 'chat', payload: { idx: 4 } });
    ws.emitMessage({ type: 'chat', payload: { idx: 5 } });

    expect(received).toEqual([]);
    vi.runAllTimers();
    expect(received).toEqual([1, 2, 3, 4, 5]);
  });

  it('drops oldest queued messages when max queues are exceeded', () => {
    const drops: string[] = [];
    const ws = new MockSocket();
    const received: string[] = [];

    const client = new WsClient({
      url: 'ws://test/ws',
      wsFactory: () => ws,
      maxOutbox: 2,
      maxInbound: 2,
      inboundBatchSize: 8,
      onDrop: (kind) => drops.push(kind),
      onMessage: (msg) => received.push(msg.payload.value),
      onConnectionChange: () => {},
    });

    client.sendCommand('out-1');
    client.sendCommand('out-2');
    client.sendCommand('out-3');

    client.connect();
    ws.emitOpen();
    expect(ws.sent).toHaveLength(2);
    const outValues = ws.sent.map((s) => JSON.parse(s).payload.text);
    expect(outValues).toEqual(['out-2', 'out-3']);

    ws.emitMessage({ type: 'chat', payload: { value: 'in-1' } });
    ws.emitMessage({ type: 'chat', payload: { value: 'in-2' } });
    ws.emitMessage({ type: 'chat', payload: { value: 'in-3' } });
    vi.runAllTimers();

    expect(received).toEqual(['in-2', 'in-3']);
    expect(drops).toContain('outbox');
    expect(drops).toContain('inbound');
  });
});

