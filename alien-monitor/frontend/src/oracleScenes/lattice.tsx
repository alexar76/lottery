import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";

/**
 * Lattice oracle — low-discrepancy (quasi-random) Halton sequences.
 *
 * The product claim is "white noise CLUMPS, lattice DOESN'T": ordinary random
 * sampling leaves clusters and gaps by chance, while a Halton low-discrepancy
 * sequence fills the unit cube ultra-evenly. This scene is that claim made
 * cinematic — order emerging from chaos.
 *
 * SIGNATURE MOTIF: ~900 emissive points START as a clumpy random 3D cloud and
 * EASE (easeOutBack overshoot) into a PERFECT 3D LATTICE — a real Halton-style
 * quasi-uniform grid in [0,1)^3 computed by the van der Corput radical inverse
 * in coprime prime bases 2/3/5 (mirrors lattice/halton.py). The point set holds
 * in its ordered crystalline state (faint connective grid lines appear), then
 * dissolves back to chaos and reseeds — an endless loop. The whole lattice
 * tumbles slowly in 3D and the points depth-color-ramp cyan(near) -> purple ->
 * pink(far) with emissive material so the shared Bloom pass makes them glow.
 *
 * Rendered INSIDE the shared CosmicCanvas (camera, auto-rotating OrbitControls,
 * lights, nebula, starfields, Sparkles, Bloom+Vignette already provided), so
 * this exports only the signature <group>.
 */

const N = 900; // points — instanced, comfortably 60fps
const GRID = 9; // 9*9*~11 ~= 900 lattice cells, near-cubic
const GRID_Z = Math.ceil(N / (GRID * GRID)); // = 12 -> 972 slots, we use first N
const EXTENT = 5.4; // half-size of the cube the lattice fills
const PRIMES = [2, 3, 5]; // coprime bases, one per axis (van der Corput)

const CYAN = new THREE.Color("#6ee7ff");
const PURPLE = new THREE.Color("#c084fc");
const PINK = new THREE.Color("#f472b6");

// loop timing (seconds)
const T_CHAOS = 1.6; // hold in the clumpy cloud
const T_FORM = 3.2; // ease chaos -> lattice
const T_ORDER = 3.4; // hold the perfect crystal (grid lines visible)
const T_DISSOLVE = 2.4; // ease lattice -> fresh chaos
const T_LOOP = T_CHAOS + T_FORM + T_ORDER + T_DISSOLVE;

// ---- pure math (mirrors oracles/lattice/lattice/halton.py) ------------------

/** van der Corput radical inverse phi_base(n) in [0,1). */
function radicalInverse(n: number, base: number): number {
  let result = 0;
  let f = 1 / base;
  let i = n;
  while (i > 0) {
    result += (i % base) * f;
    i = Math.floor(i / base);
    f /= base;
  }
  return result;
}

/** easeOutBack — overshoot so the crystal "snaps" into place. */
function easeOutBack(x: number): number {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  const t = x - 1;
  return 1 + c3 * t * t * t + c1 * t * t;
}

