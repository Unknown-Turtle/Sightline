// Live mode client. Connects when the page URL hash contains `live`:
//   #live                        ws://localhost:8787/ws (python -m live.local)
//   #live=ws://host:8787/ws      that WebSocket directly
//   #live=https://<func>.azurewebsites.net   GET <base>/api/negotiate, then the Web PubSub URL it returns
// Messages follow live/CONTRACT.md: { kind: "snapshot" | "insight" | "rating" | "event", match_id, data }.
// Unknown kinds are ignored. Reconnects with backoff and negotiates again each time (tokens expire).

export type LiveKind = 'snapshot' | 'insight' | 'rating' | 'event';

export interface LiveMessage<T = any> {
  kind: LiveKind | string;
  match_id?: string;
  data: T;
}

type Handler = (data: any, msg: LiveMessage) => void;

const DEFAULT_WS = 'ws://localhost:8787/ws';

/** Returns the live target from the hash, or null when live mode is off. */
export function liveTarget(hash: string = location.hash): string | null {
  for (const part of hash.replace(/^#/, '').split('&')) {
    if (part === 'live') return DEFAULT_WS;
    if (part.startsWith('live=')) return decodeURIComponent(part.slice(5)) || DEFAULT_WS;
  }
  return null;
}

async function resolveUrl(target: string, matchId?: string): Promise<string> {
  if (/^wss?:\/\//.test(target)) return target;
  const base = target.replace(/\/+$/, '');
  const q = matchId ? `?match_id=${encodeURIComponent(matchId)}` : '';
  const res = await fetch(`${base}/api/negotiate${q}`);
  if (!res.ok) throw new Error(`negotiate failed: ${res.status}`);
  const body = await res.json();
  return body.url;
}

export class LiveClient {
  connected = false;
  readonly target: string;
  private ws: WebSocket | null = null;
  private handlers: Record<string, Handler[]> = {};
  private stateHandlers: ((connected: boolean) => void)[] = [];
  private retry = 0;
  private stopped = false;

  constructor(target: string, private matchId?: string) {
    this.target = target;
  }

  onSnapshot(fn: Handler): this { return this.on('snapshot', fn); }
  onInsight(fn: Handler): this { return this.on('insight', fn); }
  onRating(fn: Handler): this { return this.on('rating', fn); }
  onEvent(fn: Handler): this { return this.on('event', fn); }
  onConnection(fn: (connected: boolean) => void): this { this.stateHandlers.push(fn); return this; }

  on(kind: string, fn: Handler): this {
    (this.handlers[kind] ??= []).push(fn);
    return this;
  }

  /** Base URL for the claims API next to this live source (local server or Functions app). */
  get apiBase(): string {
    if (!/^wss?:\/\//.test(this.target)) return this.target.replace(/\/+$/, '');
    const u = new URL(this.target);
    return `${u.protocol === 'wss:' ? 'https:' : 'http:'}//${u.host}`;
  }

  async start(): Promise<this> {
    this.stopped = false;
    try {
      const url = await resolveUrl(this.target, this.matchId);
      if (this.stopped) return this;
      const ws = new WebSocket(url);
      this.ws = ws;
      ws.onopen = () => { this.retry = 0; this.setConnected(true); };
      ws.onmessage = (ev) => this.dispatch(ev.data);
      ws.onclose = () => { this.setConnected(false); this.scheduleReconnect(); };
      ws.onerror = () => ws.close();
    } catch (err) {
      console.warn('[live]', err);
      this.scheduleReconnect();
    }
    return this;
  }

  stop(): void {
    this.stopped = true;
    this.ws?.close();
    this.ws = null;
  }

  private dispatch(raw: unknown): void {
    if (typeof raw !== 'string') return;
    let msg: LiveMessage;
    try { msg = JSON.parse(raw); } catch { return; }
    if (!msg || typeof msg.kind !== 'string') return;
    if (this.matchId && msg.match_id && msg.match_id !== this.matchId) return;
    for (const fn of this.handlers[msg.kind] ?? []) {
      try { fn(msg.data, msg); } catch (err) { console.error('[live] handler failed', err); }
    }
  }

  private setConnected(v: boolean): void {
    if (this.connected === v) return;
    this.connected = v;
    for (const fn of this.stateHandlers) fn(v);
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const delay = Math.min(10000, 500 * 2 ** this.retry++);
    setTimeout(() => { if (!this.stopped) this.start(); }, delay);
  }
}

/** Starts a client when the URL asks for live mode; returns null otherwise. */
export function startLive(matchId?: string): LiveClient | null {
  const target = liveTarget();
  if (!target) return null;
  const client = new LiveClient(target, matchId);
  client.start();
  return client;
}
