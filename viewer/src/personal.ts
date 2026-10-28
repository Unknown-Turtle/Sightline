// Personal settings bar: favourite club, player focus, a pinned metric and language.
// Settings live in localStorage when it is available and are only a convenience.

import type { Ev } from "./data";
import type { Extras } from "./extras";
import { ensureContainer, esc, loadData } from "./extras";
import type { Point } from "./points";

const KEY = "sightline.personal.v1";

export const LANGS: Record<string, { label: string; rtl?: boolean }> = {
  en: { label: "English" },
  es: { label: "Español" },
  fr: { label: "Français" },
  pt: { label: "Português" },
  ar: { label: "العربية", rtl: true },
};

const METRICS: Record<string, { label: string; unit: string }> = {
  "": { label: "None", unit: "" },
  distance: { label: "Distance covered", unit: "km" },
  sprints: { label: "Sprints", unit: "" },
  xg: { label: "xG", unit: "" },
  passacc: { label: "Pass accuracy", unit: "%" },
  shots: { label: "Shots", unit: "" },
  defence: { label: "Defensive actions", unit: "" },
};

interface Settings { club: string; player: string; metric: string; lang: string }

interface Insights { items: { t: number }[] }

function readSettings(): Settings {
  const base: Settings = { club: "", player: "", metric: "", lang: "en" };
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...base, ...JSON.parse(raw) };
  } catch {
    /* private mode or blocked storage */
  }
  return base;
}

function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* ignore */
  }
}

export class Personal {
  private s: Settings;
  private bar: HTMLElement;
  private chip: HTMLDivElement;
  private note: HTMLElement;
  private frame: HTMLElement;
  /** the insights the app loaded on its own, in English */
  private english: unknown;
  /** latest live stats snapshot (matchgen StatsEngine shape), used for the pinned stat when present */
  snapshot: { elapsed?: number; teams: Record<string, Record<string, number>>; players?: Record<string, Record<string, number>> } | null = null;
  private lastSec = -1;
  private track: { dist: Float32Array[]; sprints: Uint16Array[] } | null = null;

  constructor(private x: Extras) {
    this.s = readSettings();
    this.english = x.host.getInsights();
    const meta = x.host.meta;
    if (this.s.player && !meta.players.some((p) => p.id === this.s.player)) this.s.player = "";
    if (this.s.club && !meta.teams.some((t) => t.id === this.s.club)) this.s.club = "";
    if (!LANGS[this.s.lang]) this.s.lang = "en";
    this.bar = ensureContainer("personal-bar", "Your settings", document.querySelector("#app > header"));
    this.bar.classList.add("x-bar");
    this.build();
    this.note = this.bar.querySelector(".x-note")!;
    this.frame = this.bar.querySelector(".x-frame")!;
    this.chip = document.createElement("div");
    this.chip.className = "x-pin";
    this.chip.hidden = true;
    this.chip.setAttribute("aria-live", "off");
    (document.getElementById("stage") ?? document.body).appendChild(this.chip);
    this.applyClub();
    if (this.s.lang !== "en") void this.loadLang();
  }

  get player(): string | null {
    return this.s.player || null;
  }

  get club(): string | null {
    return this.s.club || null;
  }

  get lang(): string {
    return this.s.lang;
  }

  // ------------------------------------------------------------------ bar
  private build(): void {
    const { meta } = this.x.host;
    const teamOpts = meta.teams.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join("");
    const playerOpts = meta.teams
      .map((t) => {
        const ps = meta.players.filter((p) => p.team === t.id).sort((a, b) => a.number - b.number);
        return `<optgroup label="${esc(t.name)}">${ps.map((p) => `<option value="${esc(p.id)}">${p.number} ${esc(p.name)}</option>`).join("")}</optgroup>`;
      })
      .join("");
    const metricOpts = Object.entries(METRICS).map(([k, m]) => `<option value="${k}">${esc(m.label)}</option>`).join("");
    const langOpts = Object.entries(LANGS).map(([k, l]) => `<option value="${k}" lang="${k}">${esc(l.label)}</option>`).join("");
    const root = document.createElement("div");
    root.className = "x-bar-inner";
    root.innerHTML = `
      <label class="x-field"><span>Your club</span><select data-k="club"><option value="">No favourite</option>${teamOpts}</select></label>
      <label class="x-field"><span>Player focus</span><select data-k="player"><option value="">Everyone</option>${playerOpts}</select></label>
      <label class="x-field"><span>Pinned stat</span><select data-k="metric">${metricOpts}</select></label>
      <label class="x-field"><span>Language</span><select data-k="lang">${langOpts}</select></label>
      <p class="x-frame" aria-live="polite"></p>
      <p class="x-note" aria-live="polite"></p>`;
    this.bar.appendChild(root);
    root.querySelectorAll<HTMLSelectElement>("select").forEach((sel) => {
      const k = sel.dataset.k as keyof Settings;
      sel.value = this.s[k];
      sel.addEventListener("change", () => {
        this.s[k] = sel.value;
        saveSettings(this.s);
        if (k === "lang") void this.loadLang();
        if (k === "club") this.applyClub();
        if (k === "metric" || k === "player") this.lastSec = -1;
        this.x.host.refresh();
      });
    });
  }

