import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Line, Instances, Instance, Billboard, Text } from "@react-three/drei";
import * as THREE from "three";

/**
 * CHRONOS — Verifiable Delay Function (Wesolowski VDF).
 *
 * The oracle sells *time you can verify*: y = g^(2^T) mod N, computed by T
 * repeated squarings y_i = y_{i-1}^2 mod N. Each squaring depends on the one
 * before it, so the chain is inherently SEQUENTIAL — more cores cannot help.
 *
 * The signature motif renders exactly that: a single luminous HELIX-THREAD of
 * emissive beads (each bead = one squaring), laid down one-by-one along a
 * parametric helix by a brilliant white comet-HEAD at the frontier. The thread
 * is ONE unbroken line (never a parallel field). When the head reaches the end
 * it resets and the chain regrows — the loop. Color ramps cyan -> purple ->
 * pink along the thread (the deepening of elapsed time). Slowly drifts/rotates.
 */

// ---- palette -------------------------------------------------------------
const CYAN = new THREE.Color("#6ee7ff");
const PURPLE = new THREE.Color("#c084fc");
const PINK = new THREE.Color("#f472b6");
const WHITE = new THREE.Color("#ffffff");

// cyan -> purple -> pink ramp over u in [0,1]
function rampColor(u: number, out: THREE.Color): THREE.Color {
  if (u < 0.5) out.copy(CYAN).lerp(PURPLE, u / 0.5);
  else out.copy(PURPLE).lerp(PINK, (u - 0.5) / 0.5);
  return out;
}

// ---- helix geometry ------------------------------------------------------
// A tilted helix whose radius grows with the winding — the "deepening" of
// sequential time. One bead per squaring step.
const BEADS = 460; // T sequential squarings (capped for 60fps)
const TURNS = 5.5; // windings
const HEIGHT = 9.0; // axial length of the helix
const R0 = 0.55; // starting radius
const R1 = 3.2; // ending radius
const TILT = 0.42; // radians the whole helix is tilted in 3D

function helixPoint(i: number, out: THREE.Vector3): THREE.Vector3 {
  const u = i / (BEADS - 1); // 0..1 along the chain
  const ang = u * TURNS * Math.PI * 2;
  const r = R0 + (R1 - R0) * Math.pow(u, 0.85);
  const y = -HEIGHT * 0.5 + HEIGHT * u;
  out.set(Math.cos(ang) * r, y, Math.sin(ang) * r);
  return out;
}

