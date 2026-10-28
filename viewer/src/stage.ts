// The 3D match stage: floodlit pitch, stylised players with procedural animation,
// broadcast and tactical cameras, and screen-space anchors for HTML overlays.

import * as THREE from "three";
import type { Ev, Meta, Sample, Tracking } from "./data";

const S = 1.55; // figure scale; real-size players vanish at broadcast distance
const GK_COLOURS: Record<string, string> = { ARD: "#e8c21a", HVL: "#2bb673" };

export type CameraMode = "broadcast" | "tactical";

interface Action { t: number; kind: "kick" | "jump" | "slide" | "dive" | "celebrate"; dur: number }

interface Figure {
  root: THREE.Group;
  disc: THREE.Mesh;
  body: THREE.Group;
  legL: THREE.Object3D;
  legR: THREE.Object3D;
  yaw: number;
  phase: number;
  actions: Action[];
  lastX: number;
  lastY: number;
}

// pitch (x 0..105, y 0..68) to world: X = x - 52.5, Z = 34 - y (y = 0 is the near touchline)
export const toWorld = (x: number, y: number, h = 0) => new THREE.Vector3(x - 52.5, h, 34 - y);

export class Stage {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(28, 16 / 9, 0.5, 600);
  private figures: Figure[] = [];
  private ball!: THREE.Mesh;
  private ballShadow!: THREE.Mesh;
  private focusRing!: THREE.Mesh;
  private pressRing!: THREE.Mesh;
  private lineStrip!: THREE.Mesh;
  private trails: { mesh: THREE.Mesh; born: number; ev: Ev | null }[] = [];
  private camTarget = new THREE.Vector3();
  private camPos = new THREE.Vector3(0, 30, 70);
  mode: CameraMode = "broadcast";
  lens: "casual" | "tactical" = "casual";
  focus: string | null = null;
  readonly sample: Sample;
  private index = new Map<string, number>();

