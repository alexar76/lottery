import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Instances, Instance, Line, Billboard, Text } from "@react-three/drei";
import * as THREE from "three";

/* ===========================================================================
 *  KANTOR — Exact Optimal Transport (Wasserstein) with a dual certificate.
 *
 *  "THE EARTH BEING MOVED." A CYAN source mass-distribution — a glowing heap of
 *  instanced particles on the left — is transported along bundled FILAMENT
 *  streamlines to a MAGENTA target distribution on the right. Mass is literally
 *  carried across: travelling sparks ride each filament from source to sink.
 *
 *  The oracle's whole selling point is OPTIMALITY, so the scene dramatises it.
 *  First a SUBOPTIMAL coupling is shown: the filaments are crossed/tangled and
 *  the whole bundle visibly SAGS, drooping under its own weight. Then, when the
 *  Kantorovich DUAL CERTIFICATE locks in (u_i + v_j ≤ c_ij, tight on the
 *  support), the plan SNAPS to the certified-optimal coupling: the filaments
 *  untangle, straighten, and pull TAUT — a single satisfying release.
 *
 *  Loop:  source builds -> suboptimal sag -> SNAP taut to optimal ->
 *         mass arrives at the magenta target -> brief hold -> reset.
 *
 *  Rendered INSIDE the shared CosmicCanvas. Everything that scales with particle
 *  count is instanced; per-frame work touches only preallocated scratch objects,
 *  so it runs for minutes without allocating or leaking.
 * ========================================================================= */

const CYAN = new THREE.Color("#6ee7ff"); // source mass
const MAGENTA = new THREE.Color("#e879f9"); // target mass (accent)
const PURPLE = new THREE.Color("#c084fc");
const WHITE = new THREE.Color("#ffffff");

const N = 320; // source particles (= target particles; one filament each), capped for 60fps
const FIL = 56; // filaments actually drawn as <Line> (a representative bundle)
const SEG = 24; // vertices per filament curve

// Phase arc (seconds): build the heap -> tangled suboptimal sag -> SNAP taut ->
// mass flows to target -> hold -> reset.
const T_BUILD = 3.2;
const T_SAG = 4.0;
const T_SNAP = 1.1; // the quick, satisfying release
const T_FLOW = 4.2;
const T_HOLD = 2.2;
const LOOP = T_BUILD + T_SAG + T_SNAP + T_FLOW + T_HOLD;

const clamp = (v: number, lo: number, hi: number) =>
  v < lo ? lo : v > hi ? hi : v;
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};
// elastic-ish ease for the snap: overshoots slightly then settles.
const snapEase = (x: number) => {
  const t = clamp(x, 0, 1);
  const s = 1 - Math.pow(1 - t, 3);
  return s + Math.sin(t * Math.PI) * (1 - t) * 0.12;
};

// Deterministic PRNG so the heap looks identical every reload (and never NaNs).
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

const SRC_X = -6.0; // source heap centre
const SNK_X = 6.0; // target heap centre

type Mote = {
  src: THREE.Vector3; // anchor in the source heap
  snkOpt: THREE.Vector3; // its anchor in the OPTIMAL target coupling
  snkBad: THREE.Vector3; // its anchor in the SUBOPTIMAL (tangled) coupling
  color: THREE.Color;
  phase: number;
};