  private applyClub(): void {
    const { meta } = this.x.host;
    const homeEl = document.querySelector(".scorebug .team.home");
    const awayEl = document.querySelector(".scorebug .team.away");
    homeEl?.classList.toggle("x-fav", this.s.club === meta.home);
    awayEl?.classList.toggle("x-fav", this.s.club === meta.away);
    this.lastSec = -1;
  }

  // ------------------------------------------------------------- language
  /** Swap the app's insights for insights.<lang>.json; English keeps whatever the app loaded. */
  private async loadLang(): Promise<void> {
    const lang = this.s.lang;
    const html = document.documentElement;
    html.lang = lang;
    html.dir = LANGS[lang]?.rtl ? "rtl" : "ltr";
    let file: unknown = this.english;
    let note = "";
    if (lang !== "en") {
      const got = await loadData<Insights>(`insights.${lang}`);
      if (got && Array.isArray(got.data.items) && got.data.items.length) {
        got.data.items = [...got.data.items].sort((a, b) => a.t - b.t);
        file = got.data;
      } else note = `${LANGS[lang].label}: no translation for this match yet, showing English.`;
    }
    if (lang !== this.s.lang) return; // changed again while loading
    this.x.host.setInsights(file);
    this.note.textContent = note;
    this.x.host.refresh();
  }

  // --------------------------------------------------------------- points
  /** Player focus keeps only points involving them; favourite club goes first. */
  arrange(pts: Point[], _lens: string, _t: number): Point[] {
    let out = pts;
    const pf = this.s.player;
    if (pf) {
      out = out
        .filter((p) => p.subject === pf || p.forEv.some((e) => involves(e, pf)) || p.againstEv.some((e) => involves(e, pf)))
        .map((p) => (p.subject === pf ? p : { ...p, forEv: p.forEv.filter((e) => involves(e, pf)), againstEv: p.againstEv.filter((e) => involves(e, pf)) }));
    }
    const club = this.s.club;
    if (club) out = [...out].sort((a, b) => Number(b.team === club) - Number(a.team === club));
    return out;
  }

  badge(p: { team: string }): string {
    if (this.s.club && p.team === this.s.club) return `<span class="x-badge">Your club</span>`;
    return "";
  }

  // ------------------------------------------------------- per-frame bits
  tick(t: number): void {
    const sec = Math.floor(t);
    if (sec === this.lastSec) return;
    this.lastSec = sec;
    this.renderFrame(t);
    this.renderPin(t);
  }

  /** One line that frames the match from the favourite club's side. */
  private renderFrame(t: number): void {
    const club = this.s.club;
    const { meta, events } = this.x.host;
    if (!club) { this.frame.textContent = ""; return; }
    const other = club === meta.home ? meta.away : meta.home;
    let score: Record<string, number> = { [club]: 0, [other]: 0 };
    for (const e of events) { if (e.t > t) break; if (e.score) score = e.score; }
    const name = meta.teams.find((x) => x.id === club)?.name ?? club;
    const d = (score[club] ?? 0) - (score[other] ?? 0);
    const state = d > 0 ? `${d} up` : d < 0 ? `${-d} down` : "level";
    const pf = this.s.player;
    const pfName = pf ? meta.players.find((p) => p.id === pf)?.name : "";
    this.frame.textContent = `${name} are ${state}.` + (pfName ? ` Following ${pfName}.` : "");
  }

  private renderPin(t: number): void {
    const m = this.s.metric;
    if (!m) { this.chip.hidden = true; return; }
    const { meta } = this.x.host;
    const pf = this.s.player;
    const fmt = (v: number) => (m === "distance" ? v.toFixed(2) : m === "xg" ? v.toFixed(2) : String(Math.round(v)));
    const unit = METRICS[m].unit;
    let html = `<b>${esc(METRICS[m].label)}</b>`;
    if (pf) {
      const p = meta.players.find((x) => x.id === pf)!;
      html += `<span>${esc(surname(p.name))} ${fmt(this.value(m, t, pf, null))}${unit}</span>`;
    } else {
      const order = this.s.club && this.s.club === meta.away ? [meta.away, meta.home] : [meta.home, meta.away];
      html += order
        .map((tid) => {
          const team = meta.teams.find((x) => x.id === tid)!;
          return `<span><i style="--c:${esc(team.colour)}"></i>${esc(tid)} ${fmt(this.value(m, t, null, tid))}${unit}</span>`;
        })
        .join("");
    }
    this.chip.innerHTML = html;
    this.chip.hidden = false;
  }

