// Claim checker: type a claim about the match and get a verdict with tests and evidence.
// Uses POST /api/claims when the page is served with an API, otherwise the bundled offline examples.

import { clockAt } from "./data";
import type { Extras } from "./extras";
import { asPoint, ensureContainer, esc, loadData } from "./extras";

export interface ClaimResult {
  claim: string;
  t?: number;
  verdict: "supported" | "partly" | "not_supported" | "out_of_scope";
  summary: Record<string, string>;
  tests: { name: string; value: string; passes: boolean }[];
  evidence_for: string[];
  evidence_against: string[];
  check?: { passed: boolean; numbers_checked: number; retries: number };
  receipt?: { model: string | null; latency_ms: number; mode: string };
}

const VERDICT: Record<string, string> = {
  supported: "Supported",
  partly: "Partly",
  not_supported: "Not supported",
  out_of_scope: "Out of scope",
};

const TIMEOUT_MS = 15000;

export class Claims {
  private examples: ClaimResult[] = [];
  private body: HTMLElement;
  private out!: HTMLElement;
  private input!: HTMLInputElement;
  private go!: HTMLButtonElement;
  /** base URL of the claims API; empty means same origin */
  apiBase = "";
  private last: { r: ClaimResult; offline: string | null } | null = null;

  constructor(private x: Extras) {
    const panel = ensureContainer("panel-claims", "Check a claim", document.getElementById("panel-ratings"));
    this.body = document.createElement("div");
    this.body.className = "x-card";
    panel.appendChild(this.body);
    this.build();
    void this.load();
  }

  private build(): void {
    this.body.innerHTML = `
      <h2>Check a claim</h2>
      <p class="x-sub">Heard something on the broadcast or in the group chat? Sightline tests it against the match data so far.</p>
      <form class="x-claim-form">
        <label class="x-sr" for="x-claim-in">Claim to check</label>
        <input id="x-claim-in" type="text" maxlength="200" autocomplete="off" placeholder="e.g. they've lost the momentum" />
        <button class="x-btn primary" type="submit">Check</button>
      </form>
      <ul class="x-chips" aria-label="Example claims"></ul>
      <div class="x-result" aria-live="polite"></div>`;
    this.out = this.body.querySelector(".x-result")!;
    this.input = this.body.querySelector("input")!;
    this.go = this.body.querySelector("button[type=submit]")!;
    this.body.querySelector("form")!.addEventListener("submit", (e) => {
      e.preventDefault();
      void this.check(this.input.value);
    });
  }

  private async load(): Promise<void> {
    const got = await loadData<{ examples: ClaimResult[] }>("claims");
    this.examples = got?.data.examples ?? (Array.isArray(got?.data) ? (got!.data as unknown as ClaimResult[]) : []);
    const chips = this.body.querySelector(".x-chips")!;
    chips.innerHTML = this.examples.map((c, i) => `<li><button class="x-btn" type="button" data-i="${i}">${esc(c.claim)}</button></li>`).join("");
    chips.querySelectorAll<HTMLButtonElement>("button").forEach((b) =>
      b.addEventListener("click", () => {
        this.input.value = this.examples[Number(b.dataset.i)].claim;
        void this.check(this.input.value);
      }),
    );
  }

