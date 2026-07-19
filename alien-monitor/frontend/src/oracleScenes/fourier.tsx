import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Billboard, Instance, Instances, Text } from "@react-three/drei";
import * as THREE from "three";

/* ===========================================================================
 *  FOURIER — Graph-Spectral oracle (signature 3D scene)  ·  "THE DRUMHEAD"
 *
 *  The real concept: the Fourier transform ON a graph. Build the Laplacian
 *  L = D − A; its eigenvectors are the graph's standing-wave modes (its Fourier
 *  basis) and its eigenvalues are the graph "frequencies". The smallest non-
 *  trivial eigenvalue λ₂ (the FIEDLER value) is the algebraic connectivity —
 *  0 iff the graph splits, tiny when it has a narrow bottleneck — and its
 *  eigenvector v₂ (the FIEDLER vector) is the lowest vibration mode whose sign
 *  pattern is the canonical bisection into two communities.
 *
 *  The scene literalizes all of that. A ~50-node graph of two loosely-joined
 *  communities (a near-split — small spectral gap):
 *    1. BLOB     — nodes scattered in a random cloud.
 *    2. RELAX    — they ease into their OWN spectral-embedding coordinates
 *                  (v₂,v₃,v₄ of the real Laplacian, solved here by Jacobi), so
 *                  the graph unfolds into the shape its connectivity implies.
 *    3. DRUMHEAD — nodes oscillate along the Fiedler axis by their v₂ amplitude
 *                  (sign +/− = the two communities, cyan vs pink). Because the
 *                  spectral gap is small the two halves TREMBLE on the edge of
 *                  tearing apart and snapping back — a two-community standing
 *                  wave that never quite splits. Edges glow & stretch.
 *    …then it resets and loops.
 *
 *  Rendered inside the shared CosmicCanvas (camera/lights/nebula/bloom given).
 *  Everything that scales with node count is instanced; per-frame work touches
 *  preallocated buffers only — no allocations, no leaks over long runs.
 * ========================================================================= */

const AZURE = new THREE.Color("#60a5fa"); // accent
const CYAN = new THREE.Color("#6ee7ff"); // Fiedler community +
const PINK = new THREE.Color("#f472b6"); // Fiedler community −
const WHITE = new THREE.Color("#ffffff");

const N = 52; // graph nodes
const SPREAD = 7.4; // spectral-embedding scale
const VIB = 1.7; // drumhead vibration amplitude

// Phase arc (seconds): blob → relax into spectral shape → drumhead → reset.
const T_BLOB = 2.6;
const T_RELAX = 4.2;
const T_DRUM = 9.0;
const T_RESET = 2.4;
const LOOP = T_BLOB + T_RELAX + T_DRUM + T_RESET;

const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};

// Deterministic PRNG so the graph (and its spectrum) is identical every reload.
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

type Edge = { i: number; j: number };

interface SpectralGraph {
  edges: Edge[];
  blob: THREE.Vector3[]; // random start cloud
  embed: THREE.Vector3[]; // spectral coords (v2,v3,v4)
  fiedler: number[]; // v2 component per node (signed), normalized to ~[-1,1]
  community: boolean[]; // sign of fiedler (the two halves)
  lambda2: number; // algebraic connectivity (small => near-split)
  amp: number[]; // |fiedler| drumhead amplitude per node
}

/* --- symmetric eigensolver (cyclic Jacobi) — small, exact enough for N≈52,
 *     scipy-free, runs once at mount. Returns ascending eigenpairs. ------- */
function jacobiEigen(Ain: number[][]): { values: number[]; vectors: number[][] } {
  const n = Ain.length;
  const A = Ain.map((r) => r.slice());
  const V: number[][] = Array.from({ length: n }, (_, i) =>
    Array.from({ length: n }, (_, j) => (i === j ? 1 : 0))
  );
  for (let sweep = 0; sweep < 100; sweep++) {
    let off = 0;
    for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) off += A[p][q] * A[p][q];
    if (off < 1e-12) break;
    for (let p = 0; p < n; p++) {
      for (let q = p + 1; q < n; q++) {
        if (Math.abs(A[p][q]) < 1e-14) continue;
        const theta = (A[q][q] - A[p][p]) / (2 * A[p][q]);
        const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1);
        const s = t * c;
        for (let k = 0; k < n; k++) {
          const akp = A[k][p];
          const akq = A[k][q];
          A[k][p] = c * akp - s * akq;
          A[k][q] = s * akp + c * akq;
        }
        for (let k = 0; k < n; k++) {
          const apk = A[p][k];
          const aqk = A[q][k];
          A[p][k] = c * apk - s * aqk;
          A[q][k] = s * apk + c * aqk;
        }
        for (let k = 0; k < n; k++) {
          const vkp = V[k][p];
          const vkq = V[k][q];
          V[k][p] = c * vkp - s * vkq;
          V[k][q] = s * vkp + c * vkq;
        }
      }
    }
  }
  const idx = Array.from({ length: n }, (_, i) => i).sort((a, b) => A[a][a] - A[b][b]);
  const values = idx.map((i) => A[i][i]);
  const vectors = idx.map((i) => V.map((row) => row[i])); // vectors[m] = eigenvector m
  return { values, vectors };
}

