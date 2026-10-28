// Loading and selecting AI insights (see INSIGHTS.md). If data/insights.json is missing or
// invalid the viewer falls back to data/insights.sample.json, and if that is missing too the
// app runs on its templated points exactly as before.

import type { Lens } from "./points";

export type InsightKind = "anchor" | "duel" | "finishing" | "momentum" | "score_state" | "recap";

export interface Trivia { text: string; source: string; row?: string }
export interface Insight {
  id: string;
  t: number;
  clock: string;
  kind: InsightKind;
  point_id: string;
  team: string;
  subject: string | null;
  text: { casual: string; tactical: string; commentator: string };
  evidence_for: string[];
  evidence_against: string[];
  trivia?: Trivia[];
  check: { passed: boolean; numbers_checked: number; retries: number; issues?: string[] };
  receipt: { model: string | null; latency_ms: number; tokens_in?: number; tokens_out?: number; agents?: string[] };
}
export interface InsightFile {
  match_id: string;
  generated_at: string;
  mode: "live" | "fallback";
  model: string | null;
  items: Insight[];
}

/** The kinds that appear as their own rail items rather than replacing a template point. */
export const STANDALONE: ReadonlySet<string> = new Set(["momentum", "score_state", "recap"]);

const KINDS: ReadonlySet<string> = new Set(["anchor", "duel", "finishing", "momentum", "score_state", "recap"]);

function valid(raw: unknown): raw is InsightFile {
  if (!raw || typeof raw !== "object") return false;
  const f = raw as Partial<InsightFile>;
  if (!Array.isArray(f.items)) return false;
  return f.items.every(
    (i) =>
      i && typeof i.id === "string" && typeof i.t === "number" && KINDS.has(i.kind) &&
      typeof i.point_id === "string" && i.text && typeof i.text.casual === "string" &&
      Array.isArray(i.evidence_for) && Array.isArray(i.evidence_against) && i.check && i.receipt,
  );
}

/** Load insights.json, else the sample fixture, else null. Never throws. */
export async function loadInsights(base = "data/"): Promise<{ file: InsightFile; source: "insights.json" | "sample" } | null> {
  for (const [name, source] of [["insights.json", "insights.json"], ["insights.sample.json", "sample"]] as const) {
    try {
      const r = await fetch(base + name, { cache: "no-store" });
      if (!r.ok) continue;
      const raw: unknown = await r.json();
      if (!valid(raw)) continue;
      const file = raw;
      file.items = [...file.items].sort((a, b) => a.t - b.t || a.id.localeCompare(b.id));
      return { file, source };
    } catch {
      // missing, unreachable or not JSON: try the next one
    }
  }
  return null;
}

/** Newest item per point_id with t at or before the live time. */
export function currentInsights(file: InsightFile | null, t: number): Map<string, Insight> {
  const out = new Map<string, Insight>();
  if (!file) return out;
  for (const i of file.items) {
    if (i.t > t) break;
    out.set(i.point_id, i);
  }
  return out;
}

export function textFor(i: Insight, lens: Lens): string {
  return i.text[lens] || i.text.casual;
}

/** "Checked: 4 numbers, 0 retries. model, 1.8 s" */
export function receiptLine(i: Insight): string {
  const n = i.check.numbers_checked;
  const r = i.check.retries;
  const model = i.receipt.model ?? "no model";
  const lat = i.receipt.latency_ms >= 1000 ? `${(i.receipt.latency_ms / 1000).toFixed(1)} s` : `${i.receipt.latency_ms} ms`;
  return `Checked: ${n} number${n === 1 ? "" : "s"}, ${r} retr${r === 1 ? "y" : "ies"}. ${model}, ${lat}`;
}
