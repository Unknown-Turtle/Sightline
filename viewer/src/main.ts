import "./styles.css";
import { clockAt, loadMatch, relX, type Ev, type Meta, type Tracking } from "./data";
import { Stage, type CameraMode } from "./stage";
import { cardLabel, detectPoints, zoneText, type Lens, type Point } from "./points";
import { currentInsights, loadInsights, receiptLine, STANDALONE, textFor, type Insight, type InsightFile } from "./insights";

/** One card on the rail: a templated point, an insight that replaces its wording, or a standalone insight. */
interface RailItem {
  id: string;
  kind: string;
  team: string;
  subject: string | null;
  text: string;
  stat: string | null;
  forEv: Ev[];
  againstEv: Ev[];
  checked: number;
  insight: Insight | null;
  rejected: boolean;
  t: number;
}

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const ON_BALL = new Set(["pass", "carry", "take_on", "shot", "clearance"]);

interface State {
  t: number;
  /** where the match is; a replay moves t but never this */
  liveT: number;
  playing: boolean;
  speed: number;
  lens: Lens;
  cam: CameraMode;
  item: RailItem | null;
  side: "for" | "against";
  replayEnd: number | null;
  playingCard: string | null;
}

async function boot(): Promise<void> {
  const [{ meta, events, tracking }, ins] = await Promise.all([loadMatch(), loadInsights()]);
  $("loading").hidden = true;
  const app = new App(meta, events, tracking, ins?.file ?? null, ins?.source ?? null);
  app.start();
}

class App {
  private stage: Stage;
  private st: State;
  private lastFrame = performance.now();
  private lastPointsAt = -1;
  private items: RailItem[] = [];
  private byId = new Map<string, Ev>();
  private dismissedRecaps = new Set<string>();
  private tags: HTMLDivElement[] = [];
  private names = new Map<string, { name: string; number: number; team: string }>();
  private duration: number;
  private home: string;
  private away: string;

  constructor(private meta: Meta, private events: Ev[], private tracking: Tracking,
              private insights: InsightFile | null, private insightSource: string | null) {
    this.stage = new Stage($("canvas") as HTMLCanvasElement, meta, tracking, events);
    for (const e of events) this.byId.set(e.id, e);
    for (const p of meta.players) this.names.set(p.id, { name: p.name, number: p.number, team: p.team });
    this.duration = tracking.duration;
    this.home = meta.home;
    this.away = meta.away;
    const p2 = meta.periods[1];
    // open just before the comeback starts, paused, so the first view already says something
    this.st = {
      t: p2 ? p2.start + (72.6 - 45) * 60 : 0,
      liveT: 0,
      playing: false, speed: 12, lens: "casual", cam: "broadcast",
      item: null, side: "for", replayEnd: null, playingCard: null,
    };
    this.st.liveT = this.st.t;
    this.buildHeader();
    this.buildTimeline();
    this.bindControls();
    const ro = new ResizeObserver(() => this.resize());
    ro.observe($("stage"));
    this.resize();
  }

  start(): void {
    this.stage.update(this.st.t, 0, null, []);
    this.stage.snapCamera();
    this.refreshPoints(true);
    if (this.items[0]) this.selectItem(this.items[0]);
    this.booted = true;
    const loop = (now: number) => {
      const real = Math.min(0.1, (now - this.lastFrame) / 1000);
      this.lastFrame = now;
      this.tick(real);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  // ------------------------------------------------------------------ loop
  private tick(real: number): void {
    const st = this.st;
    const prev = st.t;
    if (st.playing) {
      st.t = Math.min(this.duration, st.t + real * st.speed);
      if (st.replayEnd !== null && st.t >= st.replayEnd) {
        this.endReplay();
        return;
      }
      if (st.t >= this.duration) this.setPlaying(false);
      if (st.replayEnd === null) st.liveT = st.t;
    }
    const dt = st.t - prev;
    const recent = this.range(st.t - 4, st.t).filter((e) => e.type === "pass");
    this.stage.update(st.t, st.playing ? real : 0.016, this.carrier(), recent);
    this.stage.render();
    if (dt > 0 && dt < 30) this.fireToasts(prev, st.t);
    this.updateHeader();
    this.drawTags();
    if (!this.scrubbing) ($("scrub") as HTMLInputElement).value = String((st.liveT / this.duration) * 1000);
    if (Math.abs(st.liveT - this.lastPointsAt) >= 2) this.refreshPoints(false);
  }

  private scrubbing = false;

  private range(a: number, b: number): Ev[] {
    const ev = this.events;
    let lo = 0, hi = ev.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (ev[m].t <= a) lo = m + 1; else hi = m; }
    const out: Ev[] = [];
    for (let i = lo; i < ev.length && ev[i].t <= b; i++) out.push(ev[i]);
    return out;
  }

  private lastEventBefore(t: number, pred: (e: Ev) => boolean): Ev | null {
    const ev = this.events;
    let lo = 0, hi = ev.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (ev[m].t <= t) lo = m + 1; else hi = m; }
    for (let i = lo - 1; i >= 0; i--) if (pred(ev[i])) return ev[i];
    return null;
  }

