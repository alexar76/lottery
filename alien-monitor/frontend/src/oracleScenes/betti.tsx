import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Billboard, Text } from "@react-three/drei";
import * as THREE from "three";

/* ===========================================================================
 *  BETTI — Persistent Homology (signature 3D scene)
 *
 *  A cloud of ~120 glowing points in 3D. A FILTRATION SCALE ε sweeps up and
 *  loops: a translucent ε-ball inflates around every point. The instant two
 *  balls touch (‖p−q‖ ≤ 2ε) the EDGE between them lights up — components merge
 *  and b0 drops. When edges enclose a planar region a LOOP is revealed as a
 *  glowing orchid RING (b1). When faces wrap a 3-D region a VOID is revealed as
 *  a shimmering hollow SHELL you see straight through (b2) — and *that* only
 *  reads as a void because the scene is genuinely 3-D: you orbit it, parallax
 *  separates the near and far shell, and the cavity is empty in the middle.
 *
 *  A live BARCODE accumulates along the bottom: thin emissive bars, one per
 *  persistence interval (cyan = H0 components, purple = H1 loops, pink = H2
 *  voids), each growing from its birth-ε to its death-ε as the sweep passes.
 *
 *  This mirrors the Vietoris-Rips filtration the oracle computes. The geometry
 *  is procedural and deterministic (seeded), built once; every frame only reads
 *  preallocated buffers, so it runs for minutes without allocating.
 * ========================================================================= */

const CYAN = new THREE.Color("#6ee7ff"); // H0 — connected components
const PURPLE = new THREE.Color("#c084fc"); // H1 — loops
const PINK = new THREE.Color("#f472b6"); // H2 — voids
const ORCHID = new THREE.Color("#f0abfc"); // accent — the live loop ring

const N_RING = 22; // points forming a clean loop (b1 = 1)
const N_SHELL = 42; // points on a sphere → a cavity (b2 = 1)
const N_SCATTER = 56; // ambient scatter giving body / extra merges
const N = N_RING + N_SHELL + N_SCATTER; // ~120 points total
const MAX_EDGES = 900; // capped edge segments for 60fps

// filtration sweep: ε rises 0→EPS_MAX, holds, resets — a looping barcode build
const EPS_MAX = 3.2;
const T_SWEEP = 11.0; // seconds to sweep ε up
const T_HOLD = 2.2; // hold at full scale (everything connected)
const T_RESET = 1.4; // ε falls back to 0
const LOOP = T_SWEEP + T_HOLD + T_RESET;

const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Pt = { p: THREE.Vector3; color: THREE.Color };
type Edge = { i: number; j: number; birth: number }; // birth = ε at which balls touch

// ---- build the point cloud: a flat loop + a 3-D shell + ambient scatter -----
function buildCloud(): { pts: Pt[]; ringIdx: number[]; shellCenter: THREE.Vector3 } {
  const rnd = mulberry32(0xbe771);
  const pts: Pt[] = [];
  const ringIdx: number[] = [];

  // (1) a tilted ring on the left — a clean topological loop (H1)
  const ringR = 2.7;
  const ringCenter = new THREE.Vector3(-4.6, 0.4, 0);
  for (let k = 0; k < N_RING; k++) {
    const a = (k / N_RING) * Math.PI * 2;
    const p = new THREE.Vector3(Math.cos(a) * ringR, Math.sin(a) * ringR * 0.92, Math.sin(a * 2) * 0.5);
    // tilt the ring so it has real depth (parallax sells the loop in 3D)
    p.applyAxisAngle(new THREE.Vector3(1, 0.4, 0).normalize(), 0.6).add(ringCenter);
    ringIdx.push(pts.length);
    pts.push({ p, color: PURPLE.clone() });
  }

  // (2) a spherical shell on the right — its hollow interior is a VOID (H2)
  const shellR = 2.5;
  const shellCenter = new THREE.Vector3(4.4, 0.2, 0);
  // Fibonacci sphere → even shell coverage so the cavity is well-bounded
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let k = 0; k < N_SHELL; k++) {
    const y = 1 - (k / (N_SHELL - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const a = k * golden;
    const p = new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r)
      .multiplyScalar(shellR)
      .add(shellCenter);
    pts.push({ p, color: PINK.clone() });
  }

  // (3) ambient scatter bridging the two so b0 visibly drops as ε rises
  for (let k = 0; k < N_SCATTER; k++) {
    const p = new THREE.Vector3(
      (rnd() - 0.5) * 16,
      (rnd() - 0.5) * 9,
      (rnd() - 0.5) * 9
    );
    pts.push({ p, color: CYAN.clone() });
  }

  return { pts, ringIdx, shellCenter };
}

