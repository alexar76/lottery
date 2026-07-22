import { useMemo, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import { Billboard, Text } from "@react-three/drei";
import * as THREE from "three";

/**
 * Turing oracle — structured BLUE-NOISE sampling via Mitchell's best-candidate
 * algorithm (mirrors oracles/turing/turing/bluenoise.py).
 *
 * Signature motif: ~700 points placed one-at-a-time so that each new point lands
 * as FAR as possible from every point already placed (throw K dart candidates,
 * keep the most isolated). The result is the defining property of blue noise — a
 * large minimum pairwise distance, evenly spread, NEVER clumped, yet irregular
 * (no lattice). The flat unit-square sample is lifted onto a gently undulating
 * shell so it reads as a living membrane: every point shimmers (per-point size +
 * emissive pulse), the whole sheet breathes and drifts, and each point links to
 * its nearest neighbours forming an organic cyan/purple/pink mesh.
 *
 * The scene re-seeds periodically: it grows a fresh blue-noise set point-by-point
 * (you watch the membrane fill in, every new point claiming the largest empty
 * gap), holds the finished even field, then dissolves and re-grows — a smooth
 * looping cinematic arc. A live readout shows the measured `min_distance`, the
 * quantitative signature the oracle actually sells.
 */

const TARGET_COUNT = 700; // points in the finished blue-noise set
const CANDIDATES = 10; // Mitchell dart candidates per placement (matches default)
const NEIGHBOUR_LINKS = 3; // near-neighbour links drawn per point (organic mesh)
const MAX_LINK_DIST = 0.085; // only link genuinely-close pairs (unit-square space)
const MAX_LINES = 1500; // cap link segments for 60fps
const SURFACE = 9.0; // half-extent of the membrane on X/Z
const UNDULATE = 1.15; // vertical amplitude of the undulating shell

const GROW_PER_SEC = 520; // points materialised per second while filling
const HOLD_FULL = 4.0; // seconds to admire the complete even field
const DISSOLVE = 1.6; // seconds to fade the old set before re-seeding

const CYAN = new THREE.Color("#6ee7ff");
const PURPLE = new THREE.Color("#c084fc");
const PINK = new THREE.Color("#f472b6");

type Pt = { x: number; y: number; color: THREE.Color };

// ---- deterministic RNG (so each re-seed is distinct but reproducible) -------

function makeRng(seed: number) {
  let s = (seed * 2654435761) >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/**
 * Mitchell's best-candidate blue-noise in the unit square — the oracle's real
 * algorithm. Point 0 is uniform; to add point i, throw K uniform candidates and
 * keep the one whose nearest-neighbour distance to the existing set is largest
 * (the most isolated), pushing every new point into the biggest empty region.
 * Returns points in placement order plus the measured minimum pairwise distance.
 */
function blueNoise(count: number, seed: number): { pts: Pt[]; minDist: number } {
  const rand = makeRng(seed);
  const xs: number[] = [];
  const ys: number[] = [];
  const pts: Pt[] = [];

  for (let i = 0; i < count; i++) {
    let bx = 0;
    let by = 0;
    if (i === 0) {
      bx = rand();
      by = rand();
    } else {
      let bestGap = -1;
      const k = CANDIDATES;
      for (let c = 0; c < k; c++) {
        const cx = rand();
        const cy = rand();
        // nearest distance to any already-placed point
        let nearest = Infinity;
        for (let j = 0; j < xs.length; j++) {
          const dx = cx - xs[j];
          const dy = cy - ys[j];
          const d2 = dx * dx + dy * dy;
          if (d2 < nearest) nearest = d2;
          if (nearest === 0) break;
        }
        if (nearest > bestGap) {
          bestGap = nearest;
          bx = cx;
          by = cy;
        }
      }
    }
    xs.push(bx);
    ys.push(by);
    // palette bleed: hue follows position across the membrane (cyan→purple→pink)
    const t = (bx + by) * 0.5;
    const col =
      t < 0.5
        ? CYAN.clone().lerp(PURPLE, t * 2)
        : PURPLE.clone().lerp(PINK, (t - 0.5) * 2);
    pts.push({ x: bx, y: by, color: col });
  }

  // measured minimum pairwise distance — the quantitative blue-noise signature
  let minD2 = Infinity;
  for (let i = 0; i < xs.length; i++) {
    for (let j = i + 1; j < xs.length; j++) {
      const dx = xs[i] - xs[j];
      const dy = ys[i] - ys[j];
      const d2 = dx * dx + dy * dy;
      if (d2 < minD2) minD2 = d2;
    }
  }
  return { pts, minDist: Math.sqrt(minD2) };
}

/** Near-neighbour links (the organic mesh) — capped, built once per re-seed. */
function buildLinks(pts: Pt[]): [number, number][] {
  const links: [number, number][] = [];
  const max2 = MAX_LINK_DIST * MAX_LINK_DIST;
  for (let i = 0; i < pts.length && links.length < MAX_LINES; i++) {
    // collect this point's nearest few neighbours within the link radius
    const cand: { j: number; d2: number }[] = [];
    for (let j = 0; j < pts.length; j++) {
      if (j === i) continue;
      const dx = pts[i].x - pts[j].x;
      const dy = pts[i].y - pts[j].y;
      const d2 = dx * dx + dy * dy;
      if (d2 <= max2) cand.push({ j, d2 });
    }
    cand.sort((a, b) => a.d2 - b.d2);
    for (let n = 0; n < Math.min(NEIGHBOUR_LINKS, cand.length); n++) {
      const j = cand[n].j;
      if (j > i) links.push([i, j]); // dedup undirected edges
      if (links.length >= MAX_LINES) break;
    }
  }
  return links;
}

// ---- membrane mapping: lift the flat unit square onto an undulating shell ---

function surfacePos(
  x: number,
  y: number,
  t: number,
  out: THREE.Vector3
): THREE.Vector3 {
  // unit-square → centred X/Z plane
  const px = (x - 0.5) * 2 * SURFACE;
  const pz = (y - 0.5) * 2 * SURFACE;
  // travelling fbm-ish undulation so the whole sheet breathes & drifts
  const h =
    Math.sin(px * 0.32 + t * 0.6) * Math.cos(pz * 0.28 - t * 0.45) +
    0.5 * Math.sin(px * 0.6 - pz * 0.5 + t * 0.9);
  out.set(px, h * UNDULATE, pz);
  return out;
}

const _v = new THREE.Vector3();
const _scale = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _m = new THREE.Matrix4();

// ---- the shimmering point field (single instanced mesh, ~700 points) --------

function Membrane({
  pts,
  growT,
  fade,
}: {
  pts: Pt[];
  growT: React.MutableRefObject<number>; // how many points are currently "born"
  fade: React.MutableRefObject<number>; // 0..1 dissolve fade of the whole sheet
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const haloRef = useRef<THREE.InstancedMesh>(null);

  useFrame(({ clock }) => {
    const mesh = ref.current;
    const halo = haloRef.current;
    if (!mesh) return;
    const t = clock.elapsedTime;
    const born = Math.min(pts.length, Math.floor(growT.current));
    const f = fade.current;

    // bake per-instance colours once per set. setColorAt lazily allocates the
    // instanceColor buffer on first call, so guard with a baked marker.
    if ((mesh as any).__coloredN !== pts.length) {
      for (let i = 0; i < pts.length; i++) {
        mesh.setColorAt(i, pts[i].color);
        if (halo) halo.setColorAt(i, pts[i].color);
      }
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      if (halo && halo.instanceColor) halo.instanceColor.needsUpdate = true;
      (mesh as any).__coloredN = pts.length;
    }

    for (let i = 0; i < pts.length; i++) {
      surfacePos(pts[i].x, pts[i].y, t, _v);

      // per-point shimmer — size pulse, each point on its own phase
      const phase = (pts[i].x + pts[i].y) * 12.0 + i * 0.21;
      const shimmer = 0.78 + 0.42 * Math.sin(t * 2.4 + phase);

      // birth pop: newest points spring in, older ones settle
      let birth = 1;
      if (i >= born) birth = 0;
      else if (i > born - 14) birth = (born - i) / 14; // soft growth front

      const s = 0.052 * shimmer * birth * f;
      _scale.setScalar(Math.max(s, 0.0001));
      _q.identity();
      _m.compose(_v, _q, _scale);
      mesh.setMatrixAt(i, _m);

      if (halo) {
        const hs = 0.14 * shimmer * birth * f;
        _scale.setScalar(Math.max(hs, 0.0001));
        _m.compose(_v, _q, _scale);
        halo.setMatrixAt(i, _m);
      }
    }
    mesh.count = pts.length;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    if (halo) {
      halo.count = pts.length;
      halo.instanceMatrix.needsUpdate = true;
      if (halo.instanceColor) halo.instanceColor.needsUpdate = true;
    }
  });

  return (
    <group>
      {/* bright cores — bloom catches these as a field of even stars */}
      <instancedMesh
        ref={ref}
        args={[undefined as any, undefined as any, TARGET_COUNT]}
        frustumCulled={false}
      >
        <sphereGeometry args={[1, 10, 10]} />
        <meshStandardMaterial
          vertexColors
          emissive={"#ffffff"}
          emissiveIntensity={2.4}
          roughness={0.25}
          metalness={0.4}
          toneMapped={false}
        />
      </instancedMesh>

      {/* soft additive halos for the membrane glow */}
      <instancedMesh
        ref={haloRef}
        args={[undefined as any, undefined as any, TARGET_COUNT]}
        frustumCulled={false}
      >
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial
          vertexColors
          transparent
          opacity={0.22}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </instancedMesh>
    </group>
  );
}

// ---- the near-neighbour mesh (one merged line object, recolours over time) --

function MeshLinks({
  pts,
  links,
  growT,
  fade,
}: {
  pts: Pt[];
  links: [number, number][];
  growT: React.MutableRefObject<number>;
  fade: React.MutableRefObject<number>;
}) {
  // Raw THREE line segments (correctly-sized position attribute) — drei's <Line>
  // is a fat-line (Line2) with interleaved buffers, so a plain position write
  // overflows it; a native BufferGeometry is the correct, crash-free approach.
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute(
      "position",
      new THREE.BufferAttribute(new Float32Array(Math.max(links.length, 1) * 2 * 3), 3)
    );
    return g;
  }, [links]);
  const mat = useMemo(
    () =>
      new THREE.LineBasicMaterial({
        color: PURPLE.clone(),
        transparent: true,
        opacity: 0.14,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      }),
    []
  );

  useFrame(({ clock }) => {
    if (links.length === 0) return;
    const t = clock.elapsedTime;
    const born = Math.floor(growT.current);
    const arr = geom.attributes.position.array as Float32Array;
    for (let s = 0; s < links.length; s++) {
      const [a, b] = links[s];
      const visible = a < born && b < born;
      if (visible) {
        surfacePos(pts[a].x, pts[a].y, t, _v);
        arr[s * 6] = _v.x; arr[s * 6 + 1] = _v.y; arr[s * 6 + 2] = _v.z;
        surfacePos(pts[b].x, pts[b].y, t, _v);
        arr[s * 6 + 3] = _v.x; arr[s * 6 + 4] = _v.y; arr[s * 6 + 5] = _v.z;
      } else {
        for (let k = 0; k < 6; k++) arr[s * 6 + k] = 0;
      }
    }
    geom.attributes.position.needsUpdate = true;
    mat.opacity = (0.12 + 0.06 * Math.sin(t * 0.8)) * fade.current;
  });

  if (links.length === 0) return null;
  return <lineSegments geometry={geom} material={mat} frustumCulled={false} />;
}

// ---- main scene -------------------------------------------------------------

export default function Scene() {
  const group = useRef<THREE.Group>(null);

  // mutable lifecycle state (no re-render while animating individual points)
  const life = useRef({
    seed: 7,
    phase: "grow" as "grow" | "hold" | "dissolve",
    growT: 0, // points materialised so far (float, drives the growth front)
    holdT: 0,
    dissolveT: 0,
    fade: 1, // whole-sheet fade (1 solid, 0 gone) — eased
  });

  // refs the child meshes read every frame
  const growRef = useRef(0);
  const fadeRef = useRef(1);

  const [set, setSet] = useState(() => {
    const bn = blueNoise(TARGET_COUNT, 7);
    return { pts: bn.pts, minDist: bn.minDist, links: buildLinks(bn.pts) };
  });
  const [minDist, setMinDist] = useState(set.minDist);

  useFrame((_, delta) => {
    const L = life.current;
    const d = Math.min(delta, 0.05); // clamp tab-restore spikes

    if (L.phase === "grow") {
      L.growT += d * GROW_PER_SEC;
      L.fade += (1 - L.fade) * Math.min(1, d * 6);
      if (L.growT >= TARGET_COUNT) {
        L.growT = TARGET_COUNT;
        L.phase = "hold";
        L.holdT = 0;
      }
    } else if (L.phase === "hold") {
      L.holdT += d;
      L.fade += (1 - L.fade) * Math.min(1, d * 6);
      if (L.holdT >= HOLD_FULL) {
        L.phase = "dissolve";
        L.dissolveT = 0;
      }
    } else {
      // dissolve: fade the whole even field out, then re-seed a fresh one
      L.dissolveT += d;
      L.fade += (0 - L.fade) * Math.min(1, d * 3.5);
      if (L.dissolveT >= DISSOLVE) {
        const seed = L.seed + 1;
        const bn = blueNoise(TARGET_COUNT, seed);
        setSet({ pts: bn.pts, minDist: bn.minDist, links: buildLinks(bn.pts) });
        setMinDist(bn.minDist);
        L.seed = seed;
        L.phase = "grow";
        L.growT = 0;
        L.fade = 0;
      }
    }

    growRef.current = L.growT;
    fadeRef.current = L.fade;

    // slow drift layered over the canvas auto-rotate — living membrane
    if (group.current) {
      group.current.rotation.y += d * 0.03;
      const tilt = Math.sin(performance.now() * 0.0001) * 0.06;
      group.current.rotation.x = -0.18 + tilt;
    }
  });

  return (
    <group ref={group}>
      <MeshLinks
        pts={set.pts}
        links={set.links}
        growT={growRef}
        fade={fadeRef}
      />
      <Membrane pts={set.pts} growT={growRef} fade={fadeRef} />

      {/* live measured min-distance — the blue-noise signature the oracle sells */}
      <Billboard position={[0, UNDULATE + 3.4, 0]}>
        <Text
          fontSize={0.5}
          color="#6ee7ff"
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.014}
          outlineColor="#04121a"
        >
          {`min distance ${minDist.toFixed(3)}`}
        </Text>
        <Text
          position={[0, -0.62, 0]}
          fontSize={0.26}
          color="#c084fc"
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.01}
          outlineColor="#120420"
        >
          {`blue-noise · ${TARGET_COUNT} pts · even, never clumped`}
        </Text>
      </Billboard>
    </group>
  );
}