  /** The player nearest the ball when it is at their feet. */
  private carrier(): string | null {
    const smp = this.stage.sample;
    const [bx, by, bz] = smp.ball;
    if (bz > 1.2) return null;
    let best: string | null = null, bd = 1.8;
    const order = this.meta.tracking.order;
    for (let i = 0; i < order.length; i++) {
      const x = smp.pos[2 * i];
      if (Number.isNaN(x)) continue;
      const d = Math.hypot(x - bx, smp.pos[2 * i + 1] - by);
      if (d < bd) { bd = d; best = order[i]; }
    }
    return best;
  }

  // ---------------------------------------------------------------- header
  private buildHeader(): void {
    const th = this.meta.teams.find((t) => t.id === this.home)!;
    const ta = this.meta.teams.find((t) => t.id === this.away)!;
    $("home-name").textContent = th.name;
    $("away-name").textContent = ta.name;
    for (const [id, team] of [["home-chip", th], ["away-chip", ta]] as const) {
      const crest = $(id);
      crest.style.setProperty("--c", team.colour);
      crest.textContent = initials(team.name);
      crest.setAttribute("aria-hidden", "true");
    }
    const split = $("mc-split");
    split.style.setProperty("--home", th.colour);
    split.style.setProperty("--away", ta.colour);
    const c = this.meta.context;
    const bits: [string, string | number | undefined][] = [
      ["", this.meta.competition],
      ["Matchday", c.matchday],
      ["", this.meta.venue],
      ["Crowd", c.attendance?.toLocaleString("en-GB")],
      ["Referee", c.referee?.name],
      ["Weather", c.weather],
    ];
    $("context").innerHTML = bits
      .filter(([, v]) => v !== undefined && v !== null)
      .map(([k, v]) => `<span>${k ? `${k} ` : ""}<b>${v}</b></span>`)
      .join("");
  }

  private updateHeader(): void {
    const ev = this.lastEventBefore(this.st.liveT, (e) => !!e.score && (e.type === "goal" || e.type !== "shot"));
    const sc = ev?.score ?? { [this.home]: 0, [this.away]: 0 };
    $("home-score").textContent = String(sc[this.home] ?? 0);
    $("away-score").textContent = String(sc[this.away] ?? 0);
    $("clock").textContent = clockAt(this.meta, this.st.liveT).text;
  }

  // -------------------------------------------------------------- timeline
  private buildTimeline(): void {
    const svg = $("momentum") as unknown as SVGSVGElement;
    const W = 1000, H = 46, mid = H / 2;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const pts = this.meta.momentum;
    const ch = this.meta.teams.find((t) => t.id === this.home)!.colour;
    const ca = this.meta.teams.find((t) => t.id === this.away)!.colour;
    const xs = (t: number) => (t / this.duration) * W;
    const ys = (v: number) => mid - (v / 100) * (mid - 2);
    let up = `M0 ${mid}`, down = `M0 ${mid}`;
    for (const p of pts) {
      const net = (p.m[this.home] ?? 0) - (p.m[this.away] ?? 0);
      up += ` L${xs(p.t).toFixed(1)} ${ys(Math.max(0, net)).toFixed(1)}`;
      down += ` L${xs(p.t).toFixed(1)} ${ys(Math.min(0, net)).toFixed(1)}`;
    }
    const end = xs(pts.length ? pts[pts.length - 1].t : this.duration);
    up += ` L${end} ${mid} Z`;
    down += ` L${end} ${mid} Z`;
    const ht = this.meta.periods[1] ? xs(this.meta.periods[1].start) : W / 2;
    svg.innerHTML = `
      <rect x="0" y="0" width="${W}" height="${H}" fill="var(--panel)" />
      <path d="${up}" fill="${ch}" opacity="0.85" />
      <path d="${down}" fill="${ca}" opacity="0.85" />
      <line x1="0" x2="${W}" y1="${mid}" y2="${mid}" stroke="var(--line)" stroke-width="1" />
      <line x1="${ht}" x2="${ht}" y1="0" y2="${H}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3" />`;
    const markers = $("markers");
    markers.innerHTML = "";
    for (const g of this.events.filter((e) => e.type === "goal")) {
      const m = document.createElement("i");
      m.className = "marker";
      m.style.left = `${(g.t / this.duration) * 100}%`;
      m.style.setProperty("--c", this.meta.teams.find((t) => t.id === g.team)!.colour);
      m.title = `${g.clock.split(".")[0]} ${this.names.get(g.pl ?? "")?.name ?? ""}`;
      markers.appendChild(m);
    }
  }

