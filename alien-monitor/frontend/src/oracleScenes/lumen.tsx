import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Billboard, Instance, Instances, Line, Text } from "@react-three/drei";
import * as THREE from "three";

/**
 * LUMEN — reputation / trust scoring (EigenTrust · PageRank), made luminous.
 *
 * The real concept: a directed weighted trust graph i -> j ("i trusts j with
 * weight w") becomes a column-stochastic transition matrix M, folded into the
 * Google matrix G = d·M + (1-d)/n, whose dominant eigenvector (found by power
 * iteration of a damped random walk) is the reputation vector. Nodes *trusted
 * by trusted nodes* score highest; the (1-d) teleport keeps the walk ergodic so
 * sybil cliques cannot trap rank mass.
 *
 * The scene literalizes that: ~40 emissive nodes on a fibonacci sphere, glowing
 * directed edges, and bright pulses of light that travel ALONG each edge in the
 * trust direction (source -> target). Node radius & brightness scale with the
 * actual PageRank score computed here, so light visibly streams toward — and the
 * highest-reputation node blazes as a radiant sun.
 */

const N = 40; // node count (graph nodes)
const DAMPING = 0.85;
const RADIUS = 5.4; // layout sphere radius
const CYAN = new THREE.Color("#6ee7ff");
const PURPLE = new THREE.Color("#c084fc");
const PINK = new THREE.Color("#f472b6");

// ---- tiny deterministic PRNG so the graph (and its ranking) is stable ----
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// fibonacci-sphere point i of n (organic, even 3D layout)
function fibSphere(i: number, n: number, r: number): THREE.Vector3 {
  const golden = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - (i / (n - 1)) * 2; // 1 .. -1
  const rad = Math.sqrt(Math.max(0, 1 - y * y));
  const theta = golden * i;
  return new THREE.Vector3(Math.cos(theta) * rad, y, Math.sin(theta) * rad).multiplyScalar(r);
}

type Edge = { i: number; j: number; w: number };

interface GraphData {
  positions: THREE.Vector3[];
  edges: Edge[];
  scores: number[]; // PageRank, sums to 1
  rank: number[]; // 0..1 normalized score (max -> 1)
  topNode: number;
  colors: THREE.Color[];
}

function buildGraph(): GraphData {
  const rng = mulberry32(73);
  const positions: THREE.Vector3[] = [];
  for (let i = 0; i < N; i++) positions.push(fibSphere(i, N, RADIUS));

  // A few "authority" hubs everyone tends to trust + transitive structure so
  // PageRank concentrates (and one clear sun emerges). The top hub is node 0.
  const hubs = [0, 1, 2, 5, 9];
  const edges: Edge[] = [];
  const seen = new Set<string>();
  const add = (i: number, j: number, w: number) => {
    if (i === j) return;
    const k = i + ":" + j;
    if (seen.has(k)) return;
    seen.add(k);
    edges.push({ i, j, w });
  };

  for (let i = 0; i < N; i++) {
    // each node extends 2-3 trust edges, biased toward nearby + toward hubs
    const out = 2 + Math.floor(rng() * 2);
    for (let e = 0; e < out; e++) {
      let j: number;
      if (rng() < 0.55) {
        // trust an authority hub (gives them inflow -> high rank)
        j = hubs[Math.floor(rng() * hubs.length)];
      } else {
        // trust a spatial neighbour (transitive local clusters)
        j = (i + 1 + Math.floor(rng() * 7)) % N;
      }
      add(i, j, 0.4 + rng() * 1.2);
    }
  }
  // funnel the secondary hubs toward the prime sun so node 0 wins clearly
  add(1, 0, 1.6);
  add(2, 0, 1.4);
  add(5, 0, 1.2);
  add(9, 1, 1.1);

  // ---- real PageRank via power iteration on the Google matrix ----
  // column-stochastic outgoing distributions
  const outW: number[] = new Array(N).fill(0);
  for (const ed of edges) outW[ed.i] += ed.w;
  let r = new Array(N).fill(1 / N);
  const teleport = (1 - DAMPING) / N;
  for (let iter = 0; iter < 120; iter++) {
    const next = new Array(N).fill(teleport);
    let dangling = 0;
    for (let i = 0; i < N; i++) if (outW[i] === 0) dangling += DAMPING * r[i] / N;
    for (let i = 0; i < N; i++) next[i] += dangling;
    for (const ed of edges) {
      next[ed.j] += DAMPING * r[ed.i] * (ed.w / outW[ed.i]);
    }
    let s = 0;
    for (let i = 0; i < N; i++) s += next[i];
    let delta = 0;
    for (let i = 0; i < N; i++) {
      next[i] /= s;
      delta += Math.abs(next[i] - r[i]);
    }
    r = next;
    if (delta < 1e-9) break;
  }

  const maxScore = Math.max(...r);
  const minScore = Math.min(...r);
  const rank = r.map((s) => (s - minScore) / (maxScore - minScore + 1e-9));
  let topNode = 0;
  for (let i = 1; i < N; i++) if (r[i] > r[topNode]) topNode = i;

  // color by rank: cyan (low) -> purple (mid) -> pink/white-hot (high)
  const colors = rank.map((t) => {
    const c = new THREE.Color();
    if (t < 0.5) c.copy(CYAN).lerp(PURPLE, t / 0.5);
    else c.copy(PURPLE).lerp(PINK, (t - 0.5) / 0.5);
    return c;
  });

  return { positions, edges, scores: r, rank, topNode, colors };
}