function buildSpectralGraph(): SpectralGraph {
  const rng = mulberry32(0x517e); // stable seed
  // Two communities A={0..k-1}, B={k..N-1}, densely wired within, ONE-ish bridge
  // between — a near-split: large within-community degree, tiny cut ⇒ small λ₂.
  const k = Math.floor(N / 2);
  const edges: Edge[] = [];
  const seen = new Set<string>();
  const add = (i: number, j: number) => {
    if (i === j) return;
    const key = i < j ? i + ":" + j : j + ":" + i;
    if (seen.has(key)) return;
    seen.add(key);
    edges.push({ i, j });
  };
  const wireCommunity = (lo: number, hi: number) => {
    for (let i = lo; i < hi; i++) {
      const out = 3 + Math.floor(rng() * 3);
      for (let e = 0; e < out; e++) {
        const j = lo + Math.floor(rng() * (hi - lo));
        add(i, j);
      }
      add(i, lo + ((i - lo + 1) % (hi - lo))); // a ring keeps each side connected
    }
  };
  wireCommunity(0, k);
  wireCommunity(k, N);
  // a thin bridge: 2 cross edges total → narrow bottleneck, small spectral gap
  add(k - 1, k);
  add(Math.floor(k / 2), k + Math.floor((N - k) / 2));

  // --- Laplacian L = D − A, then its eigvecs (the graph Fourier basis) ----
  const L: number[][] = Array.from({ length: N }, () => new Array(N).fill(0));
  for (const e of edges) {
    L[e.i][e.j] -= 1;
    L[e.j][e.i] -= 1;
    L[e.i][e.i] += 1;
    L[e.j][e.j] += 1;
  }
  const { values, vectors } = jacobiEigen(L);
  // vectors[1..3] = v2,v3,v4 (skip v1 = constant λ1≈0 mode). Spectral embedding.
  const v2 = vectors[1];
  const v3 = vectors[2] ?? vectors[1];
  const v4 = vectors[3] ?? vectors[1];
  const lambda2 = values[1];

  // normalize each embedding axis so the unfolded shape fills the view
  const norm = (v: number[]) => {
    let m = 0;
    for (const x of v) m = Math.max(m, Math.abs(x));
    return m > 1e-9 ? 1 / m : 1;
  };
  const s2 = norm(v2);
  const s3 = norm(v3);
  const s4 = norm(v4);

  const embed: THREE.Vector3[] = [];
  const fiedler: number[] = [];
  const community: boolean[] = [];
  const amp: number[] = [];
  for (let i = 0; i < N; i++) {
    embed.push(
      new THREE.Vector3(v3[i] * s3 * SPREAD, v2[i] * s2 * SPREAD, v4[i] * s4 * SPREAD)
    );
    const f = v2[i] * s2; // signed Fiedler amplitude ~[-1,1]
    fiedler.push(f);
    community.push(f >= 0);
    amp.push(Math.abs(f));
  }

  // random start blob (deterministic)
  const blob: THREE.Vector3[] = [];
  for (let i = 0; i < N; i++) {
    const a = rng() * Math.PI * 2;
    const b = Math.acos(2 * rng() - 1);
    const r = 2.4 + rng() * 2.0;
    blob.push(
      new THREE.Vector3(
        Math.sin(b) * Math.cos(a) * r,
        Math.cos(b) * r,
        Math.sin(b) * Math.sin(a) * r
      )
    );
  }

  return { edges, blob, embed, fiedler, community, lambda2, amp };
}

/* ----------------------------- edges (glowing) ---------------------------- */
function Edges({ g, posRef }: { g: SpectralGraph; posRef: React.MutableRefObject<THREE.Vector3[]> }) {
  // One additive-blended LineSegments for ALL edges (single draw call). We rewrite
  // the endpoint positions each frame from the live node positions via a
  // preallocated Float32Array — no per-frame allocations, and no dependency on
  // the three-stdlib Line2 API (whose per-frame geometry mutation is brittle).
  // Cross-community edges (the bridge) are coloured brightest.
  const segRef = useRef<THREE.LineSegments>(null);
  const positions = useMemo(() => new Float32Array(g.edges.length * 2 * 3), [g.edges]);
  const geom = useMemo(() => {
    const gg = new THREE.BufferGeometry();
    gg.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const colors = new Float32Array(g.edges.length * 2 * 3);
    const col = new THREE.Color();
    for (let e = 0; e < g.edges.length; e++) {
      const cross = g.community[g.edges[e].i] !== g.community[g.edges[e].j];
      col.set(cross ? "#dbeafe" : "#3b82f6").multiplyScalar(cross ? 1.4 : 0.5);
      const k = e * 6;
      col.toArray(colors, k);
      col.toArray(colors, k + 3);
    }
    gg.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    return gg;
  }, [g.edges, g.community, positions]);

  useFrame(() => {
    const pos = posRef.current;
    if (!pos) return;
    for (let e = 0; e < g.edges.length; e++) {
      const { i, j } = g.edges[e];
      const a = pos[i];
      const b = pos[j];
      const k = e * 6;
      positions[k] = a.x; positions[k + 1] = a.y; positions[k + 2] = a.z;
      positions[k + 3] = b.x; positions[k + 4] = b.y; positions[k + 5] = b.z;
    }
    geom.attributes.position.needsUpdate = true;
  });

  return (
    <lineSegments ref={segRef} geometry={geom}>
      <lineBasicMaterial
        vertexColors
        transparent
        opacity={0.55}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
        toneMapped={false}
      />
    </lineSegments>
  );
}