  constructor(private canvas: HTMLCanvasElement, private meta: Meta, private tracking: Tracking, events: Ev[]) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.sample = tracking.newSample();
    meta.tracking.order.forEach((id, i) => this.index.set(id, i));
    this.buildWorld();
    this.buildPlayers(events);
  }

  // ------------------------------------------------------------------ world
  private buildWorld(): void {
    const s = this.scene;
    s.background = new THREE.Color("#0a1310");
    s.fog = new THREE.Fog("#0a1310", 140, 320);

    s.add(new THREE.HemisphereLight("#c8d6ff", "#1c2a1f", 0.9));
    const sun = new THREE.DirectionalLight("#fff4e0", 2.4);
    sun.position.set(-30, 80, 45);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const sc = sun.shadow.camera as THREE.OrthographicCamera;
    sc.left = -62; sc.right = 62; sc.top = 45; sc.bottom = -45; sc.near = 10; sc.far = 200;
    sun.shadow.bias = -0.0005;
    s.add(sun);
    const fill = new THREE.DirectionalLight("#b9c9ff", 0.6);
    fill.position.set(40, 50, -50);
    s.add(fill);

    // surround
    const apron = new THREE.Mesh(new THREE.PlaneGeometry(150, 110), new THREE.MeshStandardMaterial({ color: "#163222", roughness: 1 }));
    apron.rotation.x = -Math.PI / 2;
    apron.position.y = -0.02;
    apron.receiveShadow = true;
    s.add(apron);

    const pitch = new THREE.Mesh(new THREE.PlaneGeometry(105, 68), new THREE.MeshStandardMaterial({ map: pitchTexture(), roughness: 0.95 }));
    pitch.rotation.x = -Math.PI / 2;
    pitch.receiveShadow = true;
    s.add(pitch);

    // stands: stepped tiers with a speckled crowd texture
    const crowd = crowdTexture();
    const standMat = new THREE.MeshStandardMaterial({ map: crowd, roughness: 1, color: "#9aa3a0" });
    const shellMat = new THREE.MeshStandardMaterial({ color: "#1b2420", roughness: 1 });
    const addStand = (w: number, x: number, z: number, rotY: number) => {
      const g = new THREE.Group();
      for (let k = 0; k < 4; k++) {
        const tier = new THREE.Mesh(new THREE.BoxGeometry(w, 2.4, 5), k % 2 ? shellMat : standMat);
        tier.position.set(0, 1.2 + k * 2.6, -k * 5);
        g.add(tier);
      }
      const roof = new THREE.Mesh(new THREE.BoxGeometry(w + 4, 0.6, 22), shellMat);
      roof.position.set(0, 13.5, -9);
      g.add(roof);
      g.position.set(x, 0, z);
      g.rotation.y = rotY;
      s.add(g);
    };
    addStand(120, 0, -48, 0);
    addStand(120, 0, 48, Math.PI);
    addStand(84, -66, 0, Math.PI / 2);
    addStand(84, 66, 0, -Math.PI / 2);

    // floodlight pylons
    const glow = new THREE.MeshBasicMaterial({ color: "#fff6d8" });
    for (const [x, z] of [[-64, -46], [64, -46], [-64, 46], [64, 46]]) {
      const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.7, 34, 8), shellMat);
      mast.position.set(x, 17, z);
      s.add(mast);
      const head = new THREE.Mesh(new THREE.BoxGeometry(6, 3, 0.6), glow);
      head.position.set(x, 35, z);
      head.lookAt(0, 0, 0);
      s.add(head);
    }

    // goals
    const postMat = new THREE.MeshStandardMaterial({ color: "#f4f6f2", roughness: 0.4 });
    const netMat = new THREE.MeshBasicMaterial({ color: "#dfe6e0", wireframe: true, transparent: true, opacity: 0.35 });
    for (const side of [-1, 1]) {
      const g = new THREE.Group();
      const post = new THREE.CylinderGeometry(0.07, 0.07, 2.44, 8);
      for (const zz of [-3.66, 3.66]) {
        const m = new THREE.Mesh(post, postMat);
        m.position.set(0, 1.22, zz);
        m.castShadow = true;
        g.add(m);
      }
      const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 7.32, 8), postMat);
      bar.rotation.x = Math.PI / 2;
      bar.position.set(0, 2.44, 0);
      g.add(bar);
      const net = new THREE.Mesh(new THREE.BoxGeometry(2, 2.44, 7.32, 4, 4, 8), netMat);
      net.position.set(side * 1, 1.22, 0);
      g.add(net);
      g.position.set(side * 52.5, 0, 0);
      s.add(g);
    }

    // ball and its shadow
    this.ball = new THREE.Mesh(new THREE.SphereGeometry(0.11 * S * 1.3, 16, 12), new THREE.MeshStandardMaterial({ color: "#fbfbf6", roughness: 0.35, emissive: "#30302a" }));
    this.ball.castShadow = true;
    s.add(this.ball);
    this.ballShadow = new THREE.Mesh(new THREE.CircleGeometry(0.28, 16), new THREE.MeshBasicMaterial({ color: "#000000", transparent: true, opacity: 0.35 }));
    this.ballShadow.rotation.x = -Math.PI / 2;
    this.ballShadow.position.y = 0.02;
    s.add(this.ballShadow);

    // rings and the defensive line strip
    this.focusRing = ring(1.25 * S / 1.55, "#f2b33d", 0.95);
    this.pressRing = ring(1.6, "#ff7a45", 0.7);
    s.add(this.focusRing, this.pressRing);
    this.lineStrip = new THREE.Mesh(new THREE.PlaneGeometry(0.35, 68), new THREE.MeshBasicMaterial({ color: "#7fd6ff", transparent: true, opacity: 0.55, depthWrite: false }));
    this.lineStrip.rotation.x = -Math.PI / 2;
    this.lineStrip.position.y = 0.03;
    s.add(this.lineStrip);

    for (let i = 0; i < 6; i++) {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(1, 0.32), new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0, depthWrite: false }));
      m.rotation.x = -Math.PI / 2;
      m.position.y = 0.04;
      s.add(m);
      this.trails.push({ mesh: m, born: -99, ev: null });
    }
  }

  // ---------------------------------------------------------------- players
  private buildPlayers(events: Ev[]): void {
    const byPlayer = new Map<string, Action[]>();
    const push = (pid: string | null, a: Action) => {
      if (!pid) return;
      if (!byPlayer.has(pid)) byPlayer.set(pid, []);
      byPlayer.get(pid)!.push(a);
    };
    for (const e of events) {
      if (["pass", "shot", "clearance"].includes(e.type)) {
        const header = e.bp === "head";
        push(e.pl, { t: e.t, kind: header ? "jump" : "kick", dur: 0.55 });
      } else if (e.type === "aerial_duel") push(e.pl, { t: e.t, kind: "jump", dur: 0.7 });
      else if (e.type === "tackle" && e.out === "won") push(e.pl, { t: e.t, kind: "slide", dur: 0.9 });
      else if (e.type === "goalkeeper" && e.out === "save") push(e.pl, { t: e.t, kind: "dive", dur: 1.2 });
      else if (e.type === "goalkeeper") push(e.pl, { t: e.t, kind: "jump", dur: 0.7 });
      else if (e.type === "goal") push(e.pl, { t: e.t + 0.6, kind: "celebrate", dur: 6 });
    }
    for (const list of byPlayer.values()) list.sort((a, b) => a.t - b.t);

    const teamColour = new Map(this.meta.teams.map((t) => [t.id, t.colour]));
    for (const id of this.meta.tracking.order) {
      const pm = this.meta.players.find((p) => p.id === id)!;
      const base = pm.pos === "GK" ? GK_COLOURS[pm.team] ?? "#dddddd" : teamColour.get(pm.team) ?? "#888888";
      const shirt = new THREE.MeshStandardMaterial({ color: base, roughness: 0.6 });
      const shorts = new THREE.MeshStandardMaterial({ color: new THREE.Color(base).multiplyScalar(0.35), roughness: 0.8 });
      const headMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(base).lerp(new THREE.Color("#f0efe8"), 0.75), roughness: 0.7 });

      const root = new THREE.Group();
      const body = new THREE.Group();
      root.add(body);
      const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.3 * S, 0.62 * S, 4, 10), shirt);
      torso.position.y = 1.22 * S;
      torso.castShadow = true;
      body.add(torso);
      const head = new THREE.Mesh(new THREE.SphereGeometry(0.2 * S, 14, 10), headMat);
      head.position.y = 1.86 * S;
      head.castShadow = true;
      body.add(head);
      // number on the back
      const num = new THREE.Mesh(new THREE.PlaneGeometry(0.42 * S, 0.42 * S), new THREE.MeshBasicMaterial({ map: numberTexture(pm.number), transparent: true }));
      num.position.set(0, 1.3 * S, -0.31 * S);
      num.rotation.y = Math.PI;
      body.add(num);
      const mkLeg = (side: number) => {
        const hip = new THREE.Object3D();
        hip.position.set(0.13 * S * side, 0.82 * S, 0);
        const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.1 * S, 0.62 * S, 3, 8), shorts);
        leg.position.y = -0.4 * S;
        leg.castShadow = true;
        hip.add(leg);
        body.add(hip);
        return hip;
      };
      const legL = mkLeg(-1), legR = mkLeg(1);
      const disc = new THREE.Mesh(new THREE.CircleGeometry(1.15, 24), new THREE.MeshBasicMaterial({ color: base, depthWrite: false }));
      disc.rotation.x = -Math.PI / 2;
      disc.position.y = 0.06;
      disc.visible = false;
      root.add(disc);
      root.visible = false;
      this.scene.add(root);
      this.figures.push({ root, disc, body, legL, legR, yaw: 0, phase: Math.random() * 6, actions: byPlayer.get(id) ?? [], lastX: NaN, lastY: NaN });
    }
  }

  // ---------------------------------------------------------------- update
  update(t: number, dt: number, carrierHint: string | null, recent: Ev[]): void {
    const smp = this.sample;
    this.tracking.sample(t, smp);
    const [bx, by, bz] = smp.ball;
    this.ball.position.copy(toWorld(bx, by, 0.11 * S * 1.3 + bz));
    this.ballShadow.position.set(bx - 52.5, 0.02, 34 - by);
    (this.ballShadow.material as THREE.MeshBasicMaterial).opacity = Math.max(0.08, 0.35 - bz * 0.04);

    const order = this.meta.tracking.order;
    for (let i = 0; i < this.figures.length; i++) {
      const f = this.figures[i];
      const x = smp.pos[2 * i], y = smp.pos[2 * i + 1];
      if (Number.isNaN(x)) { f.root.visible = false; f.lastX = NaN; continue; }
      f.root.visible = true;
      f.disc.visible = this.mode === "tactical";
      const w = toWorld(x, y);
      f.root.position.set(w.x, 0, w.z);
      const speed = smp.speed[i] / 3.6; // m/s
      // facing: movement direction when running, otherwise the ball
      let targetYaw = f.yaw;
      if (!Number.isNaN(f.lastX)) {
        const vx = x - f.lastX, vy = y - f.lastY;
        if (speed > 1.2 && Math.hypot(vx, vy) > 1e-4) targetYaw = Math.atan2(vx, -vy);
        else targetYaw = Math.atan2(bx - x, -(by - y));
      }
      f.lastX = x; f.lastY = y;
      f.yaw = lerpAngle(f.yaw, targetYaw, Math.min(1, Math.abs(dt) * 6 + 0.05));
      f.root.rotation.y = f.yaw;

      // run cycle
      f.phase += Math.abs(dt) * (2 + speed * 1.6);
      const swing = Math.min(0.9, speed * 0.12);
      let legL = Math.sin(f.phase) * swing, legR = -Math.sin(f.phase) * swing;
      let bodyY = Math.abs(Math.sin(f.phase)) * swing * 0.12;
      let tiltX = speed * 0.02, tiltZ = 0;

      // action clip, if one is running at time t
      const a = activeAction(f.actions, t);
      if (a) {
        const u = (t - a.t) / a.dur; // 0..1
        const env = Math.sin(Math.PI * Math.min(1, Math.max(0, u)));
        if (a.kind === "kick") { legR = -1.3 * env + 0.4 * env * env; legL = 0.25 * env; tiltX -= 0.15 * env; }
        else if (a.kind === "jump") { bodyY += 0.9 * env; legL = 0.3 * env; legR = 0.3 * env; }
        else if (a.kind === "slide") { tiltX = -1.2 * env; bodyY -= 0.5 * env; legR = -1.4 * env; legL = -0.6 * env; }
        else if (a.kind === "dive") { tiltZ = 1.35 * env * (bz > 1 ? 1 : -1); bodyY += 0.6 * env; }
        else if (a.kind === "celebrate") { bodyY += Math.abs(Math.sin(u * Math.PI * 8)) * 0.6 * (1 - u); }
      }
      f.legL.rotation.x = legL;
      f.legR.rotation.x = legR;
      f.body.position.y = bodyY;
      f.body.rotation.x = tiltX;
      f.body.rotation.z = tiltZ;
    }

    // focus ring
    const fi = this.focus ? this.index.get(this.focus) : undefined;
    if (fi !== undefined && !Number.isNaN(smp.pos[2 * fi])) {
      this.focusRing.visible = true;
      this.focusRing.position.copy(toWorld(smp.pos[2 * fi], smp.pos[2 * fi + 1], 0.05));
    } else this.focusRing.visible = false;

    // tactical layer: pressure ring on the carrier, defensive line, pass trails
    const tactical = this.lens === "tactical";
    const ci = carrierHint ? this.index.get(carrierHint) : undefined;
    this.pressRing.visible = false;
    if (tactical && ci !== undefined && !Number.isNaN(smp.pos[2 * ci])) {
      const cx = smp.pos[2 * ci], cy = smp.pos[2 * ci + 1];
      const team = order[ci].split("_")[0];
      let near = 99;
      for (let j = 0; j < order.length; j++) {
        if (order[j].startsWith(team) || Number.isNaN(smp.pos[2 * j])) continue;
        near = Math.min(near, Math.hypot(smp.pos[2 * j] - cx, smp.pos[2 * j + 1] - cy));
      }
      if (near < 4) {
        this.pressRing.visible = true;
        this.pressRing.position.copy(toWorld(cx, cy, 0.04));
        const k = 1 + (4 - near) * 0.12;
        this.pressRing.scale.set(k, k, k);
      }
    }
    this.lineStrip.visible = false;
    if (tactical && ci !== undefined) {
      const attacking = order[ci].split("_")[0];
      const defending = this.meta.teams.find((tm) => tm.id !== attacking)!.id;
      const dir = this.attackDir(defending, t);
      let deepest = dir === 1 ? 999 : -999;
      for (let j = 0; j < order.length; j++) {
        if (!order[j].startsWith(defending) || Number.isNaN(smp.pos[2 * j])) continue;
        const pm = this.meta.players[j];
        if (pm.pos === "GK") continue;
        const px = smp.pos[2 * j];
        deepest = dir === 1 ? Math.min(deepest, px) : Math.max(deepest, px);
      }
      if (Math.abs(deepest) < 200) {
        this.lineStrip.visible = true;
        this.lineStrip.position.x = deepest - 52.5;
      }
    }
    for (const tr of this.trails) {
      const age = t - tr.born;
      const mat = tr.mesh.material as THREE.MeshBasicMaterial;
      mat.opacity = tactical && tr.ev && age >= 0 && age < 4 ? 0.75 * (1 - age / 4) : 0;
    }
    if (tactical) for (const ev of recent) this.addTrail(ev);

    this.updateCamera(dt);
  }

  private attackDir(team: string, t: number): number {
    const p2 = this.meta.periods[1];
    const period = p2 && t >= p2.start ? "2" : "1";
    return this.meta.attack_direction[period][team];
  }

  private addTrail(ev: Ev): void {
    if (!ev.s || !ev.e || this.trails.some((x) => x.ev === ev)) return;
    const slot = this.trails.reduce((a, b) => (a.born < b.born ? a : b));
    const a = toWorld(ev.s[0], ev.s[1], 0.04), b = toWorld(ev.e[0], ev.e[1], 0.04);
    const len = a.distanceTo(b);
    slot.mesh.scale.set(Math.max(0.5, len), 1, 1);
    slot.mesh.position.set((a.x + b.x) / 2, 0.04, (a.z + b.z) / 2);
    slot.mesh.rotation.set(-Math.PI / 2, 0, -Math.atan2(b.z - a.z, b.x - a.x));
    const ok = ev.out === "complete";
    (slot.mesh.material as THREE.MeshBasicMaterial).color.set(ok ? "#f4f7f3" : "#ff7a45");
    slot.born = ev.t;
    slot.ev = ev;
  }

  private updateCamera(dt: number): void {
    const [bx, by] = this.sample.ball;
    const k = 1 - Math.exp(-Math.max(0.016, Math.abs(dt)) * 2.2);
    if (this.mode === "broadcast") {
      const tx = (bx - 52.5) * 0.92, tz = (34 - by) * 0.45;
      this.camTarget.lerp(new THREE.Vector3(tx, 0, tz), k);
      this.camPos.lerp(new THREE.Vector3(this.camTarget.x * 0.82, 30, 66), k);
      this.camera.fov = 26;
    } else {
      this.camTarget.lerp(new THREE.Vector3(0, 0, 0), 0.2);
      this.camPos.lerp(new THREE.Vector3(0, 104, 34), 0.2);
      this.camera.fov = 42;
    }
    this.camera.position.copy(this.camPos);
    this.camera.lookAt(this.camTarget);
    this.camera.updateProjectionMatrix();
  }

  snapCamera(): void {
    const [bx, by] = this.sample.ball;
    if (this.mode === "broadcast") {
      this.camTarget.set((bx - 52.5) * 0.92, 0, (34 - by) * 0.45);
      this.camPos.set(this.camTarget.x * 0.82, 30, 66);
    } else {
      this.camTarget.set(0, 0, 0);
      this.camPos.set(0, 104, 34);
    }
  }

  resize(w: number, h: number): void {
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  render(): void {
    this.renderer.render(this.scene, this.camera);
  }

  /** Screen position (CSS px) above a player's head, or null when off screen or off the pitch. */
  project(pid: string, w: number, h: number): { x: number; y: number } | null {
    const i = this.index.get(pid);
    if (i === undefined) return null;
    const x = this.sample.pos[2 * i], y = this.sample.pos[2 * i + 1];
    if (Number.isNaN(x)) return null;
    const v = toWorld(x, y, 2.35 * S).project(this.camera);
    if (v.z > 1 || v.x < -1.1 || v.x > 1.1 || v.y < -1.1 || v.y > 1.1) return null;
    return { x: (v.x * 0.5 + 0.5) * w, y: (-v.y * 0.5 + 0.5) * h };
  }

  projectPoint(px: number, py: number, w: number, h: number, height = 0): { x: number; y: number } | null {
    const v = toWorld(px, py, height).project(this.camera);
    if (v.z > 1) return null;
    return { x: (v.x * 0.5 + 0.5) * w, y: (-v.y * 0.5 + 0.5) * h };
  }

  speedOf(pid: string): number {
    const i = this.index.get(pid);
    return i === undefined ? 0 : this.sample.speed[i];
  }
}