// =====================================================================
// EDGES + travelling trust pulses
// Pulses ride from source -> target (the trust direction). A pulse near a
// target carrying high source-rank delivers more light; everything funnels
// toward the highest-reputation node, which therefore receives the most.
// =====================================================================
const PULSES_PER_EDGE = 1;

function TrustGraph({ g }: { g: GraphData }) {
  const { positions, edges, rank, colors, topNode } = g;

  // line segment geometry for all edges (one buffered Line per few edges would
  // be cheaper, but drei <Line> handles a flat points list fine at this count)
  const edgeLines = useMemo(() => {
    return edges.map((ed) => {
      const a = positions[ed.i];
      const b = positions[ed.j];
      // a gentle outward bow so edges read as arcs over the sphere
      const mid = a.clone().add(b).multiplyScalar(0.5);
      mid.multiplyScalar(1.14);
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      const pts = curve.getPoints(14);
      // edge brightness ~ how reputable the destination is
      const t = rank[ed.j];
      const col = colors[ed.j];
      return { pts, col, opacity: 0.06 + t * 0.34, dest: ed.j };
    });
  }, [edges, positions, rank, colors]);

  // pre-sample each edge curve for pulse motion
  const pulseEdges = useMemo(() => {
    return edges.map((ed) => {
      const a = positions[ed.i];
      const b = positions[ed.j];
      const mid = a.clone().add(b).multiplyScalar(0.5).multiplyScalar(1.14);
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      return {
        curve,
        srcRank: rank[ed.i],
        dstRank: rank[ed.j],
        col: colors[ed.j].clone(),
        speed: 0.18 + rank[ed.j] * 0.5, // light flows faster toward authority
        offset: (ed.i * 7 + ed.j * 13) % 100 / 100,
      };
    });
  }, [edges, positions, rank, colors]);

  const PULSE_COUNT = Math.min(edges.length * PULSES_PER_EDGE, 600);
  const pulseRef = useRef<any>(null);
  const tmp = useMemo(() => new THREE.Object3D(), []);
  const tmpC = useMemo(() => new THREE.Color(), []);

  useFrame(({ clock }) => {
    const inst = pulseRef.current;
    if (!inst) return;
    const time = clock.elapsedTime;
    const pe = pulseEdges;
    const count = Math.min(PULSE_COUNT, pe.length);
    for (let k = 0; k < count; k++) {
      const e = pe[k];
      // param 0..1 along the edge, wrapping; trust flows source -> target
      let u = (time * e.speed + e.offset) % 1;
      const p = e.curve.getPoint(u);
      tmp.position.copy(p);
      // brighten as it nears the destination (light "arriving" at reputation)
      const arrive = 0.35 + u * 0.65;
      const s = (0.05 + e.srcRank * 0.14) * arrive;
      tmp.scale.setScalar(s);
      tmp.updateMatrix();
      inst.setMatrixAt(k, tmp.matrix);
      tmpC.copy(e.col).multiplyScalar(0.6 + arrive * 0.8);
      inst.setColorAt(k, tmpC);
    }
    inst.instanceMatrix.needsUpdate = true;
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
  });

  return (
    <group>
      {/* glowing directed edges */}
      {edgeLines.map((el, i) => (
        <Line
          key={i}
          points={el.pts}
          color={el.col}
          transparent
          opacity={el.opacity}
          lineWidth={el.dest === topNode ? 1.6 : 0.8}
        />
      ))}

      {/* travelling trust pulses (instanced) */}
      <instancedMesh
        ref={pulseRef}
        args={[undefined as any, undefined as any, PULSE_COUNT]}
        frustumCulled={false}
      >
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

// =====================================================================
// NODES — emissive spheres, radius & glow ∝ PageRank
// =====================================================================
function Nodes({ g }: { g: GraphData }) {
  const { positions, rank, colors, topNode } = g;
  const ref = useRef<any>(null);
  const tmp = useMemo(() => new THREE.Object3D(), []);

  const data = useMemo(
    () =>
      positions.map((p, i) => ({
        p,
        baseR: 0.12 + rank[i] * 0.55,
        col: colors[i],
        rank: rank[i],
        phase: i * 1.37,
        isTop: i === topNode,
      })),
    [positions, rank, colors, topNode]
  );

  useFrame(({ clock }) => {
    const inst = ref.current;
    if (!inst) return;
    const t = clock.elapsedTime;
    for (let i = 0; i < data.length; i++) {
      const d = data[i];
      // higher-rank nodes breathe slower & statelier; all gently pulse
      const pulse = 1 + Math.sin(t * (1.4 + (1 - d.rank) * 1.6) + d.phase) * 0.08;
      tmp.position.copy(d.p);
      tmp.scale.setScalar(d.baseR * pulse);
      tmp.updateMatrix();
      inst.setMatrixAt(i, tmp.matrix);
    }
    inst.instanceMatrix.needsUpdate = true;
  });

  return (
    <Instances ref={ref} limit={N} range={N} frustumCulled={false}>
      <sphereGeometry args={[1, 24, 24]} />
      <meshStandardMaterial
        toneMapped={false}
        roughness={0.25}
        metalness={0.2}
        vertexColors
      />
      {data.map((d, i) => (
        <Instance
          key={i}
          position={d.p}
          color={d.col.clone().multiplyScalar(1.4 + d.rank * 1.4)}
        />
      ))}
    </Instances>
  );
}

// =====================================================================
// THE SUN — the highest-reputation node: a radiant core + halo + corona ring
// that drinks in the most inflowing light.
// =====================================================================
function Sun({ g }: { g: GraphData }) {
  const { positions, topNode } = g;
  const pos = positions[topNode];
  const core = useRef<THREE.Mesh>(null);
  const halo = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.Mesh>(null);
  const matCore = useRef<THREE.MeshStandardMaterial>(null);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const breathe = 1 + Math.sin(t * 0.8) * 0.06;
    if (core.current) core.current.scale.setScalar(breathe);
    if (matCore.current) matCore.current.emissiveIntensity = 2.4 + Math.sin(t * 1.3) * 0.6;
    if (halo.current) {
      const hb = 1 + Math.sin(t * 0.6 + 1) * 0.12;
      halo.current.scale.setScalar(hb);
      (halo.current.material as THREE.MeshBasicMaterial).opacity = 0.16 + Math.sin(t * 0.9) * 0.05;
    }
    if (ring.current) {
      ring.current.rotation.z += 0.004;
      ring.current.rotation.x = Math.PI / 2 + Math.sin(t * 0.4) * 0.3;
    }
  });

  return (
    <group position={pos}>
      {/* radiant core */}
      <mesh ref={core}>
        <sphereGeometry args={[0.85, 36, 36]} />
        <meshStandardMaterial
          ref={matCore}
          color={PINK}
          emissive={PINK}
          emissiveIntensity={2.6}
          toneMapped={false}
          roughness={0.1}
          metalness={0.1}
        />
      </mesh>
      {/* soft halo */}
      <mesh ref={halo}>
        <sphereGeometry args={[1.5, 24, 24]} />
        <meshBasicMaterial color={PINK} transparent opacity={0.18} depthWrite={false} toneMapped={false} />
      </mesh>
      {/* corona ring */}
      <mesh ref={ring} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1.7, 0.025, 12, 120]} />
        <meshBasicMaterial color={CYAN} transparent opacity={0.6} toneMapped={false} />
      </mesh>
      {/* a point of bright light to seed bloom */}
      <pointLight color={PINK} intensity={3.2} distance={14} />
      <Billboard>
        <Text
          position={[0, 2.4, 0]}
          fontSize={0.46}
          color="#ffd9ef"
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.006}
          outlineColor="#000000"
        >
          most trusted
        </Text>
      </Billboard>
    </group>
  );
}

// =====================================================================
// SCENE — slow rotation, looping cinematic arc.
// =====================================================================
export default function LumenScene() {
  const g = useMemo(() => buildGraph(), []);
  const root = useRef<THREE.Group>(null);

  useFrame(({ clock }, delta) => {
    if (!root.current) return;
    // slow stately spin (atop the canvas auto-rotate) + a gentle wobble so the
    // graph reads as a living 3D constellation rather than a flat ring.
    root.current.rotation.y += delta * 0.06;
    const t = clock.elapsedTime;
    root.current.rotation.x = Math.sin(t * 0.12) * 0.12;
    // slow breathing of the whole constellation = the convergence "settling"
    const s = 1 + Math.sin(t * 0.18) * 0.025;
    root.current.scale.setScalar(s);
  });

  return (
    <group ref={root}>
      <TrustGraph g={g} />
      <Nodes g={g} />
      <Sun g={g} />
    </group>
  );
}