// ---- precompute the Rips edges (birth ε = half the pair distance) -----------
function buildEdges(pts: Pt[]): Edge[] {
  const edges: Edge[] = [];
  for (let i = 0; i < pts.length; i++) {
    for (let j = i + 1; j < pts.length; j++) {
      const d = pts[i].p.distanceTo(pts[j].p);
      const birth = d / 2; // balls of radius ε touch when 2ε = d
      if (birth <= EPS_MAX) edges.push({ i, j, birth });
    }
  }
  edges.sort((a, b) => a.birth - b.birth);
  return edges.slice(0, MAX_EDGES);
}

const _v = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _s = new THREE.Vector3();
const _m = new THREE.Matrix4();

// =============================================================================
//  the inflating ε-balls + bright point cores (instanced)
// =============================================================================
function Points({ pts, eps }: { pts: Pt[]; eps: React.MutableRefObject<number> }) {
  const core = useRef<THREE.InstancedMesh>(null);
  const ball = useRef<THREE.InstancedMesh>(null);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const e = eps.current;
    if (core.current && (core.current as any).__n !== pts.length) {
      for (let i = 0; i < pts.length; i++) {
        core.current.setColorAt(i, pts[i].color);
        ball.current?.setColorAt(i, pts[i].color);
      }
      if (core.current.instanceColor) core.current.instanceColor.needsUpdate = true;
      if (ball.current?.instanceColor) ball.current.instanceColor.needsUpdate = true;
      (core.current as any).__n = pts.length;
    }
    for (let i = 0; i < pts.length; i++) {
      _v.copy(pts[i].p);
      _q.identity();
      const shimmer = 0.9 + 0.18 * Math.sin(t * 2.2 + i * 0.7);
      _s.setScalar(0.16 * shimmer);
      _m.compose(_v, _q, _s);
      core.current?.setMatrixAt(i, _m);
      // the ε-ball: radius literally equals the filtration scale ε
      _s.setScalar(Math.max(e, 0.0001));
      _m.compose(_v, _q, _s);
      ball.current?.setMatrixAt(i, _m);
    }
    if (core.current) {
      core.current.count = pts.length;
      core.current.instanceMatrix.needsUpdate = true;
    }
    if (ball.current) {
      ball.current.count = pts.length;
      ball.current.instanceMatrix.needsUpdate = true;
    }
  });

  return (
    <group>
      <instancedMesh ref={core} args={[undefined as any, undefined as any, N]} frustumCulled={false}>
        <sphereGeometry args={[1, 12, 12]} />
        <meshStandardMaterial vertexColors emissive={"#ffffff"} emissiveIntensity={2.2} roughness={0.3} metalness={0.4} toneMapped={false} />
      </instancedMesh>
      {/* translucent inflating filtration balls — additive, see-through */}
      <instancedMesh ref={ball} args={[undefined as any, undefined as any, N]} frustumCulled={false}>
        <sphereGeometry args={[1, 14, 14]} />
        <meshBasicMaterial vertexColors transparent opacity={0.045} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

// =============================================================================
//  the Rips edges — light up when balls touch (ε >= birth)
// =============================================================================
function Edges({ pts, edges, eps }: { pts: Pt[]; edges: Edge[]; eps: React.MutableRefObject<number> }) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(Math.max(edges.length, 1) * 6), 3));
    return g;
  }, [edges]);
  const mat = useMemo(
    () => new THREE.LineBasicMaterial({ color: CYAN.clone(), transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }),
    []
  );

  useFrame(() => {
    if (edges.length === 0) return;
    const e = eps.current;
    const arr = geom.attributes.position.array as Float32Array;
    for (let s = 0; s < edges.length; s++) {
      const ed = edges[s];
      if (ed.birth <= e) {
        const a = pts[ed.i].p;
        const b = pts[ed.j].p;
        arr[s * 6] = a.x; arr[s * 6 + 1] = a.y; arr[s * 6 + 2] = a.z;
        arr[s * 6 + 3] = b.x; arr[s * 6 + 4] = b.y; arr[s * 6 + 5] = b.z;
      } else {
        for (let k = 0; k < 6; k++) arr[s * 6 + k] = 0;
      }
    }
    geom.attributes.position.needsUpdate = true;
  });

  if (edges.length === 0) return null;
  return <lineSegments geometry={geom} material={mat} frustumCulled={false} />;
}