export default function Scene() {
  const group = useRef<THREE.Group>(null);
  const beadsRef = useRef<THREE.InstancedMesh>(null);
  const headRef = useRef<THREE.Group>(null);
  const headCoreRef = useRef<THREE.Mesh>(null);
  const lineRef = useRef<any>(null);
  const haloRef = useRef<THREE.Mesh>(null);

  // Precompute every helix bead position + its ramp colour. Tilt is applied to
  // the whole group so the line, beads and head stay perfectly coincident.
  const { positions, colors, linePts } = useMemo(() => {
    const positions: THREE.Vector3[] = [];
    const colors: THREE.Color[] = [];
    const linePts: THREE.Vector3[] = [];
    const tmp = new THREE.Vector3();
    const col = new THREE.Color();
    for (let i = 0; i < BEADS; i++) {
      const p = helixPoint(i, tmp).clone();
      positions.push(p);
      linePts.push(p.clone());
      colors.push(rampColor(i / (BEADS - 1), col).clone());
    }
    return { positions, colors, linePts };
  }, []);

  // Per-vertex colours so the drei <Line> shows the cyan->purple->pink ramp.
  const vertexColors = useMemo(
    () => colors.map((c) => [c.r, c.g, c.b] as [number, number, number]),
    [colors]
  );

  // scratch objects (no per-frame allocation)
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const tmpColor = useMemo(() => new THREE.Color(), []);
  const headPos = useMemo(() => new THREE.Vector3(), []);
  const headColor = useMemo(() => new THREE.Color(), []);

  const LOOP = 16; // seconds for the head to traverse + a short hold/reset

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;

    // slow cinematic drift of the whole motif
    if (group.current) {
      group.current.rotation.y = t * 0.12;
      group.current.rotation.x = TILT + Math.sin(t * 0.18) * 0.08;
      group.current.position.y = Math.sin(t * 0.25) * 0.35;
    }

    // ---- the frontier: where the comet-head currently is --------------
    // phase in [0,1): grow for ~85% of the loop, then a brief glow-hold before
    // the chain resets and regrows. Smoothstep ease-out at the very end.
    const phase = (t % LOOP) / LOOP;
    const grow = Math.min(1, phase / 0.85); // 0..1 then clamps
    const eased = grow * grow * (3 - 2 * grow); // smoothstep
    const frontier = eased * (BEADS - 1); // fractional bead index of the head
    const frontierI = Math.floor(frontier);

    // ---- beads: light up only those already laid by the head ----------
    if (beadsRef.current) {
      for (let i = 0; i < BEADS; i++) {
        const laid = i <= frontierI;
        // recently-laid beads flare brighter, then settle — a travelling pulse
        const dist = frontier - i;
        const fresh = laid ? Math.exp(-dist * dist * 0.06) : 0;
        const baseS = laid ? 0.085 + 0.02 * Math.sin(t * 3 + i * 0.6) : 0.0001;
        const s = baseS + fresh * 0.16;
        const p = positions[i];
        dummy.position.copy(p);
        dummy.scale.setScalar(s);
        dummy.updateMatrix();
        beadsRef.current.setMatrixAt(i, dummy.matrix);

        // colour = ramp, brightened toward white near the frontier
        tmpColor.copy(colors[i]);
        if (laid) tmpColor.lerp(WHITE, fresh * 0.8);
        else tmpColor.multiplyScalar(0.0);
        beadsRef.current.setColorAt(i, tmpColor);
      }
      beadsRef.current.instanceMatrix.needsUpdate = true;
      if (beadsRef.current.instanceColor)
        beadsRef.current.instanceColor.needsUpdate = true;
    }

    // ---- the glowing thread: reveal it progressively ------------------
    // drei <Line> exposes geometry.setDrawRange so the line literally grows
    // bead-by-bead as ONE unbroken sequential thread.
    if (lineRef.current) {
      const drawn = Math.max(2, Math.min(BEADS, frontierI + 2));
      const geo = lineRef.current.geometry as THREE.BufferGeometry;
      // Line2 uses segment instances; safest cross-version reveal is drawRange
      // on the underlying geometry (falls back gracefully if unsupported).
      if (geo && typeof geo.setDrawRange === "function") {
        geo.setDrawRange(0, drawn);
      }
      const mat = lineRef.current.material as any;
      if (mat) mat.opacity = 0.85;
    }

    // ---- the comet-head at the frontier -------------------------------
    // Interpolate between the two bracketing beads for buttery motion.
    const a = positions[frontierI];
    const b = positions[Math.min(BEADS - 1, frontierI + 1)];
    headPos.copy(a).lerp(b, frontier - frontierI);
    rampColor(eased, headColor);
    headColor.lerp(WHITE, 0.7); // brilliant white-hot frontier

    if (headRef.current) {
      headRef.current.position.copy(headPos);
    }
    if (headCoreRef.current) {
      const pulse = 1 + Math.sin(t * 9) * 0.12;
      headCoreRef.current.scale.setScalar(pulse);
      const m = headCoreRef.current.material as THREE.MeshStandardMaterial;
      m.emissive.copy(headColor);
    }
    if (haloRef.current) {
      const hp = 1.4 + Math.sin(t * 4) * 0.18;
      haloRef.current.scale.setScalar(hp);
      const hm = haloRef.current.material as THREE.MeshBasicMaterial;
      hm.color.copy(headColor);
      hm.opacity = 0.22 + Math.sin(t * 4) * 0.05;
    }
  });

  return (
    <group ref={group} rotation={[TILT, 0, 0]}>
      {/* THE THREAD — one unbroken sequential line, cyan->purple->pink ramp.
          Grows via setDrawRange so it reads as non-parallelizable time. */}
      <Line
        ref={lineRef}
        points={linePts}
        vertexColors={vertexColors}
        lineWidth={2.4}
        transparent
        opacity={0.85}
        toneMapped={false}
      />

      {/* THE BEADS — one emissive sphere per squaring, instanced for 60fps.
          meshStandardMaterial w/ emissive so Bloom blooms each one. */}
      <Instances ref={beadsRef as any} limit={BEADS} range={BEADS}>
        <sphereGeometry args={[1, 12, 12]} />
        <meshStandardMaterial
          emissive={CYAN}
          emissiveIntensity={2.4}
          color="#000000"
          roughness={0.3}
          metalness={0.1}
          toneMapped={false}
        />
        {positions.map((_, i) => (
          <Instance key={i} color={colors[i]} />
        ))}
      </Instances>

      {/* THE COMET-HEAD — brilliant white frontier laying new beads. */}
      <group ref={headRef}>
        <mesh ref={headCoreRef}>
          <sphereGeometry args={[0.16, 24, 24]} />
          <meshStandardMaterial
            color="#ffffff"
            emissive={WHITE}
            emissiveIntensity={3}
            toneMapped={false}
          />
        </mesh>
        {/* soft glow halo (basic so it always blooms) */}
        <mesh ref={haloRef}>
          <sphereGeometry args={[0.34, 20, 20]} />
          <meshBasicMaterial
            color="#ffffff"
            transparent
            opacity={0.22}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            toneMapped={false}
          />
        </mesh>
        {/* a faint point of light travelling with the head */}
        <pointLight color="#ffffff" intensity={1.4} distance={6} decay={2} />
      </group>

      {/* Concept label — drifts with the motif, faces the camera. */}
      <Billboard position={[0, -HEIGHT * 0.5 - 1.1, 0]}>
        <Text
          fontSize={0.4}
          color="#6ee7ff"
          anchorX="center"
          anchorY="middle"
          outlineWidth={0}
          letterSpacing={0.18}
        >
          {"y = g^(2^T) mod N"}
        </Text>
      </Billboard>
    </group>
  );
}
