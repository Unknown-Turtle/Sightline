// Match ratings: chips on player tags and a panel listing both teams.
// Selecting a player opens the shared evidence reel with the events that moved the rating.

import type { Extras } from "./extras";
import { asPoint, ensureContainer, esc, loadData } from "./extras";

export interface RatingReason { event_id: string; label: string; effect: number }
export interface RatingEntry { t: number; rating: number; delta: number; reasons: RatingReason[] }
interface RatingsFile { every_s: number; formula?: string; players: Record<string, RatingEntry[]> }

/** Treat moves smaller than this as no move. */
const MOVE = 0.05;

export class Ratings {
  private data: RatingsFile | null = null;
  private sample = false;
  private panel: HTMLElement;
  private body: HTMLElement;
  private lastStep = -2;
  private selected: string | null = null;

  constructor(private x: Extras) {
    this.panel = ensureContainer("panel-ratings", "Match ratings", document.getElementById("reel-wrap"));
    this.body = document.createElement("div");
    this.body.className = "x-card";
    this.panel.appendChild(this.body);
    this.body.innerHTML = `<h2>Match ratings</h2><p class="x-sub">Loading ratings.</p>`;
    void this.load();
  }

  private async load(): Promise<void> {
    const got = await loadData<RatingsFile>("ratings");
    if (got && got.data && got.data.players) {
      this.data = got.data;
      this.sample = got.sample;
    }
    this.lastStep = -2;
    this.render(this.x.host.liveT());
  }

  /** Live mode: merge one rating message into the series. */
  push(pid: string, entry: RatingEntry): void {
    if (!this.data) this.data = { every_s: 60, players: {} };
    const list = (this.data.players[pid] ??= []);
    const i = list.findIndex((e) => e.t >= entry.t);
    if (i === -1) list.push(entry);
    else if (list[i].t === entry.t) list[i] = entry;
    else list.splice(i, 0, entry);
    this.lastStep = -2;
  }

  get ready(): boolean {
    return !!this.data;
  }

  at(pid: string, t: number): RatingEntry | null {
    const list = this.data?.players[pid];
    if (!list || !list.length || list[0].t > t) return null;
    let lo = 0, hi = list.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (list[m].t <= t) lo = m + 1; else hi = m; }
    return list[lo - 1];
  }

  /** Html for the chip inside a player tag. */
  chip(pid: string, t: number): string {
    const r = this.at(pid, t);
    if (!r) return "";
    const fresh = t - r.t < (this.data?.every_s ?? 60);
    const arrow = fresh && r.delta >= MOVE ? `<span class="up" aria-label="up">▲</span>` : fresh && r.delta <= -MOVE ? `<span class="down" aria-label="down">▼</span>` : "";
    return `<span class="x-rate">${r.rating.toFixed(1)}${arrow}</span>`;
  }

  tick(t: number): void {
    const step = Math.floor(t / (this.data?.every_s ?? 60));
    if (step === this.lastStep) return;
    this.lastStep = step;
    this.render(t);
  }

  private render(t: number): void {
    const { meta } = this.x.host;
    if (!this.data) {
      this.body.innerHTML = `<h2>Match ratings</h2><p class="x-sub">Ratings are not available for this match yet.</p>`;
      return;
    }
    const cols = meta.teams
      .map((team) => {
        const rows = meta.players
          .filter((p) => p.team === team.id)
          .map((p) => ({ p, r: this.at(p.id, t) }))
          .filter((x) => x.r)
          .sort((a, b) => b.r!.rating - a.r!.rating);
        if (!rows.length) return "";
        const items = rows
          .map(({ p, r }) => {
            const recent = t - r!.t < this.data!.every_s;
            const d = recent ? r!.delta : 0;
            const cls = d >= MOVE ? "up" : d <= -MOVE ? "down" : "";
            const dTxt = cls ? `${d > 0 ? "▲ +" : "▼ "}${d.toFixed(1)}` : "";
            return `<li><button class="x-row${this.selected === p.id ? " on" : ""}" data-pid="${esc(p.id)}" aria-label="${esc(`${p.name}, rating ${r!.rating.toFixed(1)}`)}">
              <span class="n">${p.number}</span><span class="nm">${esc(p.name)}</span><span class="r">${r!.rating.toFixed(1)}</span><span class="d ${cls}">${dTxt}</span></button></li>`;
          })
          .join("");
        return `<section><h3><i style="--c:${esc(team.colour)}"></i>${esc(team.name)}</h3><ol>${items}</ol></section>`;
      })
      .join("");
    const note = this.sample ? " Showing the bundled sample ratings." : "";
    this.body.innerHTML = `<h2>Match ratings</h2>
      <p class="x-sub">Out of 10, updated every minute from logged events. Select a player to see why their rating moved.${note}</p>
      <div class="x-ratings">${cols || `<p class="empty">No ratings yet. They start once players have touched the ball.</p>`}</div>`;
    this.body.querySelectorAll<HTMLButtonElement>(".x-row").forEach((b) => b.addEventListener("click", () => this.open(b.dataset.pid!)));
  }

  /** Open the reasons behind a player's rating in the evidence reel. */
  open(pid: string): void {
    const t = this.x.host.liveT();
    const r = this.at(pid, t);
    if (!r || !this.data) return;
    this.selected = pid;
    this.body.querySelectorAll(".x-row").forEach((el) => el.classList.toggle("on", (el as HTMLElement).dataset.pid === pid));
    const up: string[] = [], down: string[] = [];
    for (const e of this.data.players[pid] ?? []) {
      if (e.t > t) break;
      for (const why of e.reasons ?? []) (why.effect >= 0 ? up : down).push(why.event_id);
    }
    const p = this.x.host.meta.players.find((q) => q.id === pid)!;
    const forEv = this.x.evs(up).reverse(), againstEv = this.x.evs(down).reverse();
    const move = r.delta ? `, ${r.delta > 0 ? "up" : "down"} ${Math.abs(r.delta).toFixed(1)} in the last minute` : "";
    const claim = `${p.name} is rated ${r.rating.toFixed(1)}${move}`;
    this.x.host.selectPoint(
      asPoint({
        id: `rating-${pid}`, kind: "rating", team: p.team, subject: pid,
        claim: { casual: claim, tactical: claim, commentator: claim } as never,
        stat: r.rating.toFixed(1), forEv, againstEv, checked: forEv.length + againstEv.length, strength: 0,
      }),
    );
    document.getElementById("reel-wrap")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
  }
}
