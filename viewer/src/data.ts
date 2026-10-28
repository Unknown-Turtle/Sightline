// Loading and sampling the packed match (see tools/pack_match.py).

export interface PlayerMeta { id: string; name: string; number: number; pos: string; team: string }
export interface TeamMeta { id: string; name: string; formation: string; colour: string; xi: string[]; bench: string[] }
export interface MomentumPoint {
  t: number;
  m: Record<string, number>;
  xg: Record<string, number>;
  /** per-team stats block from the snapshot (possession, shots, xg, passes ...), when packed */
  stats?: Record<string, Record<string, number>>;
}
export interface Meta {
  match_id: string;
  competition: string;
  venue: string;
  home: string;
  away: string;
  final_score: Record<string, number>;
  context: { referee?: { name: string }; weather?: string; attendance?: number; kickoff_local?: string; matchday?: number; stakes?: string };
  attack_direction: Record<string, Record<string, number>>;
  teams: TeamMeta[];
  players: PlayerMeta[];
  tracking: { order: string[]; frames: number; hz: number; t0: number; scale: number; absent: number; stride: number };
  periods: { p: number; start: number; end: number }[];
  momentum: MomentumPoint[];
}
export interface Ev {
  id: string;
  t: number;
  clock: string;
  min: number;
  p: number;
  type: string;
  out: string | null;
  team: string;
  pl: string | null;
  s: [number, number] | null;
  e: [number, number] | null;
  dir: number;
  poss: number;
  seq: number;
  pat: string;
  up: boolean;
  bp: string | null;
  rel: string | null;
  q: string[];
  score: Record<string, number> | null;
  x: Record<string, any>;
}

declare global {
  interface Window { __SIGHTLINE_TRACKING_B64?: string }
}

export async function loadMatch(base = "data/"): Promise<{ meta: Meta; events: Ev[]; tracking: Tracking }> {
  const [meta, events] = await Promise.all([
    fetch(base + "meta.json").then((r) => r.json() as Promise<Meta>),
    fetch(base + "events.json").then((r) => r.json() as Promise<Ev[]>),
  ]);
  let buf: ArrayBuffer;
  if (window.__SIGHTLINE_TRACKING_B64) {
    const bin = atob(window.__SIGHTLINE_TRACKING_B64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    buf = bytes.buffer;
    delete window.__SIGHTLINE_TRACKING_B64;
  } else {
    buf = await fetch(base + "tracking.bin").then((r) => r.arrayBuffer());
  }
  return { meta, events, tracking: new Tracking(meta, new Int16Array(buf)) };
}

export interface Sample {
  ball: [number, number, number];
  pos: Float32Array; // x, y per player in meta order; NaN when off the pitch
  speed: Float32Array; // km/h
}

export class Tracking {
  readonly n: number;
  readonly hz: number;
  readonly t0: number;
  readonly duration: number;
  readonly count: number;
  private stride: number;
  private scale: number;
  private absent: number;

  constructor(meta: Meta, private data: Int16Array) {
    const tr = meta.tracking;
    this.n = tr.frames;
    this.hz = tr.hz;
    this.t0 = tr.t0;
    this.stride = tr.stride;
    this.scale = tr.scale;
    this.absent = tr.absent;
    this.count = tr.order.length;
    this.duration = (this.n - 1) / this.hz;
  }

  newSample(): Sample {
    return { ball: [52.5, 34, 0], pos: new Float32Array(this.count * 2), speed: new Float32Array(this.count) };
  }

  private v(frame: number, k: number): number {
    const f = Math.max(0, Math.min(this.n - 1, frame));
    return this.data[f * this.stride + k];
  }

  /** Fill `out` with positions at match time t (seconds), smoothed with Catmull-Rom. */
  sample(t: number, out: Sample): void {
    const f = Math.max(0, Math.min(this.n - 1.0001, (t - this.t0) * this.hz));
    const i = Math.floor(f);
    const u = f - i;
    const s = this.scale;
    // ball: linear, passes travel in straight lines in the data
    for (let k = 0; k < 3; k++) {
      const a = this.v(i, k), b = this.v(i + 1, k);
      out.ball[k] = (a + (b - a) * u) / s;
    }
    for (let p = 0; p < this.count; p++) {
      const kx = 3 + 2 * p, ky = kx + 1;
      const x1 = this.v(i, kx), x2 = this.v(i + 1, kx);
      if (x1 === this.absent || x2 === this.absent) {
        const xs = u < 0.5 ? x1 : x2;
        const ys = u < 0.5 ? this.v(i, ky) : this.v(i + 1, ky);
        if (xs === this.absent) {
          out.pos[2 * p] = NaN; out.pos[2 * p + 1] = NaN; out.speed[p] = 0;
        } else {
          out.pos[2 * p] = xs / s; out.pos[2 * p + 1] = ys / s; out.speed[p] = 0;
        }
        continue;
      }
      let x0 = this.v(i - 1, kx), x3 = this.v(i + 2, kx);
      let y0 = this.v(i - 1, ky), y3 = this.v(i + 2, ky);
      const y1 = this.v(i, ky), y2 = this.v(i + 1, ky);
      if (x0 === this.absent) { x0 = x1; y0 = y1; }
      if (x3 === this.absent) { x3 = x2; y3 = y2; }
      out.pos[2 * p] = cr(x0, x1, x2, x3, u) / s;
      out.pos[2 * p + 1] = cr(y0, y1, y2, y3, u) / s;
      const dx = (x2 - x1) / s, dy = (y2 - y1) / s;
      out.speed[p] = Math.hypot(dx, dy) * this.hz * 3.6;
    }
  }
}

function cr(p0: number, p1: number, p2: number, p3: number, t: number): number {
  const t2 = t * t, t3 = t2 * t;
  return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
}

/** Broadcast clock for a match time, using the period boundaries. */
export function clockAt(meta: Meta, t: number): { text: string; period: number } {
  const p2 = meta.periods[1];
  const inSecond = p2 && t >= p2.start;
  const base = inSecond ? 45 * 60 : 0;
  const start = inSecond ? p2.start : meta.periods[0].start;
  const into = Math.max(0, t - start);
  if (into <= 45 * 60) {
    const total = base + into;
    return { text: `${pad(Math.floor(total / 60))}:${pad(Math.floor(total % 60))}`, period: inSecond ? 2 : 1 };
  }
  const extra = into - 45 * 60;
  return { text: `${(base + 45 * 60) / 60}+${Math.floor(extra / 60) + 1}'`, period: inSecond ? 2 : 1 };
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

/** Team-relative x (own goal at 0) for an event location. */
export function relX(ev: Ev, x: number): number {
  return ev.dir === 1 ? x : 105 - x;
}