function easeInOutCubic(x: number): number {
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

function smoothstep(a: number, b: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

type Vec3 = [number, number, number];

// ---- main scene -------------------------------------------------------------

export default function Scene() {
  const group = useRef<THREE.Group>(null);
  const mesh = useRef<THREE.InstancedMesh>(null);
  const grid = useRef<THREE.Group>(null);

  // ordered lattice targets — a real Halton point set, centered on the cube.
  const ordered = useMemo<Vec3[]>(() => {
    const pts: Vec3[] = [];
    for (let n = 1; n <= N; n++) {
      const hx = radicalInverse(n, PRIMES[0]);
      const hy = radicalInverse(n, PRIMES[1]);
      const hz = radicalInverse(n, PRIMES[2]);
      pts.push([
        (hx - 0.5) * 2 * EXTENT,
        (hy - 0.5) * 2 * EXTENT,
        (hz - 0.5) * 2 * EXTENT,
      ]);
    }
    return pts;
  }, []);

  // depth/index color ramp baked once: cyan -> purple -> pink along Halton Z.
  const colors = useMemo<THREE.Color[]>(() => {
    const tmp = new THREE.Color();
    return ordered.map((p) => {
      const t = (p[2] / (2 * EXTENT)) + 0.5; // 0..1 over the cube depth
      if (t < 0.5) tmp.copy(CYAN).lerp(PURPLE, t * 2);
      else tmp.copy(PURPLE).lerp(PINK, (t - 0.5) * 2);
      return tmp.clone();
    });
  }, [ordered]);

  // two chaotic clouds we crossfade between across loops (clumpy white noise:
  // gaussian-ish clusters so it visibly CLUMPS, unlike the even lattice).
  const makeChaos = useMemo(
    () => (seed: number): Vec3[] => {
      let s = seed * 1013904223 + 1664525;
      const rnd = () => {
        s = (s * 1664525 + 1013904223) % 4294967296;
        return s / 4294967296;
      };
      // a handful of clumps; each point belongs to one — that is the "clumping"
      const clumps: Vec3[] = [];
      const NC = 7;
      for (let c = 0; c < NC; c++) {
        clumps.push([
          (rnd() - 0.5) * 2 * EXTENT * 0.7,
          (rnd() - 0.5) * 2 * EXTENT * 0.7,
          (rnd() - 0.5) * 2 * EXTENT * 0.7,
        ]);
      }
      const pts: Vec3[] = [];
      for (let i = 0; i < N; i++) {
        const c = clumps[Math.floor(rnd() * NC)];
        // gaussian-ish offset via sum of uniforms (clumpy)
        const g = () => (rnd() + rnd() + rnd() - 1.5) * EXTENT * 0.6;
        pts.push([c[0] + g(), c[1] + g(), c[2] + g()]);
      }
      return pts;
    },
    []
  );

  // animation state held in a ref so useFrame mutates without re-render
  const state = useRef({
    loop: -1,
    chaosA: makeChaos(1),
    chaosB: makeChaos(2),
  });

  // faint connective grid lines that read as the crystal's scaffolding. We draw
  // a coarse cubic frame (independent of the 900 points) and fade it in only
  // during the ordered phase. Precomputed segment endpoints.
  const gridSegments = useMemo<[Vec3, Vec3][]>(() => {
    const segs: [Vec3, Vec3][] = [];
    const STEPS = 4; // 5 planes per axis -> light scaffold
    const at = (i: number) => (i / STEPS - 0.5) * 2 * EXTENT;
    for (let i = 0; i <= STEPS; i++) {
      for (let j = 0; j <= STEPS; j++) {
        const a = at(i);
        const b = at(j);
        segs.push([[-EXTENT, a, b], [EXTENT, a, b]]); // along X
        segs.push([[a, -EXTENT, b], [a, EXTENT, b]]); // along Y
        segs.push([[a, b, -EXTENT], [a, b, EXTENT]]); // along Z
      }
    }
    return segs;
  }, []);

  const tmpObj = useMemo(() => new THREE.Object3D(), []);

  useFrame(({ clock }) => {
    const m = mesh.current;
    if (!m) return;
    const t = clock.elapsedTime;

    // slow 3D tumble of the whole crystal
    if (group.current) {
      group.current.rotation.y = t * 0.16;
      group.current.rotation.x = Math.sin(t * 0.11) * 0.28;
      group.current.rotation.z = Math.cos(t * 0.07) * 0.12;
    }

    // bake per-instance colors once. setColorAt lazily allocates the
    // instanceColor buffer on first call, so we call it unconditionally here.
    if ((m as any).__coloredN !== N) {
      for (let i = 0; i < N; i++) m.setColorAt(i, colors[i]);
      if (m.instanceColor) m.instanceColor.needsUpdate = true;
      (m as any).__coloredN = N;
    }

    // which loop iteration are we in? reseed chaos cloud each new loop.
    const loopIdx = Math.floor(t / T_LOOP);
    if (loopIdx !== state.current.loop) {
      state.current.loop = loopIdx;
      // promote B -> A (the cloud we just dissolved into) and seed a fresh B
      state.current.chaosA = state.current.chaosB;
      state.current.chaosB = makeChaos(loopIdx * 2 + 3);
    }
    const local = t - loopIdx * T_LOOP;

    // order parameter: 0 = pure chaos, 1 = perfect lattice
    let order: number;
    let lineFade: number;
    if (local < T_CHAOS) {
      order = 0;
      lineFade = 0;
    } else if (local < T_CHAOS + T_FORM) {
      const u = (local - T_CHAOS) / T_FORM;
      order = easeOutBack(u);
      lineFade = smoothstep(0.55, 1.0, u);
    } else if (local < T_CHAOS + T_FORM + T_ORDER) {
      order = 1;
      lineFade = 1;
    } else {
      const u = (local - T_CHAOS - T_FORM - T_ORDER) / T_DISSOLVE;
      order = 1 - easeInOutCubic(u);
      lineFade = 1 - smoothstep(0.0, 0.4, u);
    }

    const chaos = state.current.chaosA;
    // gentle breathing of the whole cloud so chaos never looks frozen
    const breath = 1 + Math.sin(t * 0.6) * 0.015;

    for (let i = 0; i < N; i++) {
      const c = chaos[i];
      const o = ordered[i];
      // small per-point chaotic jitter that quiets as order -> 1
      const jit = (1 - order) * 0.35;
      const jx = Math.sin(t * 1.7 + i * 0.9) * jit;
      const jy = Math.cos(t * 1.4 + i * 1.3) * jit;
      const jz = Math.sin(t * 1.1 + i * 0.5) * jit;

      const x = (c[0] * (1 - order) + o[0] * order + jx) * breath;
      const y = (c[1] * (1 - order) + o[1] * order + jy) * breath;
      const z = (c[2] * (1 - order) + o[2] * order + jz) * breath;

      tmpObj.position.set(x, y, z);
      // points shrink slightly while ordered (crisp), swell while chaotic
      const sc = 0.85 + (1 - order) * 0.5 + Math.sin(t * 3 + i) * 0.05;
      tmpObj.scale.setScalar(sc);
      tmpObj.updateMatrix();
      m.setMatrixAt(i, tmpObj.matrix);
    }
    m.instanceMatrix.needsUpdate = true;

    // drive the scaffold opacity via material on the grid group lines
    if (grid.current) {
      grid.current.visible = lineFade > 0.01;
      grid.current.traverse((child: any) => {
        if (child.material && "opacity" in child.material) {
          child.material.opacity = 0.14 * lineFade;
          child.material.transparent = true;
        }
      });
      grid.current.scale.setScalar(1);
    }
  });

  return (
    <group ref={group}>
      {/* the ~900 quasi-random / lattice points */}
      <instancedMesh
        ref={mesh as any}
        args={[undefined as any, undefined as any, N]}
        frustumCulled={false}
      >
        <icosahedronGeometry args={[0.075, 0]} />
        <meshStandardMaterial
          vertexColors
          emissive={"#ffffff"}
          emissiveIntensity={2.2}
          roughness={0.25}
          metalness={0.5}
          toneMapped={false}
        />
      </instancedMesh>

      {/* faint connective scaffold — only visible at the ordered phase */}
      <group ref={grid} visible={false}>
        {gridSegments.map((seg, i) => (
          <Line
            key={i}
            points={[
              new THREE.Vector3(...seg[0]),
              new THREE.Vector3(...seg[1]),
            ]}
            color="#c084fc"
            transparent
            opacity={0}
            lineWidth={1}
            toneMapped={false}
          />
        ))}
      </group>
    </group>
  );
}