/* ----------------------------- nodes (instanced) -------------------------- */
export default function Scene() {
  const g = useMemo(() => buildSpectralGraph(), []);
  const root = useRef<THREE.Group>(null);
  const nodesRef = useRef<THREE.InstancedMesh>(null);
  const labelRef = useRef<THREE.Group>(null);

  // live node positions, mutated in place & shared with the edge renderer
  const live = useRef<THREE.Vector3[]>(g.blob.map((p) => p.clone()));

  // per-node colour (community) precomputed; brightness modulated per frame
  const baseColors = useMemo(
    () => g.community.map((c) => (c ? CYAN.clone() : PINK.clone())),
    [g.community]
  );

  const dummy = useMemo(() => new THREE.Object3D(), []);
  const tmpColor = useMemo(() => new THREE.Color(), []);
  const fiedlerAxis = useMemo(() => new THREE.Vector3(0, 1, 0), []); // v2 maps to +Y in embed

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const lt = t % LOOP;

    // phase weights (smoothly blended)
    const tBlob = T_BLOB;
    const tRelax = tBlob + T_RELAX;
    const tDrum = tRelax + T_DRUM;
    // unfold: 0 in blob → 1 by end of relax → stays 1 through drum → 0 on reset
    const unfold =
      smoothstep(tBlob, tRelax, lt) * (1 - smoothstep(tDrum, LOOP, lt));
    // drumhead vibration ramps in after the shape settles
    const drum = smoothstep(tRelax + 0.6, tRelax + 2.2, lt) * (1 - smoothstep(tDrum - 0.6, tDrum, lt));

    // small spectral gap ⇒ the standing wave trembles near the splitting point:
    // a slow fundamental beat with a faster tremor, gated by per-node |Fiedler|.
    const beat = Math.sin(t * 1.15);
    const tremor = Math.sin(t * 4.3) * 0.32 + Math.sin(t * 7.9 + 1.3) * 0.16;
    const wave = beat * (1 + tremor * 0.5);

    const mesh = nodesRef.current;
    for (let i = 0; i < N; i++) {
      const p = live.current[i];
      // base position eases blob → spectral embedding
      p.copy(g.blob[i]).lerp(g.embed[i], unfold);
      // drumhead displacement along the Fiedler (+Y) axis, signed by community,
      // scaled by this node's Fiedler amplitude → the two halves swing oppositely
      const disp = g.fiedler[i] * wave * VIB * drum;
      p.addScaledVector(fiedlerAxis, disp);

      if (mesh) {
        dummy.position.copy(p);
        const s = 0.16 + g.amp[i] * 0.34 + Math.abs(disp) * 0.05;
        dummy.scale.setScalar(s);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
        // brighten with vibration extremes so the wave pulses through the colour
        tmpColor.copy(baseColors[i]).lerp(WHITE, clamp(Math.abs(disp) * 0.35 + drum * 0.1, 0, 0.6));
        tmpColor.multiplyScalar(1.5 + g.amp[i] * 1.2 + Math.abs(disp) * 0.4);
        mesh.setColorAt(i, tmpColor);
      }
    }
    if (mesh) {
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }

    // gentle stately spin of the whole drumhead
    if (root.current) {
      root.current.rotation.y += 0.0016;
      root.current.rotation.x = Math.sin(t * 0.1) * 0.1;
    }
    // float the label just above the membrane
    if (labelRef.current) labelRef.current.position.y = -(SPREAD * 0.62 + 1.6) + Math.sin(t * 0.5) * 0.1;
  });

  return (
    <group ref={root}>
      <Edges g={g} posRef={live} />

      <Instances ref={nodesRef as any} limit={N} range={N} frustumCulled={false}>
        <sphereGeometry args={[1, 20, 20]} />
        <meshStandardMaterial
          vertexColors
          emissive={WHITE}
          emissiveIntensity={1.6}
          toneMapped={false}
          roughness={0.28}
          metalness={0.2}
        />
        {g.community.map((_, i) => (
          <Instance key={i} color={baseColors[i]} />
        ))}
      </Instances>

      <group ref={labelRef}>
        <Billboard>
          <Text
            fontSize={0.6}
            color="#bfdbfe"
            anchorX="center"
            anchorY="middle"
            outlineWidth={0.01}
            outlineColor="#04030f"
          >
            L = D - A  ·  λ2 (Fiedler)
          </Text>
        </Billboard>
      </group>
    </group>
  );
}
