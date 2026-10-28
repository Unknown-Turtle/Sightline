// Extras hub: personalisation and the ratings, claims and patterns panels.
// main.ts talks to this file only, through the small [extras] hook blocks.

/// <reference types="vite/client" />

import "./extras.css";
import type { Ev, Meta, Tracking } from "./data";
import type { Point } from "./points";
import type { Stage } from "./stage";
import { Personal } from "./personal";
import { Ratings } from "./ratings";
import { Claims } from "./claims";
import { Routines } from "./routines";

export interface Host {
  meta: Meta;
  events: Ev[];
  tracking: Tracking;
  stage: Stage;
  /** where the match is (not the replay head) */
  liveT(): number;
  lens(): string;
  /** open a point in the shared evidence reel */
  selectPoint(p: Point): void;
  /** rebuild the points rail */
  refresh(): void;
  /** the insights file the rail reads (English unless swapped for a translation) */
  getInsights(): unknown;
  setInsights(file: unknown): void;
}

/** Point kinds added by extras; the rail treats them like any other point. */
export type ExtraKind = "routine" | "rating" | "claim";

export function asPoint(p: Omit<Point, "kind"> & { kind: Point["kind"] | ExtraKind }): Point {
  return p as Point;
}

/** Find (or create, when the app shell has not built it) a container by id. */
export function ensureContainer(id: string, title: string, after?: Element | null): HTMLElement {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement("section");
    el.id = id;
    el.className = "x-panel x-own";
    el.setAttribute("aria-label", title);
    const app = document.getElementById("app")!;
    if (after && after.parentElement) after.insertAdjacentElement("afterend", el);
    else app.appendChild(el);
  }
  el.querySelectorAll(":scope > .placeholder").forEach((x) => x.remove());
  return el;
}

export function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

/** Fetch JSON from data/, trying the real file first and then its .sample fixture. */
export async function loadData<T>(name: string): Promise<{ data: T; sample: boolean } | null> {
  for (const [file, sample] of [[`${name}.json`, false], [`${name}.sample.json`, true]] as const) {
    try {
      const r = await fetch(`data/${file}`);
      if (!r.ok || !(r.headers.get("content-type") ?? "").includes("json")) continue;
      return { data: (await r.json()) as T, sample };
    } catch {
      /* try the next one */
    }
  }
  return null;
}

export class Extras {
  readonly personal: Personal;
  readonly ratings: Ratings;
  readonly claims: Claims;
  readonly routines: Routines;
  private lastLens = "";
  private byId = new Map<string, Ev>();

  constructor(readonly host: Host) {
    for (const e of host.events) this.byId.set(e.id, e);
    this.personal = new Personal(this);
    this.ratings = new Ratings(this);
    this.claims = new Claims(this);
    this.routines = new Routines(this);
    void this.startLive();
  }

  // ------------------------------------------------------------ live mode
  /** With #live in the URL and src/live.ts present (agent E), feed live ratings, insights and
   *  snapshots into the extras. The glob is empty when live.ts is missing, so this is a no-op. */
  private async startLive(): Promise<void> {
    const load = import.meta.glob("./live.ts")["./live.ts"];
    if (!load || !/(^#|&)live(=|&|$)/.test(location.hash)) return;
    try {
      const mod = (await load()) as { startLive?: (matchId?: string) => LiveLike | null };
      const client = mod.startLive?.(this.host.meta.match_id);
      if (!client) return;
      client.onRating?.((d: any) => {
        if (d && typeof d.player === "string" && typeof d.t === "number") this.ratings.push(d.player, d);
      });
      client.onInsight?.((d: any) => {
        if (d && typeof d.id === "string" && typeof d.t === "number") this.personal.addInsight(d);
      });
      client.onSnapshot?.((d: any) => {
        if (d && d.teams) this.personal.snapshot = d;
      });
      if (client.apiBase) this.claims.apiBase = client.apiBase;
    } catch (err) {
      console.warn("[extras] live mode unavailable", err);
    }
  }

  ev(id: string): Ev | undefined {
    return this.byId.get(id);
  }

  evs(ids: string[]): Ev[] {
    return ids.map((id) => this.byId.get(id)).filter((e): e is Ev => !!e).sort((a, b) => a.t - b.t);
  }

  // ------------------------------------------------------------ main hooks
  /** Called every frame. */
  tick(): void {
    const t = this.host.liveT();
    const pf = this.personal.player;
    if (pf) this.host.stage.focus = pf;
    this.host.stage.bias = pf;
    this.personal.tick(t);
    this.ratings.tick(t);
    this.routines.tick(t);
    const lens = this.host.lens();
    if (lens !== this.lastLens) {
      this.lastLens = lens;
      this.claims.render();
    }
  }

  /** Reorder, filter and extend the detected points. */
  points(pts: Point[], lens: string): Point[] {
    const t = this.host.liveT();
    const all = lens === "tactical" ? [...pts, ...this.routines.points(t)] : pts;
    return this.personal.arrange(all, lens, t);
  }

  /** Extra html after a player tag (rating chip). */
  tagChip(pid: string, lens: string): string {
    if (!this.ratings.ready || (lens !== "tactical" && pid !== this.personal.player)) return "";
    return this.ratings.chip(pid, this.host.liveT());
  }

  /** Small badge on a point card (your club, pattern). */
  badge(p: { team: string }): string {
    return this.personal.badge(p);
  }
}

interface LiveLike {
  apiBase?: string;
  onRating?(fn: (d: any) => void): unknown;
  onInsight?(fn: (d: any) => void): unknown;
  onSnapshot?(fn: (d: any) => void): unknown;
}

export function mountExtras(host: Host): Extras {
  return new Extras(host);
}
