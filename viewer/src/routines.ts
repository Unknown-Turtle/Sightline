// Rehearsed patterns: routines detected from events (routines.json), shown as Tactical points
// and in the Patterns panel. Each attempt is one card in the evidence reel.

import { clockAt, type Ev } from "./data";
import type { Extras } from "./extras";
import { asPoint, ensureContainer, esc, loadData } from "./extras";
import type { Point } from "./points";

interface Attempt { t: number; event_ids: string[]; outcome: string }
interface Pattern {
  id: string;
  team: string;
  label: string;
  trigger?: string;
  attempts: Attempt[];
  shots_from?: number;
  evaluation?: { precision: number | null; recall: number | null; against?: string };
}

/** A pattern needs this many attempts by now before it becomes a point. */
const MIN_ATTEMPTS = 3;

const TRIGGER: Record<string, string> = {
  goal_kick: "goal kick routine",
  keeper: "build-up from the keeper",
  regain_own_third: "move after winning the ball back",
  corner: "corner routine",
  free_kick: "free kick routine",
  throw_in: "throw-in routine",
};

export class Routines {
  private patterns: Pattern[] = [];
  private loaded = false;
  private body: HTMLElement;
  private lastSig = "";

  constructor(private x: Extras) {
    const panel = ensureContainer("panel-patterns", "Rehearsed patterns", document.getElementById("panel-claims"));
    this.body = document.createElement("div");
    this.body.className = "x-card";
    panel.appendChild(this.body);
    this.body.innerHTML = `<h2>Rehearsed patterns</h2><p class="x-sub">Loading patterns.</p>`;
    void this.load();
  }

  private async load(): Promise<void> {
    const got = await loadData<{ patterns: Pattern[] }>("routines");
    this.patterns = (got?.data.patterns ?? []).filter((p) => Array.isArray(p.attempts));
    this.loaded = true;
    this.lastSig = "";
    this.render(this.x.host.liveT());
    this.x.host.refresh();
  }

  /** Attempts so far, with their first event (the card the reel shows). */
  private sofar(p: Pattern, t: number): { a: Attempt; ev: Ev }[] {
    const out: { a: Attempt; ev: Ev }[] = [];
    for (const a of p.attempts) {
      if (a.t > t) continue;
      const ev = this.x.ev(a.event_ids[0]);
      if (ev) out.push({ a, ev });
    }
    return out;
  }

  /** One point per pattern seen often enough by time t. */
  points(t: number): Point[] {
    const { meta } = this.x.host;
    const out: Point[] = [];
    for (const p of this.patterns) {
      const seen = this.sofar(p, t);
      if (seen.length < MIN_ATTEMPTS) continue;
      const shots = seen.filter((s) => s.a.outcome === "shot").length;
      const team = meta.teams.find((x) => x.id === p.team)?.name ?? p.team;
      const what = TRIGGER[p.trigger ?? ""] ?? "routine";
      const n = seen.length;
      const led = `${shots} led to ${shots === 1 ? "a shot" : "shots"}`;
      const casual = `${team} have run the same ${what} ${n} times, ${led}`;
      const tactical = `${team}: ${p.label}, ${n} attempts, ${shots} ended in a shot, ${seen.filter((s) => s.a.outcome === "lost").length} lost`;
      out.push(
        asPoint({
          id: `routine-${p.id}`, kind: "routine", team: p.team, subject: null,
          claim: { casual, tactical, commentator: casual } as never,
          stat: `${n} runs, ${shots} shot${shots === 1 ? "" : "s"}`,
          forEv: seen.filter((s) => s.a.outcome !== "lost").map((s) => s.ev),
          againstEv: seen.filter((s) => s.a.outcome === "lost").map((s) => s.ev),
          checked: seen.reduce((k, s) => k + s.a.event_ids.length, 0),
          strength: n * 0.4 + shots,
        }),
      );
    }
    return out;
  }

  tick(t: number): void {
    const sig = this.patterns.map((p) => this.sofar(p, t).length).join(",");
    if (sig === this.lastSig) return;
    this.lastSig = sig;
    this.render(t);
  }

  private render(t: number): void {
    if (!this.loaded) return;
    const pts = this.points(t);
    if (!this.patterns.length) {
      this.body.innerHTML = `<h2>Rehearsed patterns</h2><p class="x-sub">No pattern data for this match yet.</p>`;
      return;
    }
    const items = pts
      .map((pt) => {
        const p = this.patterns.find((q) => `routine-${q.id}` === pt.id)!;
        const ev = p.evaluation;
        const evalTxt = ev && ev.precision !== null && ev.recall !== null
          ? ` Detector checked against the hidden playbook: precision ${Math.round(ev.precision * 100)}%, recall ${Math.round(ev.recall * 100)}%.`
          : "";
        const colour = this.x.host.meta.teams.find((x) => x.id === p.team)?.colour ?? "#999";
        return `<li><button class="x-pattern" data-id="${esc(pt.id)}">
          <span class="claim">${esc(pt.claim.casual)}</span>
          <span class="meta"><i class="x-dot" style="--c:${esc(colour)}"></i> ${esc(p.label)}.${esc(evalTxt)}</span></button></li>`;
      })
      .join("");
    this.body.innerHTML = `<h2>Rehearsed patterns</h2>
      <p class="x-sub">Moves a team has repeated, found from the events alone, as of ${clockAt(this.x.host.meta, t).text}. Select one to watch every attempt.</p>
      ${items ? `<ol class="x-patterns">${items}</ol>` : `<p class="empty">No pattern has repeated ${MIN_ATTEMPTS} times yet.</p>`}`;
    this.body.querySelectorAll<HTMLButtonElement>(".x-pattern").forEach((b) =>
      b.addEventListener("click", () => {
        const pt = this.points(this.x.host.liveT()).find((q) => q.id === b.dataset.id);
        if (pt) this.x.host.selectPoint(pt);
      }),
    );
  }
}
