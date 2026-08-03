import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Line, Billboard, Text, Trail } from "@react-three/drei";
import * as THREE from "three";

/**
 * SORTES — a true ECVRF (RFC 9381, ECVRF-EDWARDS25519-SHA512-TAI).
 *
 * Sortes draws lots you can verify. For a fixed (public key, input alpha) there
 * is exactly ONE valid VRF output beta — the secret key selects it; the oracle
 * cannot grind it. The motif is "THE ONE GEODESIC":
 *
 *   The torus is the curve (edwards25519). SIX faint ghostly candidate arcs
 *   shimmer over it — the un-chosen outputs / the try-and-increment candidates,
 *   everything the oracle could *pretend* to draw. They drift, then CONVERGE and
 *   COLLAPSE into ONE brilliant GOLD geodesic that wraps the torus, and a bright
 *   point traces it: the single output bound to (PK, alpha), ungrindable. Brief
 *   hold, then reset and the ghosts return.
 *
 * Renders inside CosmicCanvas (camera / lights / nebula / bloom provided).
 */

// ---- palette -------------------------------------------------------------
const GOLD = new THREE.Color("#fde047");
const GOLD_HOT = new THREE.Color("#fffbe0");
const GHOST = new THREE.Color("#7c6f9e"); // faint un-chosen violet
const TORUS_COL = new THREE.Color("#3a2f6e");

// ---- torus geometry ------------------------------------------------------
const R = 3.2; // major radius (ring center -> tube center)
const r = 1.05; // minor radius (tube)
const ARC_SEGMENTS = 240;

// A point on the torus surface for toroidal angle u and poloidal angle v.
function torusPoint(u: number, v: number, out: THREE.Vector3): THREE.Vector3 {
  const cu = Math.cos(u);
  const su = Math.sin(u);
  const cv = Math.cos(v);
  const sv = Math.sin(v);
  out.set((R + r * cv) * cu, r * sv, (R + r * cv) * su);
  return out;
}

/**
 * A (p,q) torus knot / geodesic-like winding curve sampled into points. The
 * gold "chosen" geodesic uses a coprime winding so it wraps the whole torus as
 * one unbroken closed curve; each ghost uses its own phase + winding so they
 * read as distinct candidates before they collapse onto the chosen one.
 */
function windingCurve(
  p: number,
  q: number,
  phase: number,
  segments: number
): THREE.Vector3[] {
  const pts: THREE.Vector3[] = [];
  const tmp = new THREE.Vector3();
  for (let i = 0; i <= segments; i++) {
    const t = (i / segments) * Math.PI * 2;
    torusPoint(p * t + phase, q * t + phase * 1.7, tmp);
    pts.push(tmp.clone());
  }
  return pts;
}

const GHOST_COUNT = 6;