  // -------------------------------------------------------------- controls
  private bindControls(): void {
    $("play").addEventListener("click", () => {
      if (this.st.replayEnd !== null) { this.endReplay(); return; }
      this.setPlaying(!this.st.playing);
    });
    document.querySelectorAll<HTMLButtonElement>("[data-speed]").forEach((b) =>
      b.addEventListener("click", () => {
        this.st.speed = Number(b.dataset.speed);
        this.markOn("[data-speed]", b);
      }),
    );
    document.querySelectorAll<HTMLButtonElement>("[data-cam]").forEach((b) =>
      b.addEventListener("click", () => {
        this.st.cam = b.dataset.cam as CameraMode;
        this.stage.mode = this.st.cam;
        this.stage.snapCamera();
        this.markOn("[data-cam]", b);
      }),
    );
    document.querySelectorAll<HTMLButtonElement>("[data-lens]").forEach((b) =>
      b.addEventListener("click", () => {
        this.st.lens = b.dataset.lens as Lens;
        // overlays in the commentator lens match casual
        this.stage.lens = this.st.lens === "tactical" ? "tactical" : "casual";
        this.markOn("[data-lens]", b);
        this.refreshPoints(true);
        if (this.st.item) this.renderReel();
      }),
    );
    document.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((b) =>
      b.addEventListener("click", () => this.showTab(b.dataset.tab!)),
    );
    const scrub = $("scrub") as HTMLInputElement;
    scrub.addEventListener("input", () => {
      this.scrubbing = true;
      this.seek((Number(scrub.value) / 1000) * this.duration);
    });
    scrub.addEventListener("change", () => (this.scrubbing = false));
    $("tab-for").addEventListener("click", () => this.setSide("for"));
    $("tab-against").addEventListener("click", () => this.setSide("against"));
    window.addEventListener("keydown", (e) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.code === "Space") { e.preventDefault(); this.setPlaying(!this.st.playing); }
      if (e.code === "ArrowRight") this.seek(this.st.t + 10);
      if (e.code === "ArrowLeft") this.seek(this.st.t - 10);
    });
  }

  private markOn(sel: string, on: HTMLElement): void {
    document.querySelectorAll(sel).forEach((x) => {
      x.classList.toggle("on", x === on);
      if (x.hasAttribute("aria-pressed")) x.setAttribute("aria-pressed", String(x === on));
    });
  }

  /** Switch the match-centre tab (live, moments, stats, ratings, claims, patterns). */
  private showTab(name: string): void {
    document.querySelectorAll<HTMLElement>(".panel[id^='panel-']").forEach((p) => (p.hidden = p.id !== `panel-${name}`));
    document.querySelectorAll<HTMLElement>(".tab[data-tab]").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
    if (name === "live") this.resize();
    if (name === "stats") this.renderStats(true);
  }

  // ----------------------------------------------------------------- stats
  private statsSig = "";

  /** Comparison rows from the latest snapshot at the live time: home left, label centre, away right. */
  private renderStats(force = false): void {
    const pts = this.meta.momentum;
    let snap: (typeof pts)[number] | null = null;
    for (const p of pts) { if (p.t <= this.st.liveT + 1) snap = p; else break; }
    const sig = snap ? String(snap.t) : "none";
    if (!force && sig === this.statsSig) return;
    this.statsSig = sig;
    const th = this.meta.teams.find((t) => t.id === this.home)!;
    const ta = this.meta.teams.find((t) => t.id === this.away)!;
    const rows: [string, string, (v: number) => string, boolean][] = [
      ["possession", "Possession", (v) => `${Math.round(v * 100)}%`, true],
      ["shots", "Shots", (v) => String(v), true],
      ["shots_on_target", "On target", (v) => String(v), true],
      ["xg", "Expected goals", (v) => v.toFixed(2), true],
      ["big_chances", "Big chances", (v) => String(v), true],
      ["passes", "Passes", (v) => String(v), true],
      ["pass_accuracy", "Pass accuracy", (v) => `${Math.round(v * 100)}%`, true],
      ["final_third_entries", "Final-third entries", (v) => String(v), true],
      ["box_entries", "Box entries", (v) => String(v), true],
      ["corners", "Corners", (v) => String(v), true],
      ["tackles", "Tackles", (v) => String(v), true],
      ["interceptions", "Interceptions", (v) => String(v), true],
      ["fouls", "Fouls", (v) => String(v), false],
      ["yellows", "Yellow cards", (v) => String(v), false],
      ["distance_km", "Distance (km)", (v) => v.toFixed(1), true],
      ["sprints", "Sprints", (v) => String(v), true],
    ];
    const box = $("stats-rows");
    $("stats-sub").textContent = snap
      ? `${th.name} against ${ta.name}, as of ${clockAt(this.meta, snap.t).text}`
      : "Stats appear once the match is under way.";
    if (!snap || !snap.stats) { box.innerHTML = `<p class="empty">No snapshot yet.</p>`; return; }
    const hs = snap.stats[this.home] ?? {}, as = snap.stats[this.away] ?? {};
    box.innerHTML = rows
      .filter(([k]) => k in hs || k in as)
      .map(([k, label, fmt, moreIsBetter]) => {
        const a = Number(hs[k] ?? 0), b = Number(as[k] ?? 0);
        const total = a + b || 1;
        const lead = a === b ? null : (a > b) === moreIsBetter ? "home" : "away";
        const leadColour = lead === "home" ? th.colour : lead === "away" ? ta.colour : "inherit";
        return `<div class="stat-row" style="--lead:${leadColour}">
          <span class="v home${lead === "home" ? " lead" : ""}">${fmt(a)}</span>
          <span class="l">${label}</span>
          <span class="v away${lead === "away" ? " lead" : ""}">${fmt(b)}</span>
          <span class="bar" aria-hidden="true">
            <i class="home" style="--w:${Math.round((a / total) * 100)}%;--c:${th.colour}"></i>
            <i class="away" style="--w:${Math.round((b / total) * 100)}%;--c:${ta.colour}"></i>
          </span></div>`;
      })
      .join("");
  }

  private setPlaying(p: boolean): void {
    this.st.playing = p;
    const b = $("play");
    b.textContent = p ? "Pause" : "Play";
    b.setAttribute("aria-label", p ? "Pause" : "Play");
  }

  private seek(t: number): void {
    if (this.st.replayEnd !== null) { this.st.replayEnd = null; $("replay-badge").hidden = true; }
    this.st.t = Math.max(0, Math.min(this.duration, t));
    this.st.liveT = this.st.t;
    $("toasts").innerHTML = "";
    this.stage.update(this.st.t, 0, null, []);
    this.stage.snapCamera();
    this.refreshPoints(false);
  }

  private resize(): void {
    const el = $("stage");
    const r = el.getBoundingClientRect();
    this.stage.resize(Math.max(1, r.width), Math.max(1, r.height));
  }

  // ------------------------------------------------------------- overlays
  private tag(i: number): HTMLDivElement {
    while (this.tags.length <= i) {
      const d = document.createElement("div");
      d.className = "tag";
      $("overlay").appendChild(d);
      this.tags.push(d);
    }
    return this.tags[i];
  }

  private drawTags(): void {
    const el = $("stage");
    const w = el.clientWidth, h = el.clientHeight;
    let n = 0;
    const place = (pid: string, cls: string, html: string, lift = 0) => {
      const p = this.stage.project(pid, w, h);
      if (!p) return;
      const d = this.tag(n++);
      d.className = `tag ${cls}`;
      d.innerHTML = html;
      d.style.left = `${p.x}px`;
      d.style.top = `${p.y - lift}px`;
      d.hidden = false;
    };
    const shown = new Set<string>();
    const focus = this.stage.focus;
    if (focus) {
      const f = this.names.get(focus)!;
      place(focus, "focus", `<span class="num">${f.number}</span>${surname(f.name)}`);
      shown.add(focus);
    }
    const carrier = this.carrier();
    if (carrier && !shown.has(carrier)) {
      const c = this.names.get(carrier)!;
      place(carrier, "", `<span class="num">${c.number}</span>${surname(c.name)}`);
      shown.add(carrier);
    }
    // sprint tags: the fastest players over 29 km/h
    const fast = this.meta.tracking.order
      .map((id) => ({ id, v: this.stage.speedOf(id) }))
      .filter((x) => x.v >= 29)
      .sort((a, b) => b.v - a.v)
      .slice(0, this.st.lens === "tactical" ? 3 : 2);
    for (const f of fast) place(f.id, "speed", `${f.v.toFixed(1)} km/h`, shown.has(f.id) ? 26 : 0);
    // tactical: xG on recent shots
    if (this.st.lens === "tactical") {
      for (const s of this.range(this.st.t - 3, this.st.t).filter((e) => e.type === "shot" && e.s)) {
        const p = this.stage.projectPoint(s.s![0], s.s![1], w, h, 1);
        if (!p) continue;
        const d = this.tag(n++);
        d.className = "tag xg";
        d.innerHTML = `xG ${Number(s.x.xg).toFixed(2)}`;
        d.style.left = `${p.x}px`;
        d.style.top = `${p.y}px`;
        d.hidden = false;
      }
    }
    for (let i = n; i < this.tags.length; i++) this.tags[i].hidden = true;
  }

  private fireToasts(a: number, b: number): void {
    for (const e of this.range(a, b)) {
      let title = "", body = "";
      const who = e.pl ? this.names.get(e.pl)?.name ?? "" : "";
      const team = this.meta.teams.find((t) => t.id === e.team);
      if (e.type === "goal") {
        const sc = e.score ?? {};
        title = `Goal, ${team?.name}`;
        body = `${who} makes it ${sc[this.home] ?? 0}-${sc[this.away] ?? 0}`;
        const shot = this.events.find((x) => x.id === e.rel);
        if (shot && this.st.lens === "tactical") {
          body += `. ${Number(shot.x.xg).toFixed(2)} xG${shot.x.assist_type ? `, ${shot.x.assist_type.replace("_", " ")} assist` : ""}`;
        } else if (shot && Number(shot.x.xg) < 0.05) body += ". Out of almost nothing.";
      } else if (e.type === "shot" && e.out !== "goal" && Number(e.x.xg) >= 0.3) {
        title = e.out === "saved" ? "Big chance saved" : "Big chance missed";
        body = this.st.lens === "tactical" ? `${who}, ${Number(e.x.xg).toFixed(2)} xG from ${e.x.distance_m} m` : `${who} should have scored`;
      } else if (e.type === "card") {
        title = e.out === "yellow" ? "Yellow card" : "Red card";
        body = who;
      } else if (e.type === "substitution" && this.st.lens === "tactical") {
        title = `Change, ${team?.name}`;
        body = `${this.names.get(e.x.player_in)?.name} on for ${this.names.get(e.x.player_out)?.name}`;
      }
      if (!title) continue;
      const box = $("toasts");
      const d = document.createElement("div");
      d.className = "toast";
      d.style.setProperty("--c", team?.colour ?? "#f2b33d");
      d.innerHTML = `<b>${title}</b>${body}`;
      box.appendChild(d);
      while (box.children.length > 3) box.firstElementChild!.remove();
      setTimeout(() => d.remove(), 6000);
    }
  }

  // ---------------------------------------------------------------- points
  /** Rebuild the rail: templated points, overridden by insights when one exists for the point_id,
   *  plus standalone insights (momentum, score_state, recap) as their own items. */
  private refreshPoints(force: boolean): void {
    this.lastPointsAt = this.st.liveT;
    this.renderStats();
    const liveT = this.st.liveT;
    const lens = this.st.lens;
    const pts = detectPoints(this.meta, this.events, liveT);
    const current = currentInsights(this.insights, liveT);
    const items: RailItem[] = [];
    for (const p of pts) {
      const ins = current.get(p.id) ?? null;
      items.push(this.railItem(p, ins, lens));
      current.delete(p.id);
    }
    for (const ins of current.values()) {
      if (STANDALONE.has(ins.kind)) items.push(this.railItem(null, ins, lens));
    }
    // templated points keep their strength order; standalone insights follow, newest first
    items.sort((x, y) => Number(x.stat === null) - Number(y.stat === null) || (x.stat === null ? y.t - x.t : 0));
    const sig = items.map((i) => `${i.id}:${i.stat}:${i.insight?.id ?? ""}:${i.rejected}`).join("|") + lens;
    $("rail-sub").textContent = `As of ${clockAt(this.meta, liveT).text}. ${this.insights ? "AI insights with receipts" : "Points"} update as the match plays.`;
    this.maybeRecap(liveT);
    if (!force && sig === this.pointsSig) return;
    this.pointsSig = sig;
    this.items = items;
    const list = $("points");
    list.innerHTML = "";
    if (!items.length) {
      list.innerHTML = `<li class="empty">Nothing stands out yet. Points appear once a pattern holds up.</li>`;
    }
    for (const it of items) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.className = "point" + (this.st.item?.id === it.id ? " on" : "");
      const colour = this.meta.teams.find((t) => t.id === it.team)?.colour ?? "#999";
      b.innerHTML = `<span class="kind">${kindLabel(it.kind)}</span>
        <span class="claim">${esc(it.text)}</span>
        ${it.stat ? `<span class="stat">${esc(it.stat)}</span>` : ""}
        <span class="meta"><i class="who" style="--c:${colour}"></i>${it.forEv.length} moments for, ${it.againstEv.length} against</span>
        ${this.receiptHtml(it)}
        ${lens === "commentator" ? this.triviaHtml(it) : ""}`;
      b.addEventListener("click", () => this.selectItem(it));
      li.appendChild(b);
      list.appendChild(li);
    }
    this.renderComingUp();
    // keep the open item in sync with the latest evidence
    if (this.st.item) {
      const fresh = items.find((i) => i.id === this.st.item!.id);
      if (fresh) { this.st.item = fresh; this.renderReel(); }
    }
  }
  private pointsSig = "";

  private railItem(p: Point | null, ins: Insight | null, lens: Lens): RailItem {
    const rejected = !!ins && !ins.check.passed;
    const useInsight = !!ins && !rejected;
    const template = p ? claimOf(p, lens) : ins ? this.standaloneTemplate(ins) : "";
    const evs = (ids: string[]) => ids.map((id) => this.byId.get(id)).filter((e): e is Ev => !!e);
    return {
      id: p?.id ?? ins!.point_id,
      kind: p?.kind ?? ins!.kind,
      team: p?.team ?? ins!.team,
      subject: p?.subject ?? ins?.subject ?? null,
      text: useInsight ? textFor(ins!, lens) : template,
      stat: p?.stat ?? null,
      forEv: ins ? evs(ins.evidence_for) : p!.forEv,
      againstEv: ins ? evs(ins.evidence_against) : p!.againstEv,
      checked: p?.checked ?? (ins!.evidence_for.length + ins!.evidence_against.length),
      insight: ins,
      rejected,
      t: ins?.t ?? -1,
    };
  }

  /** Wording for a standalone insight whose AI text was rejected by the checker. */
  private standaloneTemplate(ins: Insight): string {
    const team = this.meta.teams.find((t) => t.id === ins.team)?.name ?? ins.team;
    const sc = this.lastEventBefore(ins.t, (e) => !!e.score)?.score ?? {};
    const score = `${sc[this.home] ?? 0}-${sc[this.away] ?? 0}`;
    if (ins.kind === "momentum") return `Momentum has swung towards ${team}`;
    if (ins.kind === "score_state") return `${score} at ${ins.clock}`;
    return `${ins.point_id.endsWith("ft") ? "Full time" : "Half time"}: ${score}`;
  }

  private receiptHtml(it: RailItem): string {
    const ins = it.insight;
    if (!ins) return "";
    const line = receiptLine(ins);
    const head = it.rejected
      ? `<span class="receipt-line rejected"><b>AI version rejected by the checker.</b> Showing the template. ${esc(line)}</span>`
      : `<span class="receipt-line">${esc(line)}</span>`;
    const r = ins.receipt;
    const mode = this.insights?.mode ?? "fallback";
    const agents = r.agents?.length ? r.agents.join(", ") : "not recorded";
    const issues = ins.check.issues?.length ? `<li>Issues: ${esc(ins.check.issues.join("; "))}</li>` : "";
    return `${head}<details class="receipt-more" onclick="event.stopPropagation()"><summary>Full receipt</summary><ul>
      <li>Agents: ${esc(agents)}</li>
      <li>Tokens: ${r.tokens_in ?? 0} in, ${r.tokens_out ?? 0} out</li>
      <li>Mode: ${esc(mode)}${this.insightSource === "sample" ? " (sample fixture)" : ""}</li>
      <li>Numbers checked: ${ins.check.numbers_checked}, retries: ${ins.check.retries}</li>${issues}
      <li>Written at ${esc(ins.clock)}, id ${esc(ins.id)}</li></ul></details>`;
  }

  private triviaHtml(it: RailItem): string {
    const tr = it.insight?.trivia ?? [];
    if (!tr.length) return "";
    return tr.map((x) => `<span class="trivia"><b>${esc(x.text)}</b> From ${esc(sourceName(x.source))}${x.row ? ` (${esc(x.row)})` : ""}</span>`).join("");
  }

  /** Commentator lens: the score_state insights still to come, as prepared lines. */
  private renderComingUp(): void {
    const box = $("coming");
    const list = this.insights?.items.filter((i) => i.kind === "score_state" && i.t > this.st.liveT) ?? [];
    if (this.st.lens !== "commentator" || !list.length) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `<h3>Coming up</h3><ul>${list.slice(0, 4).map((i) =>
      `<li><b>${esc(i.clock)}</b> ${esc(i.text.commentator || i.text.casual)}</li>`).join("")}</ul>`;
  }

  /** Half-time and full-time recaps as a dismissable panel over the stage. */
  private maybeRecap(liveT: number): void {
    const box = $("recap");
    let recap: Insight | null = null;
    for (const i of this.insights?.items ?? []) if (i.kind === "recap" && i.t <= liveT && i.check.passed) recap = i;
    if (!recap || this.dismissedRecaps.has(recap.id) || liveT - recap.t > 600) { box.hidden = true; return; }
    if (box.dataset.id === recap.id) return;
    box.dataset.id = recap.id;
    box.hidden = false;
    const title = recap.point_id.endsWith("ft") || liveT >= (this.meta.periods[1]?.end ?? Infinity) - 1 ? "Full time" : "Half time";
    box.innerHTML = `<h3>${title}</h3><p>${esc(textFor(recap, this.st.lens))}</p>
      <span class="receipt-line">${esc(receiptLine(recap))}</span>
      <button class="pill close" type="button">Dismiss</button>`;
    const id = recap.id;
    box.querySelector("button")!.addEventListener("click", () => { this.dismissedRecaps.add(id); box.hidden = true; });
  }

  private selectItem(it: RailItem): void {
    this.st.item = it;
    this.st.side = "for";
    this.stage.focus = it.subject;
    document.querySelectorAll(".point").forEach((el, i) => el.classList.toggle("on", this.items[i]?.id === it.id));
    this.renderReel();
    if (!$("panel-moments").hidden || !this.booted) return;
    this.showTab("moments");
  }
  private booted = false;

  private setSide(side: "for" | "against"): void {
    this.st.side = side;
    this.renderReel();
  }

  private renderReel(): void {
    const p = this.st.item;
    const wrap = $("reel-wrap");
    if (!p) { wrap.hidden = true; return; }
    wrap.hidden = false;
    $("reel-title").textContent = p.text;
    $("reel-receipt").textContent = p.insight
      ? `${receiptLine(p.insight)}. Evidence: ${p.forEv.length} events for, ${p.againstEv.length} against, each one a logged event. Select a card to watch it.`
      : `Checked against ${p.checked} logged events up to ${clockAt(this.meta, this.st.liveT).text}. Every card is one of them. Select a card to watch it.`;
    const tf = $("tab-for"), ta = $("tab-against");
    tf.textContent = `For (${p.forEv.length})`;
    ta.textContent = `Against (${p.againstEv.length})`;
    tf.classList.toggle("on", this.st.side === "for");
    ta.classList.toggle("on", this.st.side === "against");
    tf.setAttribute("aria-selected", String(this.st.side === "for"));
    ta.setAttribute("aria-selected", String(this.st.side === "against"));
    const list = this.st.side === "for" ? p.forEv : p.againstEv;
    const reel = $("reel");
    reel.innerHTML = "";
    if (!list.length) {
      reel.innerHTML = `<p class="empty">No moments on this side yet.</p>`;
      return;
    }
    for (const e of list) {
      const b = document.createElement("button");
      b.className = "card" + (this.st.playingCard === e.id ? " playing" : "");
      const who = e.pl ? this.names.get(e.pl)?.name ?? "" : "";
      const opp = e.x.opponent_id ? ` against ${surname(this.names.get(e.x.opponent_id)?.name ?? "")}` : "";
      const good = this.st.side === "for";
      const extra = e.type === "shot" ? `, ${Number(e.x.xg).toFixed(2)} xG` : "";
      b.innerHTML = `<span class="row"><span class="min">${clockAt(this.meta, e.t).text}</span>
          <span class="res ${good ? "good" : "bad"}">${good ? "Supports" : "Counts against"}</span></span>
        <span class="what">${cardLabel(e)}</span>
        <span class="where">${p.subject ? "" : `${surname(who)}, `}${zoneText(e)}${opp}${extra}</span>`;
      const c = document.createElement("canvas");
      c.width = 210; c.height = 136;
      drawThumb(c, e);
      b.appendChild(c);
      b.addEventListener("click", () => this.playMoment(e));
      reel.appendChild(b);
    }
  }

  /** Leave a replay and go back to where the match was. */
  private endReplay(): void {
    this.st.replayEnd = null;
    this.st.playingCard = null;
    this.st.t = this.st.liveT;
    $("replay-badge").hidden = true;
    $("toasts").innerHTML = "";
    this.setPlaying(false);
    this.st.speed = 12;
    this.markOn("[data-speed]", document.querySelector('[data-speed="12"]')!);
    this.stage.update(this.st.t, 0, null, []);
    this.stage.snapCamera();
    this.renderReel();
  }

  private playMoment(e: Ev): void {
    this.st.playingCard = e.id;
    this.stage.focus = this.st.item?.subject ?? e.pl;
    this.st.t = Math.max(0, e.t - 4);
    this.st.replayEnd = e.t + 3;
    this.st.speed = 1;
    this.markOn("[data-speed]", document.querySelector('[data-speed="1"]')!);
    this.stage.mode = "broadcast";
    this.st.cam = "broadcast";
    this.markOn("[data-cam]", document.querySelector('[data-cam="broadcast"]')!);
    this.stage.update(this.st.t, 0, null, []);
    this.stage.snapCamera();
    $("replay-badge").hidden = false;
    $("toasts").innerHTML = "";
    this.setPlaying(true);
    document.querySelectorAll(".card").forEach((c) => c.classList.remove("playing"));
    this.showTab("live");
    $("stage").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
    this.renderReel();
  }
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));
}