function activeAction(list: Action[], t: number): Action | null {
  // binary search for the last action starting at or before t
  let lo = 0, hi = list.length - 1, best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (list[mid].t - 0.25 <= t) { best = mid; lo = mid + 1; } else hi = mid - 1;
  }
  for (let k = best; k >= 0 && k > best - 3; k--) {
    const a = list[k];
    const start = a.t - 0.25;
    if (t >= start && t <= start + a.dur) return { ...a, t: start };
  }
  return null;
}

function lerpAngle(a: number, b: number, k: number): number {
  let d = b - a;
  while (d > Math.PI) d -= Math.PI * 2;
  while (d < -Math.PI) d += Math.PI * 2;
  return a + d * k;
}

function ring(r: number, colour: string, opacity: number): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.RingGeometry(r * 0.8, r, 40), new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  m.visible = false;
  return m;
}

function pitchTexture(): THREE.CanvasTexture {
  const ppm = 20; // pixels per metre
  const c = document.createElement("canvas");
  c.width = 105 * ppm; c.height = 68 * ppm;
  const g = c.getContext("2d")!;
  for (let i = 0; i < 14; i++) {
    g.fillStyle = i % 2 ? "#2f7a3e" : "#347f43";
    g.fillRect((i * c.width) / 14, 0, c.width / 14 + 1, c.height);
  }
  g.strokeStyle = "rgba(248,250,245,0.92)";
  g.lineWidth = 0.12 * ppm;
  const P = (m: number) => m * ppm;
  g.strokeRect(P(0.1), P(0.1), P(104.8), P(67.8));
  g.beginPath(); g.moveTo(P(52.5), 0); g.lineTo(P(52.5), P(68)); g.stroke();
  g.beginPath(); g.arc(P(52.5), P(34), P(9.15), 0, Math.PI * 2); g.stroke();
  const spot = (x: number, y: number) => { g.beginPath(); g.arc(P(x), P(y), P(0.25), 0, Math.PI * 2); g.fillStyle = "rgba(248,250,245,0.92)"; g.fill(); };
  spot(52.5, 34);
  for (const side of [0, 1]) {
    const x0 = side ? 105 - 16.5 : 0;
    g.strokeRect(P(x0), P(34 - 20.16), P(16.5), P(40.32));
    const x1 = side ? 105 - 5.5 : 0;
    g.strokeRect(P(x1), P(34 - 9.16), P(5.5), P(18.32));
    const ps = side ? 105 - 11 : 11;
    spot(ps, 34);
    g.beginPath();
    const a = Math.acos(5.5 / 9.15);
    if (side) g.arc(P(ps), P(34), P(9.15), Math.PI - a, Math.PI + a);
    else g.arc(P(ps), P(34), P(9.15), -a, a);
    g.stroke();
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

function crowdTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 64;
  const g = c.getContext("2d")!;
  g.fillStyle = "#1d2622";
  g.fillRect(0, 0, c.width, c.height);
  const cols = ["#c8102e", "#1d4e89", "#d8d8d0", "#37423d", "#55605a", "#8a6f5a"];
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < 2600; i++) {
    g.fillStyle = cols[Math.floor(rnd() * cols.length)];
    g.fillRect(rnd() * c.width, rnd() * c.height, 2, 2);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.repeat.set(6, 1);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function numberTexture(n: number): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  g.fillStyle = "#ffffff";
  g.font = "700 46px 'Saira Condensed', 'Arial Narrow', sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(String(n), 32, 35);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}