  // -------------------------------------------------------------- metrics
  private value(m: string, t: number, pid: string | null, team: string | null): number {
    const live = this.fromSnapshot(m, t, pid, team);
    if (live !== null) return live;
    const { events, meta } = this.x.host;
    const mine = (e: Ev) => (pid ? e.pl === pid : e.team === team);
    if (m === "distance" || m === "sprints") {
      const tr = this.tracks();
      const sec = Math.max(0, Math.min(tr.dist[0].length - 1, Math.floor(t)));
      const order = meta.tracking.order;
      let sum = 0;
      order.forEach((id, i) => {
        if (pid ? id !== pid : !id.startsWith(`${team}_`)) return;
        sum += m === "distance" ? tr.dist[i][sec] / 1000 : tr.sprints[i][sec];
      });
      return sum;
    }
    let a = 0, b = 0;
    for (const e of events) {
      if (e.t > t) break;
      if (!mine(e)) continue;
      if (m === "xg" && e.type === "shot") a += Number(e.x.xg ?? 0);
      else if (m === "shots" && e.type === "shot") a++;
      else if (m === "passacc" && e.type === "pass") { b++; if (e.out === "complete") a++; }
      else if (m === "defence" && isDefAction(e)) a++;
    }
    return m === "passacc" ? (b ? (100 * a) / b : 0) : a;
  }

  /** Live snapshot first, then the packed per-snapshot team stats in meta.momentum, else null. */
  private fromSnapshot(m: string, t: number, pid: string | null, team: string | null): number | null {
    let row: Record<string, number> | undefined | null = this.snapshot && (pid ? this.snapshot.players?.[pid] : this.snapshot.teams?.[team ?? ""]);
    if (!row && !pid && team) {
      for (const mp of this.x.host.meta.momentum) { if (mp.t > t) break; if (mp.stats?.[team]) row = mp.stats[team]; }
    }
    if (!row) return null;
    const n = (k: string) => Number(row[k] ?? 0);
    switch (m) {
      case "distance": return "distance_km" in row ? n("distance_km") : null;
      case "sprints": return "sprints" in row ? n("sprints") : null;
      case "xg": return "xg" in row ? n("xg") : null;
      case "shots": return "shots" in row ? n("shots") : null;
      case "passacc": return "pass_accuracy" in row ? n("pass_accuracy") * (n("pass_accuracy") <= 1 ? 100 : 1) : null;
      case "defence": return !("interceptions" in row) ? null : n("tackles_won") + n("interceptions") + n("clearances") + n("blocks") + n("recoveries");
    }
    return null;
  }

  /** Live mode: add one insight to the rail's file (and the English copy). */
  addInsight(item: { id: string; t: number }): void {
    const files = new Set([this.x.host.getInsights(), this.english].filter(Boolean) as { items: { id?: string; t: number }[] }[]);
    if (!files.size) {
      const f = { match_id: this.x.host.meta.match_id, generated_at: new Date().toISOString(), mode: "live", model: null, items: [] as { id?: string; t: number }[] };
      this.english = f;
      this.x.host.setInsights(f);
      files.add(f);
    }
    for (const f of files) {
      f.items = [...f.items.filter((i) => i.id !== item.id), item].sort((a, b) => a.t - b.t);
    }
    this.x.host.refresh();
  }

  /** Cumulative distance and sprint counts per player at one-second steps, built once. */
  private tracks(): { dist: Float32Array[]; sprints: Uint16Array[] } {
    if (this.track) return this.track;
    const tr = this.x.host.tracking;
    const n = Math.floor(tr.duration) + 1;
    const dist = Array.from({ length: tr.count }, () => new Float32Array(n));
    const sprints = Array.from({ length: tr.count }, () => new Uint16Array(n));
    const smp = tr.newSample();
    const lx = new Float32Array(tr.count).fill(NaN), ly = new Float32Array(tr.count).fill(NaN);
    const inSprint = new Uint8Array(tr.count);
    for (let s = 0; s < n; s++) {
      tr.sample(s, smp);
      for (let p = 0; p < tr.count; p++) {
        const x = smp.pos[2 * p], y = smp.pos[2 * p + 1];
        const prevD = s ? dist[p][s - 1] : 0, prevS = s ? sprints[p][s - 1] : 0;
        let d = 0;
        if (!Number.isNaN(x) && !Number.isNaN(lx[p])) {
          d = Math.hypot(x - lx[p], y - ly[p]);
          if (d > 12) d = 0; // a jump, not running
        }
        const v = d * 3.6; // km/h over the last second
        let add = 0;
        if (v >= 25 && !inSprint[p]) { inSprint[p] = 1; add = 1; } else if (v < 20) inSprint[p] = 0;
        dist[p][s] = prevD + d;
        sprints[p][s] = prevS + add;
        lx[p] = x; ly[p] = y;
      }
    }
    this.track = { dist, sprints };
    return this.track;
  }
}

export function involves(e: Ev, pid: string): boolean {
  return e.pl === pid || e.x?.receiver_id === pid || e.x?.opponent_id === pid;
}

function isDefAction(e: Ev): boolean {
  return (e.type === "tackle" && e.out === "won") || e.type === "interception" || e.type === "clearance" || e.type === "block" || e.type === "ball_recovery";
}

function surname(name: string): string {
  return name.split(" ").slice(-1)[0];
}