export default function Scene() {
  const group = useRef<THREE.Group>(null);
  const ghostRefs = useRef<(any | null)[]>([]);
  const goldRef = useRef<any>(null);
  const goldGlowRef = useRef<any>(null);
  const tracerRef = useRef<THREE.Group>(null);
  const tracerCoreRef = useRef<THREE.Mesh>(null);
  const tracerHaloRef = useRef<THREE.Mesh>(null);
  const torusRef = useRef<THREE.Mesh>(null);

  // The single CHOSEN geodesic: a (2,5) winding wraps the torus densely as one
  // closed gold thread — "the one output".
  const goldPts = useMemo(
    () => windingCurve(2, 5, 0, ARC_SEGMENTS),
    []
  );
  const goldLinePts = useMemo(
    () => goldPts.map((p) => p.clone()),
    [goldPts]
  );

  // Six ghost candidates: each its own winding + phase so they look like
  // distinct un-chosen draws. Their "home" (scattered) curves and their
  // collapse target (the gold geodesic) are both precomputed.
  const ghosts = useMemo(() => {
    const windings: [number, number][] = [
      [3, 7], [1, 4], [4, 9], [2, 3], [5, 8], [3, 5],
    ];
    return windings.map(([p, q], i) => {
      const phase = (i / GHOST_COUNT) * Math.PI * 2;
      return {
        home: windingCurve(p, q, phase, ARC_SEGMENTS),
        target: goldPts, // collapse onto the chosen geodesic
        phase,
      };
    });
  }, [goldPts]);

  // scratch (no per-frame allocation)
  const scratch = useMemo(
    () => Array.from({ length: ARC_SEGMENTS + 1 }, () => new THREE.Vector3()),
    []
  );
  const tracerPos = useMemo(() => new THREE.Vector3(), []);
  const tmpA = useMemo(() => new THREE.Vector3(), []);
  const tmpB = useMemo(() => new THREE.Vector3(), []);

  const LOOP = 13; // seconds: ghosts in -> converge -> ignite -> hold -> reset

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const phase = (t % LOOP) / LOOP;

    // slow cinematic drift of the whole torus
    if (group.current) {
      group.current.rotation.y = t * 0.14;
      group.current.rotation.x = 0.5 + Math.sin(t * 0.16) * 0.12;
    }
    if (torusRef.current) {
      const m = torusRef.current.material as THREE.MeshStandardMaterial;
      m.emissiveIntensity = 0.32 + Math.sin(t * 0.7) * 0.06;
    }

    // Timeline phases:
    //   0.00-0.45  ghosts drift, scattered (the candidates shimmer)
    //   0.45-0.70  ghosts CONVERGE onto the chosen geodesic (collapse)
    //   0.62-0.80  gold geodesic IGNITES (fade in)
    //   0.70-0.95  bright point TRACES the gold geodesic
    //   0.95-1.00  hold, then reset
    const converge = smoothstep(0.45, 0.7, phase); // 0..1 ghost->gold blend
    const ignite = smoothstep(0.62, 0.8, phase); // gold opacity
    const fade = 1 - smoothstep(0.82, 0.98, phase); // everything fades at the end

    // ---- ghosts: drift, then collapse onto the gold geodesic ----------
    for (let g = 0; g < GHOST_COUNT; g++) {
      const lineObj = ghostRefs.current[g];
      if (!lineObj) continue;
      const ghost = ghosts[g];
      // gentle shimmer drift while scattered
      const drift = (1 - converge) * (0.12 + 0.05 * Math.sin(t * 1.3 + g));
      for (let i = 0; i <= ARC_SEGMENTS; i++) {
        const home = ghost.home[i];
        const tgt = ghost.target[i];
        const out = scratch[i];
        // breathe the home curve slightly outward, then lerp to the target
        tmpA.copy(home).multiplyScalar(1 + drift * Math.sin(i * 0.18 + t + g));
        out.copy(tmpA).lerp(tgt, converge);
      }
      const geo = lineObj.geometry as THREE.BufferGeometry;
      if (geo && typeof lineObj.setPoints === "function") {
        lineObj.setPoints(scratch);
      } else if (geo) {
        const pos = geo.attributes.position as THREE.BufferAttribute | undefined;
        if (pos) {
          for (let i = 0; i <= ARC_SEGMENTS; i++)
            pos.setXYZ(i, scratch[i].x, scratch[i].y, scratch[i].z);
          pos.needsUpdate = true;
        }
      }
      const mat = lineObj.material as any;
      if (mat) {
        // bright-ish while scattered, then dissolve into the gold as they merge
        const base = 0.16 + 0.10 * Math.sin(t * 2 + g * 1.1);
        mat.opacity = Math.max(0, (base * (1 - converge * 0.9))) * fade;
      }
    }

    // ---- the chosen gold geodesic: ignite -----------------------------
    if (goldRef.current) {
      const mat = goldRef.current.material as any;
      if (mat) mat.opacity = ignite * 0.95 * fade;
    }
    if (goldGlowRef.current) {
      const mat = goldGlowRef.current.material as any;
      if (mat) mat.opacity = ignite * 0.34 * fade * (0.8 + 0.2 * Math.sin(t * 5));
    }

    // ---- the tracer: a brilliant point running the gold geodesic ------
    const tracing = smoothstep(0.7, 0.72, phase) * (1 - smoothstep(0.93, 0.97, phase));
    const traceU = smoothstep(0.7, 0.95, phase); // 0..1 progress along curve
    const fIdx = traceU * ARC_SEGMENTS;
    const i0 = Math.min(ARC_SEGMENTS - 1, Math.floor(fIdx));
    tmpA.copy(goldPts[i0]);
    tmpB.copy(goldPts[i0 + 1]);
    tracerPos.copy(tmpA).lerp(tmpB, fIdx - i0);
    if (tracerRef.current) {
      tracerRef.current.position.copy(tracerPos);
      tracerRef.current.visible = tracing > 0.01 && ignite > 0.2;
    }
    if (tracerCoreRef.current) {
      const pulse = 1 + Math.sin(t * 12) * 0.14;
      tracerCoreRef.current.scale.setScalar(pulse);
    }
    if (tracerHaloRef.current) {
      const hm = tracerHaloRef.current.material as THREE.MeshBasicMaterial;
      hm.opacity = 0.5 * tracing * fade;
      tracerHaloRef.current.scale.setScalar(1.5 + Math.sin(t * 6) * 0.2);
    }
  });

  return (
    <group ref={group} rotation={[0.5, 0, 0]}>
      {/* THE CURVE — a glowing torus surface = edwards25519. Dark, faintly
          emissive so Bloom only kisses the arcs that ride on it. */}
      <mesh ref={torusRef}>
        <torusGeometry args={[R, r, 40, 220]} />
        <meshStandardMaterial
          color="#140f30"
          emissive={TORUS_COL}
          emissiveIntensity={0.34}
          roughness={0.55}
          metalness={0.35}
          transparent
          opacity={0.92}
        />
      </mesh>

      {/* SIX GHOST CANDIDATES — un-chosen outputs shimmering on the surface,
          then collapsing onto the one geodesic. Faint violet. */}
      {ghosts.map((ghost, g) => (
        <Line
          key={g}
          ref={(el: any) => (ghostRefs.current[g] = el)}
          points={ghost.home}
          color={GHOST}
          lineWidth={1.3}
          transparent
          opacity={0.18}
          toneMapped={false}
        />
      ))}

      {/* THE ONE GOLD GEODESIC — the single VRF output bound to (PK, alpha).
          A bright core line plus a soft wide glow line beneath it. */}
      <Line
        ref={goldGlowRef}
        points={goldLinePts}
        color={GOLD}
        lineWidth={7}
        transparent
        opacity={0}
        depthWrite={false}
        toneMapped={false}
      />
      <Line
        ref={goldRef}
        points={goldLinePts}
        color={GOLD_HOT}
        lineWidth={3}
        transparent
        opacity={0}
        toneMapped={false}
      />

      {/* THE TRACER — a brilliant point that runs the gold geodesic once it
          ignites, leaving a short gold trail. */}
      <group ref={tracerRef} visible={false}>
        <Trail width={3} length={5} color={GOLD} attenuation={(w) => w * w}>
          <mesh ref={tracerCoreRef}>
            <sphereGeometry args={[0.14, 24, 24]} />
            <meshStandardMaterial
              color="#ffffff"
              emissive={GOLD_HOT}
              emissiveIntensity={3.2}
              toneMapped={false}
            />
          </mesh>
        </Trail>
        <mesh ref={tracerHaloRef}>
          <sphereGeometry args={[0.3, 20, 20]} />
          <meshBasicMaterial
            color={GOLD}
            transparent
            opacity={0}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            toneMapped={false}
          />
        </mesh>
        <pointLight color="#fde047" intensity={2.2} distance={7} decay={2} />
      </group>

      {/* Concept label — faces the camera, drifts with the motif. */}
      <Billboard position={[0, -R - 1.0, 0]}>
        <Text
          fontSize={0.42}
          color="#fde047"
          anchorX="center"
          anchorY="middle"
          outlineWidth={0}
          letterSpacing={0.12}
        >
          {"β = VRF_sk(α)  ·  bound to (PK, α)"}
        </Text>
      </Billboard>
    </group>
  );
}

// smoothstep(edge0, edge1, x)
function smoothstep(e0: number, e1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
}