export default function Scene() {
  const group = useRef<THREE.Group>(null);
  const motes = useRef<THREE.InstancedMesh>(null); // travelling mass sparks
  const srcHeap = useRef<THREE.InstancedMesh>(null); // resident source pile
  const snkHeap = useRef<THREE.InstancedMesh>(null); // accumulating target pile
  const lineRefs = useRef<(any | null)[]>([]);
  const labelRef = useRef<THREE.Group>(null);

  // ---- build the coupling once (allocated, then only read in useFrame) ----
  const data = useMemo(() => {
    const rnd = mulberry32(0x4a17012);
    const out: Mote[] = [];
    // a vertically-stacked source heap (a "pile of earth")
    for (let i = 0; i < N; i++) {
      const a = rnd() * Math.PI * 2;
      const r = Math.pow(rnd(), 0.7) * 2.4;
      const y = (rnd() - 0.5) * 4.6;
      const src = new THREE.Vector3(
        SRC_X + Math.cos(a) * r * 0.5,
        y,
        Math.sin(a) * r
      );
      // OPTIMAL target: a monotone, order-preserving coupling (height -> height).
      // Mass that is high in the source goes high in the target; no crossings.
      const ta = rnd() * Math.PI * 2;
      const tr = Math.pow(rnd(), 0.7) * 2.2;
      const snkOpt = new THREE.Vector3(
        SNK_X + Math.cos(ta) * tr * 0.5,
        y * 0.92 + (rnd() - 0.5) * 0.25, // nearly height-preserving => taut, parallel
        Math.sin(ta) * tr
      );
      // SUBOPTIMAL target: the SAME marginal, but a tangled assignment — vertically
      // mirrored so filaments cross, and pushed apart so the bundle sags.
      const snkBad = new THREE.Vector3(
        SNK_X + Math.cos(ta) * tr * 0.5,
        -y * 0.92 + (rnd() - 0.5) * 0.9,
        Math.sin(ta) * tr
      );
      const color =
        rnd() < 0.5 ? CYAN.clone() : CYAN.clone().lerp(PURPLE, 0.4);
      out.push({ src, snkOpt, snkBad, color, phase: rnd() * Math.PI * 2 });
    }
    // pick a representative subset of filaments to actually draw as lines
    const filIdx: number[] = [];
    const stride = Math.max(1, Math.floor(N / FIL));
    for (let k = 0; k < N && filIdx.length < FIL; k += stride) filIdx.push(k);
    // initial (straight) points for each drawn filament — overwritten per frame
    const filInit: THREE.Vector3[][] = filIdx.map((mi) => {
      const m = out[mi];
      const pts: THREE.Vector3[] = [];
      for (let s = 0; s < SEG; s++) {
        const u = s / (SEG - 1);
        pts.push(new THREE.Vector3().lerpVectors(m.src, m.snkOpt, u));
      }
      return pts;
    });
    // per-filament colour ramp (cyan source -> magenta target along the strand)
    const filColors: [number, number, number][][] = filInit.map(() => {
      const cols: [number, number, number][] = [];
      const c = new THREE.Color();
      for (let s = 0; s < SEG; s++) {
        const u = s / (SEG - 1);
        c.copy(CYAN).lerp(MAGENTA, u);
        cols.push([c.r, c.g, c.b]);
      }
      return cols;
    });
    return { motes: out, filIdx, filInit, filColors };
  }, []);

  // scratch (no per-frame allocation)
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const tmpColor = useMemo(() => new THREE.Color(), []);
  const pA = useMemo(() => new THREE.Vector3(), []);
  const pB = useMemo(() => new THREE.Vector3(), []);
  const pos = useMemo(() => new THREE.Vector3(), []);
  // reusable per-filament point buffers + flat position arrays, allocated once so
  // the per-frame line update never allocates (drei <Line> wraps a three-stdlib
  // Line2; its geometry.setPositions takes a flat [x,y,z,...] array).
  const filBuf = useMemo(
    () =>
      data.filIdx.map(() =>
        Array.from({ length: SEG }, () => new THREE.Vector3())
      ),
    [data.filIdx]
  );
  const filFlat = useMemo(
    () => data.filIdx.map(() => new Float32Array(SEG * 3)),
    [data.filIdx]
  );

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const lt = t % LOOP;

    // slow cinematic drift of the whole tableau
    if (group.current) {
      group.current.rotation.y = Math.sin(t * 0.12) * 0.28;
      group.current.position.y = Math.sin(t * 0.2) * 0.25;
    }

    // ---- phase weights -----------------------------------------------------
    const tBuild = T_BUILD;
    const tSag = tBuild + T_SAG;
    const tSnap = tSag + T_SNAP;
    const tFlow = tSnap + T_FLOW;

    const build = smoothstep(0, T_BUILD, lt); // 0..1 heap appears
    // sag grows during the sag phase, released by the snap
    const sagPhase = smoothstep(tBuild, tSag, lt);
    // snap: 0 before, eases to 1 across the snap window (the satisfying release)
    const snap = snapEase((lt - tSag) / T_SNAP);
    // optimality = how taut/optimal the coupling is (0 tangled -> 1 certified)
    const optimal = clamp(snap, 0, 1);
    // sag amount: full during sag, pulled to ~0 as optimal -> 1
    const sag = sagPhase * (1 - optimal);
    // flow: travelling mass progress source -> target
    const flow = smoothstep(tSnap, tFlow, lt) * (1 - smoothstep(tFlow, LOOP, lt) * 0.0);
    // arrived: how much mass has landed in the target heap
    const arrived = smoothstep(tSnap + 0.4, tFlow, lt);
    // reset fade near the very end
    const resetting = smoothstep(tFlow + T_HOLD * 0.4, LOOP, lt);

    // ---- source heap (resident pile, fades out as it is carried away) ------
    if (srcHeap.current) {
      for (let i = 0; i < N; i++) {
        const m = data.motes[i];
        const breathe = 1 + Math.sin(t * 2 + m.phase) * 0.06;
        const s = 0.07 * build * breathe * (1 - flow * 0.85) * (1 - resetting);
        dummy.position.copy(m.src);
        dummy.position.y += Math.sin(t * 1.5 + m.phase) * 0.04;
        dummy.scale.setScalar(Math.max(0.0001, s));
        dummy.updateMatrix();
        srcHeap.current.setMatrixAt(i, dummy.matrix);
        srcHeap.current.setColorAt(i, m.color);
      }
      srcHeap.current.instanceMatrix.needsUpdate = true;
      if (srcHeap.current.instanceColor)
        srcHeap.current.instanceColor.needsUpdate = true;
    }

    // ---- target heap (accumulates as mass arrives) -------------------------
    if (snkHeap.current) {
      for (let i = 0; i < N; i++) {
        const m = data.motes[i];
        const breathe = 1 + Math.sin(t * 2 + m.phase + 1.7) * 0.06;
        const s = 0.075 * arrived * breathe * (1 - resetting);
        dummy.position.copy(m.snkOpt);
        dummy.position.y += Math.sin(t * 1.4 + m.phase) * 0.04;
        dummy.scale.setScalar(Math.max(0.0001, s));
        dummy.updateMatrix();
        snkHeap.current.setMatrixAt(i, dummy.matrix);
        tmpColor.copy(MAGENTA).lerp(WHITE, 0.12);
        snkHeap.current.setColorAt(i, tmpColor);
      }
      snkHeap.current.instanceMatrix.needsUpdate = true;
      if (snkHeap.current.instanceColor)
        snkHeap.current.instanceColor.needsUpdate = true;
    }

    // ---- travelling mass sparks (one per mote, riding its filament) --------
    if (motes.current) {
      for (let i = 0; i < N; i++) {
        const m = data.motes[i];
        // each mote's individual progress, staggered so the flow reads as a stream
        const p = clamp(flow * 1.25 - (m.phase / (Math.PI * 2)) * 0.25, 0, 1);
        // current target anchor blends tangled -> optimal as the certificate locks
        pB.copy(m.snkBad).lerp(m.snkOpt, optimal);
        // base straight line src -> (current target)
        pos.copy(m.src).lerp(pB, p);
        // sag: pull the midpoint down (catenary-like), vanishes when taut
        const dropU = 4 * p * (1 - p); // 0 at ends, 1 at middle
        pos.y -= sag * dropU * 3.2;
        // a little lateral tangle wobble while suboptimal
        pos.z += Math.sin(p * Math.PI * 3 + m.phase) * sag * 0.6;
        const vis = build * (p > 0.001 && p < 0.999 ? 1 : 0.25) * (1 - resetting);
        const s = 0.05 * (0.6 + vis);
        dummy.position.copy(pos);
        dummy.scale.setScalar(Math.max(0.0001, s));
        dummy.updateMatrix();
        motes.current.setMatrixAt(i, dummy.matrix);
        // colour ramps cyan->magenta along its journey, flaring white as the
        // coupling snaps taut (the satisfying certify moment) then settling.
        tmpColor.copy(CYAN).lerp(MAGENTA, p);
        const flare = Math.sin(optimal * Math.PI) * (1 - arrived);
        tmpColor.lerp(WHITE, flare * 0.6);
        motes.current.setColorAt(i, tmpColor);
      }
      motes.current.instanceMatrix.needsUpdate = true;
      if (motes.current.instanceColor)
        motes.current.instanceColor.needsUpdate = true;
    }

    // ---- the bundled filament streamlines ----------------------------------
    // Each drawn filament is a curve from src to its (blended) target; it SAGS
    // when suboptimal and pulls TAUT as the dual certificate locks in.
    for (let k = 0; k < data.filIdx.length; k++) {
      const ref = lineRefs.current[k];
      if (!ref) continue;
      const m = data.motes[data.filIdx[k]];
      pB.copy(m.snkBad).lerp(m.snkOpt, optimal);
      const buf = filBuf[k];
      const flat = filFlat[k];
      for (let s = 0; s < SEG; s++) {
        const u = s / (SEG - 1);
        const v = buf[s];
        v.copy(m.src).lerp(pB, u);
        const dropU = 4 * u * (1 - u);
        v.y -= sag * dropU * 3.0;
        // tangle the strands sideways while suboptimal; straighten on snap
        v.z += Math.sin(u * Math.PI * 3 + m.phase) * sag * 0.7;
        v.x += Math.sin(u * Math.PI * 2 + m.phase * 1.3) * sag * 0.35;
        flat[s * 3] = v.x;
        flat[s * 3 + 1] = v.y;
        flat[s * 3 + 2] = v.z;
      }
      const geo = ref.geometry as any;
      if (geo && typeof geo.setPositions === "function") {
        geo.setPositions(flat);
      }
      const mat = ref.material as any;
      if (mat) mat.opacity = 0.25 + optimal * 0.55 + build * 0.1;
    }

    // ---- the certificate label: brightens as the coupling certifies --------
    if (labelRef.current) {
      const lm = labelRef.current as unknown as { visible: boolean };
      lm.visible = build > 0.3 && resetting < 0.8;
    }
  });

  return (
    <group ref={group}>
      {/* RESIDENT SOURCE HEAP — the cyan "pile of earth" to be moved */}
      <Instances ref={srcHeap as any} limit={N} range={N}>
        <icosahedronGeometry args={[1, 0]} />
        <meshStandardMaterial
          emissive={CYAN}
          emissiveIntensity={2.2}
          color="#04030f"
          roughness={0.35}
          metalness={0.1}
          toneMapped={false}
        />
        {data.motes.map((m, i) => (
          <Instance key={i} color={m.color} />
        ))}
      </Instances>

      {/* ACCUMULATING TARGET HEAP — magenta mass arriving */}
      <Instances ref={snkHeap as any} limit={N} range={N}>
        <icosahedronGeometry args={[1, 0]} />
        <meshStandardMaterial
          emissive={MAGENTA}
          emissiveIntensity={2.4}
          color="#04030f"
          roughness={0.35}
          metalness={0.1}
          toneMapped={false}
        />
        {data.motes.map((_, i) => (
          <Instance key={i} color={MAGENTA} />
        ))}
      </Instances>

      {/* TRAVELLING MASS SPARKS — the earth actually being moved */}
      <Instances ref={motes as any} limit={N} range={N}>
        <sphereGeometry args={[1, 8, 8]} />
        <meshStandardMaterial
          emissive={WHITE}
          emissiveIntensity={2.0}
          color="#000000"
          toneMapped={false}
        />
        {data.motes.map((_, i) => (
          <Instance key={i} color={CYAN} />
        ))}
      </Instances>

      {/* THE BUNDLED FILAMENT STREAMLINES — sag, then snap TAUT (cyan->magenta) */}
      {data.filIdx.map((mi, k) => (
        <Line
          key={mi}
          ref={(r) => (lineRefs.current[k] = r)}
          points={data.filInit[k]}
          vertexColors={data.filColors[k]}
          lineWidth={1.6}
          transparent
          opacity={0.4}
          toneMapped={false}
        />
      ))}

      {/* CONCEPT LABEL — the Kantorovich objective + dual feasibility condition */}
      <group ref={labelRef} visible={false}>
        <Billboard position={[0, -5.0, 0]}>
          <Text
            fontSize={0.5}
            color="#e879f9"
            anchorX="center"
            anchorY="middle"
            outlineWidth={0.01}
            outlineColor="#04030f"
            letterSpacing={0.06}
          >
            {"min cost(P)  ·  u_i + v_j <= c_ij"}
          </Text>
        </Billboard>
      </group>
    </group>
  );
}