// =============================================================================
//  the H1 loop ring + the H2 void shell — appear in their persistence window
// =============================================================================
function Features({
  ringIdx,
  pts,
  shellCenter,
  eps,
}: {
  ringIdx: number[];
  pts: Pt[];
  shellCenter: THREE.Vector3;
  eps: React.MutableRefObject<number>;
}) {
  const ringRef = useRef<THREE.Group>(null);
  const ringMat = useRef<THREE.MeshBasicMaterial>(null);
  const voidRef = useRef<THREE.Mesh>(null);
  const voidMat = useRef<THREE.MeshBasicMaterial>(null);

  // ring centre + radius + orientation, computed once from the ring points
  const ringFit = useMemo(() => {
    const c = new THREE.Vector3();
    ringIdx.forEach((i) => c.add(pts[i].p));
    c.multiplyScalar(1 / ringIdx.length);
    let r = 0;
    ringIdx.forEach((i) => (r += pts[i].p.distanceTo(c)));
    r /= ringIdx.length;
    // plane normal via two spokes
    const a = _v.copy(pts[ringIdx[0]].p).sub(c);
    const b = new THREE.Vector3().copy(pts[ringIdx[Math.floor(ringIdx.length / 3)]].p).sub(c);
    const n = new THREE.Vector3().crossVectors(a, b).normalize();
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    return { c: c.clone(), r, q };
  }, [ringIdx, pts]);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const e = eps.current;
    // the loop is ALIVE between the ε that connects the ring and the ε that fills it
    const loopAlive = smoothstep(0.45, 0.7, e) * (1 - smoothstep(1.35, 1.7, e));
    if (ringRef.current && ringMat.current) {
      ringRef.current.position.copy(ringFit.c);
      ringRef.current.quaternion.copy(ringFit.q);
      const pulse = 1 + Math.sin(t * 3) * 0.04;
      ringRef.current.scale.setScalar(ringFit.r * pulse);
      ringMat.current.opacity = clamp(loopAlive, 0, 1) * 0.9;
    }
    // the void is alive once the shell's faces close (ε spans the gap) until it fills
    const voidAlive = smoothstep(0.85, 1.15, e) * (1 - smoothstep(2.2, 2.7, e));
    if (voidRef.current && voidMat.current) {
      voidRef.current.position.copy(shellCenter);
      voidRef.current.rotation.y = t * 0.25;
      voidRef.current.scale.setScalar(2.5 * (1 + Math.sin(t * 2) * 0.02));
      voidMat.current.opacity = clamp(voidAlive, 0, 1) * 0.34;
    }
  });

  return (
    <group>
      {/* H1 — the glowing orchid loop ring (a torus lying in the ring's plane) */}
      <group ref={ringRef}>
        <mesh>
          <torusGeometry args={[1, 0.04, 10, 80]} />
          <meshBasicMaterial ref={ringMat} color={ORCHID} transparent opacity={0} toneMapped={false} blending={THREE.AdditiveBlending} depthWrite={false} />
        </mesh>
      </group>

      {/* H2 — the hollow shimmering shell; back-side render so you see THROUGH it */}
      <mesh ref={voidRef}>
        <icosahedronGeometry args={[1, 2]} />
        <meshBasicMaterial
          ref={voidMat}
          color={PINK}
          transparent
          opacity={0}
          wireframe
          toneMapped={false}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>
    </group>
  );
}

// =============================================================================
//  the live BARCODE along the bottom — thin emissive bars per persistence bar
// =============================================================================
type Bar = { dim: 0 | 1 | 2; birth: number; death: number; row: number };

function Barcode({ bars, eps }: { bars: Bar[]; eps: React.MutableRefObject<number> }) {
  const X0 = -7.5; // barcode left edge (world X)
  const W = 15; // barcode width
  const Y0 = -6.2; // baseline Y
  const ROW_H = 0.34;

  const refs = useRef<(THREE.Mesh | null)[]>([]);
  const xFor = (e: number) => X0 + (e / EPS_MAX) * W;

  useFrame(() => {
    const e = eps.current;
    for (let k = 0; k < bars.length; k++) {
      const m = refs.current[k];
      if (!m) continue;
      const bar = bars[k];
      // the bar grows from its birth-ε up to min(current ε, death-ε)
      const right = Math.min(e, bar.death);
      const len = Math.max(0, xFor(right) - xFor(bar.birth));
      m.scale.x = Math.max(len, 0.0001);
      m.position.x = xFor(bar.birth) + len / 2;
      m.position.y = Y0 + bar.row * ROW_H;
      const visible = e >= bar.birth;
      (m.material as THREE.MeshBasicMaterial).opacity = visible ? 0.95 : 0;
    }
  });

  const colorFor = (d: 0 | 1 | 2) => (d === 0 ? CYAN : d === 1 ? PURPLE : PINK);

  return (
    <group>
      {/* sweep playhead — a vertical tick marking the current ε */}
      <SweepTick eps={eps} X0={X0} W={W} Y0={Y0} />
      {bars.map((b, k) => (
        <mesh key={k} ref={(m) => (refs.current[k] = m)} position={[0, Y0 + b.row * ROW_H, 0]}>
          <boxGeometry args={[1, 0.12, 0.05]} />
          <meshBasicMaterial color={colorFor(b.dim)} transparent opacity={0} toneMapped={false} blending={THREE.AdditiveBlending} depthWrite={false} />
        </mesh>
      ))}
    </group>
  );
}