function kindLabel(kind: string): string {
  return ({ anchor: "Defensive anchor", duel: "Winning the duel", finishing: "Finishing", momentum: "Momentum",
    score_state: "Score state", recap: "Recap" } as Record<string, string>)[kind] ?? kind;
}

function sourceName(src: string): string {
  return ({ "head_to_head.csv": "head-to-head records", "results.csv": "past results", "player_careers.csv": "player careers",
    "scoring_timeline.csv": "the scoring timeline", "club_records.csv": "club records", "standings.csv": "league tables",
    "milestones_upcoming.csv": "upcoming milestones" } as Record<string, string>)[src] ?? src;
}

function surname(name: string): string {
  return name.split(" ").slice(-1)[0];
}

/** Two or three letters for a simple fictional crest: "Arden Athletic" gives "AA". */
function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return (parts.length > 1 ? parts.map((p) => p[0]).join("") : name.slice(0, 3)).toUpperCase();
}

/** Template wording for a lens; the commentator lens reads the casual template unless an insight overrides it. */
function claimOf(p: Point, lens: Lens): string {
  return p.claim[lens === "tactical" ? "tactical" : "casual"];
}

/** Small pitch drawn in the acting team's direction (attacking to the right). */
function drawThumb(c: HTMLCanvasElement, e: Ev): void {
  const g = c.getContext("2d")!;
  const sx = c.width / 105, sy = c.height / 68;
  g.fillStyle = "#2f7a3e";
  g.fillRect(0, 0, c.width, c.height);
  g.strokeStyle = "rgba(245,248,242,0.75)";
  g.lineWidth = 1;
  g.strokeRect(0.5, 0.5, c.width - 1, c.height - 1);
  g.beginPath(); g.moveTo(c.width / 2, 0); g.lineTo(c.width / 2, c.height); g.stroke();
  g.strokeRect(0.5, (34 - 20.16) * sy, 16.5 * sx, 40.32 * sy);
  g.strokeRect(c.width - 16.5 * sx - 0.5, (34 - 20.16) * sy, 16.5 * sx, 40.32 * sy);
  if (!e.s) return;
  const P = (x: number, y: number) => {
    const rx = relX(e, x), ry = e.dir === 1 ? y : 68 - y;
    return [rx * sx, (68 - ry) * sy];
  };
  const [x0, y0] = P(e.s[0], e.s[1]);
  if (e.e) {
    const [x1, y1] = P(e.e[0], e.e[1]);
    g.strokeStyle = "#f2b33d";
    g.lineWidth = 2;
    g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
    const a = Math.atan2(y1 - y0, x1 - x0);
    g.fillStyle = "#f2b33d";
    g.beginPath();
    g.moveTo(x1, y1);
    g.lineTo(x1 - 7 * Math.cos(a - 0.4), y1 - 7 * Math.sin(a - 0.4));
    g.lineTo(x1 - 7 * Math.cos(a + 0.4), y1 - 7 * Math.sin(a + 0.4));
    g.fill();
  }
  g.fillStyle = "#ffffff";
  g.beginPath(); g.arc(x0, y0, 4, 0, Math.PI * 2); g.fill();
  g.strokeStyle = "#0d1410"; g.lineWidth = 1.5; g.stroke();
}

boot().catch((err) => {
  $("loading").textContent = `Could not load the match: ${err instanceof Error ? err.message : String(err)}`;
});

export type { Ev, Meta, Tracking };