  async check(text: string): Promise<void> {
    const claim = text.trim();
    if (!claim) { this.input.focus(); return; }
    this.go.disabled = true;
    this.out.innerHTML = `<p class="x-sub">Checking.</p>`;
    const host = this.x.host;
    const t0 = performance.now();
    let result: ClaimResult | null = null;
    let offline: string | null = null;
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
      const r = await fetch(`${this.apiBase}/api/claims`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ match_id: host.meta.match_id, t: host.liveT(), claim, lens: host.lens(), lang: this.x.personal.lang }),
        signal: ctl.signal,
      });
      clearTimeout(timer);
      if (r.ok && (r.headers.get("content-type") ?? "").includes("json")) {
        const j = (await r.json()) as ClaimResult;
        if (j && j.verdict) {
          result = j;
          if (!result.receipt) result.receipt = { model: null, latency_ms: Math.round(performance.now() - t0), mode: "live" };
        }
      }
    } catch {
      /* no API here, or it timed out */
    }
    if (!result) {
      const m = this.nearest(claim);
      if (m) {
        result = m.r;
        const at = m.r.t !== undefined ? ` computed at ${clockAt(host.meta, m.r.t).text}` : "";
        offline = m.exact
          ? `Offline example${at}. No claim service is connected.`
          : `No claim service is connected, so this is the nearest offline example${at}: "${m.r.claim}".`;
      }
    }
    this.go.disabled = false;
    if (!result) {
      this.out.innerHTML = `<p class="empty">The claim service is not reachable and there are no offline examples for this match.</p>`;
      return;
    }
    this.last = { r: result, offline };
    this.render();
  }

  /** Exact match on normalised text, otherwise the example sharing the most words. */
  private nearest(claim: string): { r: ClaimResult; exact: boolean } | null {
    if (!this.examples.length) return null;
    const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();
    const words = (s: string) => new Set(norm(s).split(" ").filter((w) => w.length > 2));
    const q = norm(claim);
    const exact = this.examples.find((c) => norm(c.claim) === q);
    if (exact) return { r: exact, exact: true };
    const qw = words(claim);
    let best = this.examples[0], score = -1;
    for (const c of this.examples) {
      const cw = words(c.claim);
      let n = 0;
      qw.forEach((w) => { if (cw.has(w) || [...cw].some((x) => x.startsWith(w.slice(0, 5)))) n++; });
      const s = n / Math.max(1, new Set([...qw, ...cw]).size);
      if (s > score) { score = s; best = c; }
    }
    return { r: best, exact: false };
  }

  /** Re-render in the current lens (called when the lens changes). */
  render(): void {
    if (!this.last) return;
    const { r, offline } = this.last;
    const lens = this.x.host.lens();
    const summary = r.summary[lens] ?? r.summary.casual ?? r.summary.tactical ?? "";
    const tests = r.tests?.length
      ? `<ul class="x-tests">${r.tests
          .map((t) => `<li><span class="${t.passes ? "ok" : "no"}">${t.passes ? "Pass" : "Fail"}</span><span>${esc(t.name)}</span><span class="v">${esc(t.value)}</span></li>`)
          .join("")}</ul>`
      : "";
    const forEv = this.x.evs(r.evidence_for ?? []), againstEv = this.x.evs(r.evidence_against ?? []);
    const rc = r.receipt, ck = r.check;
    const receipt = [
      ck ? `${ck.numbers_checked} numbers checked` : "",
      ck ? `${ck.retries} ${ck.retries === 1 ? "retry" : "retries"}` : "",
      `model ${rc?.model ?? "none (precomputed)"}`,
      rc ? `${rc.latency_ms} ms` : "",
      `mode ${offline ? "offline example" : rc?.mode ?? "live"}`,
    ].filter(Boolean).join(" · ");
    this.out.innerHTML = `
      <div class="x-verdict"><b class="${esc(r.verdict)}">${esc(VERDICT[r.verdict] ?? r.verdict)}</b><span>${esc(r.claim)}</span></div>
      ${offline ? `<p class="x-mode">${esc(offline)}</p>` : ""}
      <p>${esc(summary)}</p>
      ${tests}
      <div class="x-actions">
        <button class="x-btn" type="button" data-side="for" ${forEv.length ? "" : "disabled"}>Evidence for (${forEv.length})</button>
        <button class="x-btn" type="button" data-side="against" ${againstEv.length ? "" : "disabled"}>Evidence against (${againstEv.length})</button>
      </div>
      <p class="x-receipt">${esc(receipt)}</p>`;
    this.out.querySelectorAll<HTMLButtonElement>("[data-side]").forEach((b) =>
      b.addEventListener("click", () => {
        const claim = r.claim;
        this.x.host.selectPoint(
          asPoint({
            id: `claim-${claim}`, kind: "claim", team: forEv[0]?.team ?? "", subject: null,
            claim: { casual: `"${claim}": ${VERDICT[r.verdict] ?? r.verdict}`, tactical: `"${claim}": ${VERDICT[r.verdict] ?? r.verdict}` } as never,
            stat: VERDICT[r.verdict] ?? r.verdict,
            forEv, againstEv, checked: forEv.length + againstEv.length, strength: 0,
          }),
        );
        if (b.dataset.side === "against") document.getElementById("tab-against")?.click();
        document.getElementById("reel-wrap")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
      }),
    );
  }
}