function SweepTick({
  eps,
  X0,
  W,
  Y0,
}: {
  eps: React.MutableRefObject<number>;
  X0: number;
  W: number;
  Y0: number;
}) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(() => {
    if (!ref.current) return;
    ref.current.position.x = X0 + (eps.current / EPS_MAX) * W;
  });
  return (
    <mesh ref={ref} position={[X0, Y0 + 1.4, 0]}>
      <boxGeometry args={[0.03, 3.4, 0.03]} />
      <meshBasicMaterial color={ORCHID} transparent opacity={0.55} toneMapped={false} blending={THREE.AdditiveBlending} depthWrite={false} />
    </mesh>
  );
}

// =============================================================================
//  main scene
// =============================================================================
export default function Scene() {
  const group = useRef<THREE.Group>(null);
  const { pts, ringIdx, shellCenter } = useMemo(buildCloud, []);
  const edges = useMemo(() => buildEdges(pts), [pts]);

  // a curated set of persistence bars for the barcode (their births derive from
  // the real edge filtration; the long bars are the loop & void features).
  const bars = useMemo<Bar[]>(() => {
    const out: Bar[] = [];
    // H0 components: many short bars dying as edges connect the cloud, plus one
    // essential bar that lives to EPS_MAX (the final single component).
    const comp = edges.slice(0, 26).map((e) => e.birth).sort((a, b) => a - b);
    comp.forEach((birth) => {
      out.push({ dim: 0, birth: birth * 0.4, death: birth + 0.05, row: 0 });
    });
    out.push({ dim: 0, birth: 0, death: EPS_MAX, row: 1 }); // the surviving component
    // H1 loop: born when the ring connects, dies when it fills.
    out.push({ dim: 1, birth: 0.55, death: 1.55, row: 2 });
    // H2 void: born when the shell closes, dies when it fills.
    out.push({ dim: 2, birth: 1.0, death: 2.45, row: 3 });
    return out;
  }, [edges]);

  const eps = useRef(0);
  const life = useRef({ phase: "sweep" as "sweep" | "hold" | "reset", t: 0 });

  useFrame((_, rawDelta) => {
    const d = Math.min(rawDelta, 0.05);
    const L = life.current;
    L.t += d;
    if (L.phase === "sweep") {
      eps.current = (L.t / T_SWEEP) * EPS_MAX;
      if (L.t >= T_SWEEP) {
        eps.current = EPS_MAX;
        L.phase = "hold";
        L.t = 0;
      }
    } else if (L.phase === "hold") {
      if (L.t >= T_HOLD) {
        L.phase = "reset";
        L.t = 0;
      }
    } else {
      eps.current = EPS_MAX * (1 - L.t / T_RESET);
      if (L.t >= T_RESET) {
        eps.current = 0;
        L.phase = "sweep";
        L.t = 0;
      }
    }

    // gentle drift on top of the canvas auto-rotate (depth/parallax for the void)
    if (group.current) {
      group.current.rotation.y += d * 0.04;
      group.current.rotation.x = -0.12 + Math.sin(performance.now() * 0.00012) * 0.05;
    }
  });

  return (
    <group ref={group}>
      <Edges pts={pts} edges={edges} eps={eps} />
      <Points pts={pts} eps={eps} />
      <Features ringIdx={ringIdx} pts={pts} shellCenter={shellCenter} eps={eps} />
      <Barcode bars={bars} eps={eps} />

      {/* scene label */}
      <Billboard position={[0, -7.2, 0]}>
        <Text fontSize={0.62} color="#f0abfc" anchorX="center" anchorY="middle" outlineWidth={0.012} outlineColor="#120420">
          {"H0  H1  H2  ·  persistent homology"}
        </Text>
        <Text position={[0, -0.74, 0]} fontSize={0.3} color="#c084fc" anchorX="center" anchorY="middle" outlineWidth={0.008} outlineColor="#120420">
          {"Vietoris–Rips filtration · the shape of a point cloud"}
        </Text>
      </Billboard>

      {/* barcode legend */}
      <Billboard position={[-7.4, -4.4, 0]}>
        <Text fontSize={0.26} color="#6ee7ff" anchorX="left" anchorY="middle" outlineWidth={0.008} outlineColor="#04121a">
          {"b0 components · b1 loops · b2 voids"}
        </Text>
      </Billboard>
    </group>
  );
}
