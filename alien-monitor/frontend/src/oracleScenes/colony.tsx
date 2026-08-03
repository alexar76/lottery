import { useMemo, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import { Billboard, Instance, Instances, Line, Text } from "@react-three/drei";
import * as THREE from "three";

/**
 * Colony oracle — Euclidean TSP solved by nearest-neighbour construction + 2-opt
 * local search, sold with an admissible lower bound and an optimality `gap`.
 *
 * Signature motif: ~14 emissive city NODES scattered in 3D, joined by a glowing
 * closed TOUR loop. A couple of real 2-opt swaps are applied per second on the
 * actual coordinates, so the path visibly UNTANGLES and shortens. The golden
 * pheromone glow on the tour brightens as the optimality gap closes; once the
 * tour is near-optimal the colony reseeds a fresh set of cities and the search
 * begins again. Camera (provided by CosmicCanvas) looks slightly top-down.
 */

const N_CITIES = 14;
const SPREAD = 5.2; // half-extent of the city cloud on X/Z
const Y_SPREAD = 1.7; // vertical scatter so the loop reads as 3D
const SWAPS_PER_SEC = 2.4; // real 2-opt candidate sweeps per second
const NEAR_OPTIMAL_GAP = 0.02; // reseed once the tour is within 2% of 2-optimal
const HOLD_AFTER_SOLVE = 2.6; // seconds to admire the solved tour before reseed

const CYAN = "#6ee7ff";
const PURPLE = "#c084fc";
const PINK = "#f472b6";
const GOLD = "#ffd479";

type Vec3 = [number, number, number];

// ---- pure TSP helpers (mirror oracles/colony/colony/tsp.py) -----------------

function dist(a: Vec3, b: Vec3): number {
  const dx = a[0] - b[0];
  const dy = a[1] - b[1];
  const dz = a[2] - b[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

function tourLength(tour: number[], pts: Vec3[]): number {
  let total = 0;
  for (let i = 0; i < tour.length; i++) {
    total += dist(pts[tour[i]], pts[tour[(i + 1) % tour.length]]);
  }
  return total;
}

/** Greedy nearest-neighbour construction from `start`. */
function nearestNeighbour(pts: Vec3[], start = 0): number[] {
  const n = pts.length;
  const visited = new Array<boolean>(n).fill(false);
  const tour = [start];
  visited[start] = true;
  let current = start;
  for (let step = 1; step < n; step++) {
    let best = -1;
    let bestD = Infinity;
    for (let j = 0; j < n; j++) {
      if (visited[j]) continue;
      const d = dist(pts[current], pts[j]);
      if (d < bestD) {
        bestD = d;
        best = j;
      }
    }
    visited[best] = true;
    tour.push(best);
    current = best;
  }
  return tour;
}

/** Sum of each node's cheapest incident edge / 2 — an admissible lower bound. */
function lowerBound(pts: Vec3[]): number {
  const n = pts.length;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    let m = Infinity;
    for (let j = 0; j < n; j++) {
      if (i === j) continue;
      const d = dist(pts[i], pts[j]);
      if (d < m) m = d;
    }
    sum += m;
  }
  return sum / 2;
}

/**
 * One pass of 2-opt: scan edge pairs and apply the FIRST improving segment
 * reversal found (replace edges (a,b),(c,d) with (a,c),(b,d)). Returns whether
 * the tour was changed — exactly the inner mechanic of the Python `two_opt`,
 * sliced into incremental steps so the untangling is visible frame-to-frame.
 */
function twoOptStep(tour: number[], pts: Vec3[]): boolean {
  const n = tour.length;
  if (n < 4) return false;
  for (let i = 1; i < n - 1; i++) {
    const a = tour[i - 1];
    const b = tour[i];
    for (let k = i + 1; k < n; k++) {
      const c = tour[k];
      const d = tour[(k + 1) % n];
      if (d === a) continue;
      const before = dist(pts[a], pts[b]) + dist(pts[c], pts[d]);
      const after = dist(pts[a], pts[c]) + dist(pts[b], pts[d]);
      if (after + 1e-9 < before) {
        // reverse the segment tour[i..k]
        let lo = i;
        let hi = k;
        while (lo < hi) {
          const tmp = tour[lo];
          tour[lo] = tour[hi];
          tour[hi] = tmp;
          lo++;
          hi--;
        }
        return true;
      }
    }
  }
  return false;
}

// ---- city generation --------------------------------------------------------

function makeCities(seed: number): Vec3[] {
  // deterministic-ish hashed scatter so each reseed feels distinct
  const pts: Vec3[] = [];
  let s = (seed * 2654435761) >>> 0;
  const rand = () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
  for (let i = 0; i < N_CITIES; i++) {
    const ang = rand() * Math.PI * 2;
    const r = (0.35 + rand() * 0.65) * SPREAD;
    pts.push([
      Math.cos(ang) * r + (rand() - 0.5) * 1.4,
      (rand() - 0.5) * 2 * Y_SPREAD,
      Math.sin(ang) * r + (rand() - 0.5) * 1.4,
    ]);
  }
  return pts;
}

// ---- emissive city nodes (instanced) ---------------------------------------

function Cities({ pts, pulse }: { pts: Vec3[]; pulse: number }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  return (
    <Instances ref={ref as any} limit={64} range={pts.length}>
      <icosahedronGeometry args={[0.16, 1]} />
      <meshStandardMaterial
        color={CYAN}
        emissive={CYAN}
        emissiveIntensity={2.4}
        roughness={0.2}
        metalness={0.6}
        toneMapped={false}
      />
      {pts.map((p, i) => (
        <CityInstance key={i} position={p} index={i} pulse={pulse} />
      ))}
    </Instances>
  );
}

function CityInstance({
  position,
  index,
  pulse,
}: {
  position: Vec3;
  index: number;
  pulse: number;
}) {
  const ref = useRef<any>(null);
  useFrame(({ clock }) => {
    if (!ref.current) return;
    const t = clock.elapsedTime;
    const s = 1 + Math.sin(t * 2.2 + index * 0.7) * 0.18 + pulse * 0.5;
    ref.current.scale.setScalar(s);
  });
  return <Instance ref={ref} position={position} />;
}

/** Soft outer glow halos around each city so Bloom catches them as beacons. */
function CityHalos({ pts }: { pts: Vec3[] }) {
  return (
    <Instances limit={64} range={pts.length}>
      <sphereGeometry args={[0.34, 12, 12]} />
      <meshBasicMaterial
        color={PURPLE}
        transparent
        opacity={0.16}
        toneMapped={false}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />
      {pts.map((p, i) => (
        <Instance key={i} position={p} />
      ))}
    </Instances>
  );
}

// ---- main scene -------------------------------------------------------------

export default function Scene() {
  const group = useRef<THREE.Group>(null);

  // mutable solver state held in a ref so useFrame can mutate without re-render
  const solver = useRef({
    seed: 1,
    pts: [] as Vec3[],
    tour: [] as number[],
    nnLen: 1,
    lb: 1,
    len: 1,
    gap: 1,
    solved: false,
    holdT: 0,
    swapAcc: 0,
    glow: 0.3, // pheromone intensity, eased toward improvement
  });

  const init = (seed: number) => {
    const pts = makeCities(seed);
    const tour = nearestNeighbour(pts, 0);
    const nnLen = tourLength(tour, pts);
    const lb = lowerBound(pts);
    solver.current = {
      seed,
      pts,
      tour,
      nnLen,
      lb: lb > 1e-6 ? lb : 1,
      len: nnLen,
      gap: lb > 1e-6 ? (nnLen - lb) / lb : 0,
      solved: false,
      holdT: 0,
      swapAcc: 0,
      glow: solver.current ? solver.current.glow : 0.3,
    };
  };

  // lazy first init
  if (solver.current.pts.length === 0) init(1);

  // React-visible mirrors so node positions + the line re-render on reseed/swap
  const [pts, setPts] = useState<Vec3[]>(() => solver.current.pts);
  const [linePts, setLinePts] = useState<Vec3[]>(() =>
    closedLoopPoints(solver.current.tour, solver.current.pts)
  );
  const [glow, setGlow] = useState(0.3);
  const [gap, setGap] = useState(solver.current.gap);

  useFrame((_, delta) => {
    const S = solver.current;
    const d = Math.min(delta, 0.05); // clamp big tab-restore deltas

    if (!S.solved) {
      // budget a couple of real 2-opt sweeps per second
      S.swapAcc += d * SWAPS_PER_SEC;
      let mutatedThisFrame = false;
      let consumedBudget = false;
      let exhausted = false; // a budgeted step found no improving move
      while (S.swapAcc >= 1) {
        S.swapAcc -= 1;
        consumedBudget = true;
        const did = twoOptStep(S.tour, S.pts);
        if (did) {
          mutatedThisFrame = true;
        } else {
          // no improving 2-opt move exists → tour is 2-optimal
          exhausted = true;
          break;
        }
      }
      if (mutatedThisFrame) {
        S.len = tourLength(S.tour, S.pts);
        S.gap = (S.len - S.lb) / S.lb;
        setLinePts(closedLoopPoints(S.tour, S.pts));
        setGap(S.gap);
      }
      // Reseed trigger: 2-optimal (no improving move) OR within the
      // near-optimal gap certificate against the admissible lower bound.
      if ((consumedBudget && exhausted) || S.gap <= NEAR_OPTIMAL_GAP) {
        S.solved = true;
        S.holdT = 0;
      }
    } else {
      S.holdT += d;
      if (S.holdT >= HOLD_AFTER_SOLVE) {
        init(S.seed + 1);
        setPts(solver.current.pts);
        setLinePts(closedLoopPoints(solver.current.tour, solver.current.pts));
        setGap(solver.current.gap);
      }
    }

    // pheromone glow: brighter as the tour shortens toward the lower bound.
    // progress 0 (raw NN tour) → 1 (down to the admissible bound).
    const span = Math.max(S.nnLen - S.lb, 1e-3);
    const progress = THREE.MathUtils.clamp((S.nnLen - S.len) / span, 0, 1);
    const target = 0.35 + progress * 1.65 + (S.solved ? 0.4 : 0);
    S.glow += (target - S.glow) * Math.min(1, d * 4);
    setGlow(S.glow);

    // gentle breathing rotation layered atop the canvas auto-rotate
    if (group.current) {
      group.current.rotation.y += d * 0.04;
    }
  });

  const cityPulse = useMemo(() => (glow > 1.3 ? (glow - 1.3) * 0.6 : 0), [glow]);

  // golden, brightening tour with a faint cyan under-trace for depth
  const tourColor = useMemo(() => {
    const g = THREE.MathUtils.clamp((glow - 0.35) / 1.65, 0, 1);
    return new THREE.Color(GOLD).lerp(new THREE.Color(PINK), 0.15 + g * 0.0);
  }, [glow]);

  return (
    <group ref={group}>
      {/* the closed tour loop — pheromone path */}
      <Line
        points={linePts}
        color={tourColor}
        lineWidth={2.4}
        transparent
        opacity={0.55 + Math.min(glow, 2) * 0.22}
        toneMapped={false}
      />
      {/* faint wide aura under the path that swells with the pheromone glow */}
      <Line
        points={linePts}
        color={GOLD}
        lineWidth={7}
        transparent
        opacity={0.05 + Math.min(glow, 2) * 0.12}
        toneMapped={false}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />

      <Cities pts={pts} pulse={cityPulse} />
      <CityHalos pts={pts} />

      {/* live optimality-gap certificate, the oracle's actual product */}
      <Billboard position={[0, Y_SPREAD + 2.0, 0]}>
        <Text
          fontSize={0.42}
          color={GOLD}
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.012}
          outlineColor="#1a1206"
        >
          {`gap ${(gap * 100).toFixed(1)}%`}
        </Text>
      </Billboard>
    </group>
  );
}

// ---- geometry helper --------------------------------------------------------

function closedLoopPoints(tour: number[], pts: Vec3[]): Vec3[] {
  if (tour.length === 0) return [];
  const out: Vec3[] = tour.map((i) => pts[i]);
  out.push(pts[tour[0]]); // close the loop back to the start
  return out;
}
