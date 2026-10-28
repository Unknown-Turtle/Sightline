// Point detectors: claims the app can raise, each with evidence for and against.
// Everything here is deterministic code over events up to the current time.
// Agents will later phrase and check these; for now the wording is templated per lens.

import type { Ev, Meta } from "./data";
import { relX } from "./data";

export type Lens = "casual" | "tactical" | "commentator";
/** The lenses the templates are written for; the commentator lens falls back to casual wording. */
export type TextLens = "casual" | "tactical";

export interface Point {
  id: string;
  kind: "anchor" | "duel" | "finishing";
  team: string;
  subject: string | null;
  claim: Record<TextLens, string>;
  stat: string;
  forEv: Ev[];
  againstEv: Ev[];
  checked: number;
  strength: number;
}

const DEF_FOR = (e: Ev) =>
  (e.type === "tackle" && e.out === "won") ||
  e.type === "interception" || e.type === "clearance" || e.type === "block" ||
  (e.type === "ball_recovery");
const DEF_AGAINST = (e: Ev) => (e.type === "tackle" && e.out === "lost") || e.type === "dribbled_past" || e.type === "foul";

export function detectPoints(meta: Meta, events: Ev[], t: number): Point[] {
  const upto = events.filter((e) => e.t <= t);
  const name = (pid: string | null) => {
    const p = meta.players.find((x) => x.id === pid);
    return p ? p.name : "Unknown";
  };
  const surname = (pid: string | null) => name(pid).split(" ").slice(-1)[0];
  const teamName = (tid: string) => meta.teams.find((x) => x.id === tid)?.name ?? tid;
  const points: Point[] = [];

  // 1. defensive anchor
  for (const team of meta.teams) {
    const counts = new Map<string, number>();
    for (const e of upto) if (e.team === team.id && e.pl && DEF_FOR(e)) counts.set(e.pl, (counts.get(e.pl) ?? 0) + 1);
    const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    if (!ranked.length) continue;
    const [pid, n] = ranked[0];
    const next = ranked[1]?.[1] ?? 0;
    if (n < 6 || n - next < 3) continue;
    const forEv = upto.filter((e) => e.pl === pid && DEF_FOR(e));
    const againstEv = upto.filter((e) => e.pl === pid && DEF_AGAINST(e));
    points.push({
      id: `anchor-${pid}`, kind: "anchor", team: team.id, subject: pid,
      claim: {
        casual: `${surname(pid)} is holding ${teamName(team.id)}'s defence together`,
        tactical: `${name(pid)}: ${n} defensive actions, ${n - next} more than any teammate`,
      },
      stat: `${n} won, ${againstEv.length} lost`,
      forEv, againstEv, checked: forEv.length + againstEv.length, strength: n - next + n * 0.2,
    });
  }

  // 2. winning the duel: take-on record
  const tk = new Map<string, Ev[]>();
  for (const e of upto) if (e.type === "take_on" && e.pl) tk.set(e.pl, [...(tk.get(e.pl) ?? []), e]);
  const duelists = [...tk.entries()]
    .map(([pid, evs]) => ({ pid, evs, won: evs.filter((e) => e.out === "success").length }))
    .filter((d) => d.evs.length >= 4 && d.won / d.evs.length >= 0.6)
    .sort((a, b) => b.won - a.won);
  for (const d of duelists.slice(0, 2)) {
    const victims = new Map<string, number>();
    for (const e of d.evs) if (e.out === "success" && e.x.opponent_id) victims.set(e.x.opponent_id, (victims.get(e.x.opponent_id) ?? 0) + 1);
    const top = [...victims.entries()].sort((a, b) => b[1] - a[1])[0];
    const team = d.pid.split("_")[0];
    points.push({
      id: `duel-${d.pid}`, kind: "duel", team, subject: d.pid,
      claim: {
        casual: `${surname(d.pid)} keeps getting the better of his man`,
        tactical: `${name(d.pid)}: ${d.won} of ${d.evs.length} take-ons won${top && top[1] >= 2 ? `, ${top[1]} against ${surname(top[0])}` : ""}`,
      },
      stat: `${d.won} of ${d.evs.length} won`,
      forEv: d.evs.filter((e) => e.out === "success"),
      againstEv: d.evs.filter((e) => e.out !== "success"),
      checked: d.evs.length, strength: d.won * 0.8,
    });
  }

  // 3. finishing against expectation
  for (const team of meta.teams) {
    const shots = upto.filter((e) => e.type === "shot" && e.team === team.id);
    if (shots.length < 3) continue;
    const xg = shots.reduce((a, e) => a + (e.x.xg ?? 0), 0);
    const goals = shots.filter((e) => e.out === "goal");
    const diff = goals.length - xg;
    if (Math.abs(diff) < 0.8) continue;
    const hot = diff > 0;
    const misses = shots.filter((e) => e.out !== "goal" && (e.x.xg ?? 0) >= 0.15);
    points.push({
      id: `finishing-${team.id}`, kind: "finishing", team: team.id, subject: null,
      claim: {
        casual: hot ? `${teamName(team.id)} are making the most of very little` : `${teamName(team.id)} are wasting good chances`,
        tactical: `${teamName(team.id)}: ${goals.length} goal${goals.length === 1 ? "" : "s"} from ${xg.toFixed(2)} xG across ${shots.length} shots`,
      },
      stat: `${goals.length} from ${xg.toFixed(1)} xG`,
      forEv: hot ? goals : misses,
      againstEv: hot ? misses : goals,
      checked: shots.length, strength: Math.abs(diff) * 3,
    });
  }

  return points.sort((a, b) => b.strength - a.strength);
}

const LABELS: Record<string, (e: Ev) => string> = {
  tackle: (e) => (e.out === "won" ? "Tackle won" : "Tackle lost"),
  interception: () => "Interception",
  clearance: () => "Clearance",
  block: () => "Shot blocked",
  ball_recovery: () => "Loose ball won",
  dribbled_past: () => "Beaten by a dribble",
  foul: () => "Foul conceded",
  take_on: (e) => (e.out === "success" ? "Beat his man" : "Take-on lost"),
  shot: (e) => ({ goal: "Goal", saved: "Saved", off_target: "Off target", blocked: "Blocked" } as Record<string, string>)[e.out ?? ""] ?? "Shot",
};

export function cardLabel(e: Ev): string {
  return (LABELS[e.type] ?? ((x: Ev) => x.type))(e);
}

export function isGood(e: Ev, side: "for" | "against"): boolean {
  return side === "for";
}

export function zoneText(e: Ev): string {
  if (!e.s) return "";
  const rx = relX(e, e.s[0]);
  const ry = e.dir === 1 ? e.s[1] : 68 - e.s[1];
  const inOwnBox = rx < 16.5 && ry > 13.84 && ry < 54.16;
  const inOppBox = rx > 88.5 && ry > 13.84 && ry < 54.16;
  if (inOwnBox) return "in his own box";
  if (inOppBox) return "in the box";
  if (rx < 35) return "in his own third";
  if (rx < 70) return "in midfield";
  return "in the final third";
}
