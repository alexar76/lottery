import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Instances, Instance, Trail, Billboard, Text } from "@react-three/drei";
import * as THREE from "three";

/* ===========================================================================
 *  MURMURATION — Robust Consensus Aggregation (signature 3D scene)
 *
 *  A swarm of ~480 instanced boids each carries a scalar "estimate" of one
 *  hidden quantity. They flock by Reynolds rules (alignment + cohesion +
 *  separation), fold into drifting ribbons, then COLLAPSE into a single
 *  luminous CONSENSUS CORE — the robust centre the oracle actually returns
 *  (median / trimmed mean / Tukey biweight). A handful of ADVERSARIAL boids
 *  carry wild estimates and resist convergence (their pull to the core is
 *  weak), mirroring the breakdown-resistance of the real estimators: a few
 *  outliers cannot move the consensus. The core flares, then the flock
 *  disperses and reforms — a smooth, endlessly looping cinematic arc echoing
 *  DeGroot x <- W x tightening to the mean.
 *
 *  Rendered INSIDE the shared CosmicCanvas (camera/lights/nebula/stars/bloom
 *  already provided). This file adds ONLY the signature scene. Everything that
 *  scales with boid count is instanced; per-frame work touches preallocated
 *  buffers only, so it runs for minutes without allocating or leaking.
 * ========================================================================= */

const CYAN = new THREE.Color("#6ee7ff");
const PURPLE = new THREE.Color("#c084fc");
const PINK = new THREE.Color("#f472b6");
const WHITE = new THREE.Color("#ffffff");

const N = 480; // total instanced boids (capped for 60fps)
const N_ADV = 22; // adversarial boids that resist the consensus
const N_TRAIL = 6; // a few drei <Trail> leaders for additive glow streaks

// Phase arc (seconds) — gather -> flock/ribbon -> converge -> hold -> disperse
const T_GATHER = 4.0;
const T_FLOCK = 7.5;
const T_CONVERGE = 4.5;
const T_HOLD = 3.5;
const T_DISPERSE = 3.0;
const LOOP = T_GATHER + T_FLOCK + T_CONVERGE + T_HOLD + T_DISPERSE;

const clamp = (v: number, lo: number, hi: number) =>
  v < lo ? lo : v > hi ? hi : v;
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};

// Deterministic PRNG so the swarm looks the same every reload (and never NaNs).
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

type Boid = {
  pos: THREE.Vector3;
  vel: THREE.Vector3;
  home: THREE.Vector3; // gathering / dispersal anchor
  adversary: boolean;
  bias: THREE.Vector3; // adversary's stubborn off-centre target
  color: THREE.Color;
  phase: number; // per-boid jitter seed
  depth: number; // size / brightness variation
};

export default function Scene() {
  // ---- swarm state (allocated once, mutated in place) --------------------
  const boids = useMemo<Boid[]>(() => {
    const rnd = mulberry32(0xc0ffee);
    const out: Boid[] = [];
    for (let i = 0; i < N; i++) {
      const adversary = i < N_ADV;
      // gather anchors fill a wide shell so the "gathering estimates" reads
      const a = rnd() * Math.PI * 2;
      const r = 7 + rnd() * 6;
      const y = (rnd() - 0.5) * 9;
      const home = new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r);
      const color = adversary
        ? PINK.clone()
        : rnd() < 0.5
        ? CYAN.clone()
        : PURPLE.clone();
      // adversaries are stubbornly anchored far from the true centre
      const ba = rnd() * Math.PI * 2;
      const bias = new THREE.Vector3(
        Math.cos(ba) * (5 + rnd() * 4),
        (rnd() - 0.5) * 6,
        Math.sin(ba) * (5 + rnd() * 4)
      );
      out.push({
        pos: home.clone(),
        vel: new THREE.Vector3(
          (rnd() - 0.5) * 2,
          (rnd() - 0.5) * 2,
          (rnd() - 0.5) * 2
        ),
        home,
        adversary,
        bias,
        color,
        phase: rnd() * Math.PI * 2,
        depth: 0.45 + rnd() * 0.55,
      });
    }
    return out;
  }, []);

  // The robust consensus core position (where the honest flock collapses).
  const corePos = useMemo(() => new THREE.Vector3(0, 0, 0), []);

  // Refs to the instanced mesh + the bright core meshes.
  const flock = useRef<THREE.InstancedMesh>(null);
  const coreRef = useRef<THREE.Mesh>(null);
  const coreMat = useRef<THREE.MeshStandardMaterial>(null);
  const haloRef = useRef<THREE.Mesh>(null);
  const haloMat = useRef<THREE.MeshBasicMaterial>(null);
  const ringRef = useRef<THREE.Mesh>(null);
  const labelRef = useRef<THREE.Group>(null);

  // Scratch objects (no per-frame allocation).
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const tmpColor = useMemo(() => new THREE.Color(), []);
  const acc = useMemo(() => new THREE.Vector3(), []);
  const steer = useMemo(() => new THREE.Vector3(), []);
  const align = useMemo(() => new THREE.Vector3(), []);
  const cohere = useMemo(() => new THREE.Vector3(), []);
  const separate = useMemo(() => new THREE.Vector3(), []);
  const diff = useMemo(() => new THREE.Vector3(), []);
  const target = useMemo(() => new THREE.Vector3(), []);
  const up = useMemo(() => new THREE.Vector3(0, 1, 0), []);
  const quat = useMemo(() => new THREE.Quaternion(), []);

  // The trail leaders ride along with chosen honest boids — we just track
  // their indices and drive their meshes from the simulated positions.
  const trailIdx = useMemo(() => {
    const idx: number[] = [];
    let k = N_ADV + 3;
    while (idx.length < N_TRAIL && k < N) {
      idx.push(k);
      k += Math.floor(N / N_TRAIL);
    }
    return idx;
  }, []);
  const trailRefs = useRef<(THREE.Mesh | null)[]>([]);

  useFrame((state, rawDelta) => {
    const dt = Math.min(rawDelta, 1 / 30); // clamp big frames (tab refocus)
    const t = state.clock.elapsedTime;
    const lt = t % LOOP; // local loop time

    // -------- phase weights (smoothly blended, never hard-cut) ------------
    const tGather = T_GATHER;
    const tFlock = tGather + T_FLOCK;
    const tConverge = tFlock + T_CONVERGE;
    const tHold = tConverge + T_HOLD;

    // converge: 0 during gather/flock -> 1 by end of converge -> stays 1 in hold
    const converge =
      smoothstep(tFlock, tConverge, lt) * (1 - smoothstep(tHold, LOOP, lt));
    // ribbon: peaks during the flock phase (folding into ribbons)
    const ribbon = smoothstep(tGather, tFlock, lt) * (1 - converge);
    // disperse: ramps in the final phase
    const disperse = smoothstep(tHold, LOOP - 0.4, lt);
    // hold: bright plateau around the collapse
    const hold = smoothstep(tConverge - 1.2, tConverge + 0.4, lt) *
      (1 - smoothstep(tHold, tHold + 0.8, lt));

    // a slow breathing drift of the consensus centre so it feels alive
    corePos.set(
      Math.sin(t * 0.18) * 0.6,
      Math.sin(t * 0.13 + 1.0) * 0.4,
      Math.cos(t * 0.16) * 0.6
    );

    // global flock tuning shifts across the arc
    const cohesionK = 0.9 + ribbon * 1.4 + converge * 2.2;
    const swirl = 0.6 + ribbon * 1.1 + converge * 1.8;
    const coreK = 0.15 + converge * 3.2 - disperse * 1.6;
    const jitter = 0.9 * (1 - converge * 0.7) + disperse * 1.4;

    const PERCEIVE = 3.2;
    const SEP = 1.25;
    const P2 = PERCEIVE * PERCEIVE;
    const S2 = SEP * SEP;

    for (let i = 0; i < N; i++) {
      const b = boids[i];
      align.set(0, 0, 0);
      cohere.set(0, 0, 0);
      separate.set(0, 0, 0);
      let nA = 0;

      // Neighbour scan. Capped stride keeps this O(N * N/STRIDE) — smooth at
      // N=480. Sampling a strided subset is plenty for emergent flocking.
      for (let j = (i % 3); j < N; j += 3) {
        if (j === i) continue;
        const o = boids[j];
        const dx = o.pos.x - b.pos.x;
        const dy = o.pos.y - b.pos.y;
        const dz = o.pos.z - b.pos.z;
        const d2 = dx * dx + dy * dy + dz * dz;
        if (d2 > P2 || d2 === 0) continue;
        align.add(o.vel);
        cohere.x += o.pos.x;
        cohere.y += o.pos.y;
        cohere.z += o.pos.z;
        nA++;
        if (d2 < S2) {
          const inv = 1 / Math.sqrt(d2);
          separate.x -= dx * inv;
          separate.y -= dy * inv;
          separate.z -= dz * inv;
        }
      }

      acc.set(0, 0, 0);
      const fg = b.adversary ? 0.3 : 1; // adversaries barely flock

      if (nA > 0) {
        align.multiplyScalar(1 / nA).sub(b.vel);
        acc.addScaledVector(align, 0.5 * fg);
        cohere.multiplyScalar(1 / nA).sub(b.pos);
        acc.addScaledVector(cohere, 0.015 * cohesionK * fg);
      }
      acc.addScaledVector(separate, 1.4);

      // ribbon-folding: a sheared sinusoidal field pushes the flock into
      // long drifting ribbons during the flock phase.
      if (ribbon > 0.01) {
        const rb = ribbon;
        steer.set(
          Math.sin(b.pos.z * 0.35 + t * 0.7) * 2.2,
          Math.sin(b.pos.x * 0.3 - t * 0.5) * 1.6 - b.pos.y * 0.12,
          Math.cos(b.pos.x * 0.35 + t * 0.6) * 2.2
        );
        acc.addScaledVector(steer, rb * 1.1 * fg);
      }

      // pull toward the consensus core (honest boids strongly; adversaries
      // resist — they lean toward their stubborn bias instead).
      if (b.adversary) {
        target.copy(corePos).addScaledVector(b.bias, 0.85);
        acc.addScaledVector(diff.copy(target).sub(b.pos), coreK * 0.18);
      } else {
        acc.addScaledVector(diff.copy(corePos).sub(b.pos), coreK * 0.55);
      }

      // gather / disperse: drift toward home anchors at the loop ends
      if (disperse > 0.01) {
        acc.addScaledVector(
          diff.copy(b.home).sub(b.pos),
          disperse * 0.8
        );
      }
      const gather = 1 - smoothstep(0, T_GATHER, lt);
      if (gather > 0.01) {
        acc.addScaledVector(diff.copy(b.home).sub(b.pos), gather * 0.6);
      }

      // orbital swirl around the core (the murmuration whirl)
      diff.copy(b.pos).sub(corePos);
      steer.crossVectors(up, diff).multiplyScalar(swirl * 0.06);
      acc.add(steer);

      // organic jitter
      b.phase += dt * 2.2;
      acc.x += Math.sin(b.phase) * jitter * 0.5;
      acc.y += Math.cos(b.phase * 1.3) * jitter * 0.4;
      acc.z += Math.sin(b.phase * 0.7) * jitter * 0.5;

      // integrate
      b.vel.addScaledVector(acc, dt);
      // damping + speed clamp (faster when dispersing, slower when held)
      const maxV = 6 * b.depth * (0.5 + (1 - converge) * 0.9 + disperse * 0.6);
      const sp = b.vel.length();
      if (sp > maxV) b.vel.multiplyScalar(maxV / sp);
      b.vel.multiplyScalar(0.92);
      b.pos.addScaledVector(b.vel, dt * 6);

      // write the instance transform (oriented dart)
      dummy.position.copy(b.pos);
      if (sp > 0.001) {
        diff.copy(b.vel).normalize();
        quat.setFromUnitVectors(up, diff);
        dummy.quaternion.copy(quat);
      }
      // shrink a touch as the flock collapses into the bright core
      const s = b.depth * (1 - converge * 0.35);
      dummy.scale.set(s, s * 2.2, s);
      dummy.updateMatrix();
      flock.current?.setMatrixAt(i, dummy.matrix);

      // colour: lerp honest boids toward white near full convergence so the
      // collapse reads as the flock "agreeing"; adversaries stay pink.
      if (b.adversary) {
        tmpColor.copy(PINK);
      } else {
        tmpColor.copy(b.color).lerp(WHITE, converge * 0.55 + hold * 0.2);
      }
      flock.current?.setColorAt(i, tmpColor);
    }

    if (flock.current) {
      flock.current.instanceMatrix.needsUpdate = true;
      if (flock.current.instanceColor) flock.current.instanceColor.needsUpdate = true;
    }

    // drive the trail leader meshes from their boid positions
    for (let k = 0; k < trailIdx.length; k++) {
      const m = trailRefs.current[k];
      if (m) m.position.copy(boids[trailIdx[k]].pos);
    }

    // -------- the consensus core ------------------------------------------
    const glow = converge; // 0..1
    const flare = hold; // 0..1 plateau
    if (coreRef.current && coreMat.current) {
      const pulse = 1 + Math.sin(t * 3) * 0.06 * glow;
      const cs = (0.15 + glow * 1.5 + flare * 0.6) * pulse;
      coreRef.current.position.copy(corePos);
      coreRef.current.scale.setScalar(cs);
      coreMat.current.emissiveIntensity = 0.5 + glow * 2.4 + flare * 1.8;
      coreMat.current.opacity = clamp(glow * 1.4, 0, 1);
    }
    if (haloRef.current && haloMat.current) {
      const hs = (0.4 + glow * 3.6 + flare * 2.2) * (1 + Math.sin(t * 1.7) * 0.05);
      haloRef.current.position.copy(corePos);
      haloRef.current.scale.setScalar(hs);
      haloMat.current.opacity = clamp(glow * 0.32 + flare * 0.18, 0, 0.5);
    }
    if (ringRef.current) {
      ringRef.current.position.copy(corePos);
      ringRef.current.rotation.x = Math.PI / 2;
      ringRef.current.rotation.z = t * 0.6;
      const rs = 1.4 + glow * 2.2 + Math.sin(t * 2) * 0.08;
      ringRef.current.scale.setScalar(rs);
      const rm = ringRef.current.material as THREE.MeshBasicMaterial;
      rm.opacity = clamp(glow * 0.5 + flare * 0.3, 0, 0.8);
    }
    if (labelRef.current) {
      labelRef.current.position.set(corePos.x, corePos.y - 3.1, corePos.z);
      const lm = labelRef.current as unknown as { visible: boolean };
      lm.visible = glow > 0.35;
    }
  });

  return (
    <group>
      {/* THE FLOCK — instanced glowing darts (alignment+cohesion+separation) */}
      <Instances ref={flock} limit={N} range={N}>
        {/* a slim cone = a starling dart; oriented along velocity in useFrame */}
        <coneGeometry args={[0.16, 0.6, 5]} />
        <meshStandardMaterial
          vertexColors
          emissive={WHITE}
          emissiveIntensity={1.8}
          toneMapped={false}
          metalness={0.2}
          roughness={0.4}
        />
        {/* Instances API requires <Instance> children to register the range. */}
        {boids.map((b, i) => (
          <Instance key={i} color={b.color} />
        ))}
      </Instances>

      {/* A FEW ADDITIVE-GLOW TRAILS on leader boids (drei <Trail>) */}
      {trailIdx.map((bi, k) => (
        <Trail
          key={bi}
          width={2.4}
          length={6}
          decay={1.4}
          local={false}
          stride={0}
          interval={1}
          color={k % 2 === 0 ? CYAN : PURPLE}
          attenuation={(w) => w * w}
        >
          <mesh
            ref={(m) => (trailRefs.current[k] = m)}
            position={boids[bi].home}
          >
            <sphereGeometry args={[0.12, 8, 8]} />
            <meshBasicMaterial
              color={k % 2 === 0 ? CYAN : PURPLE}
              toneMapped={false}
            />
          </mesh>
        </Trail>
      ))}

      {/* THE LUMINOUS CONSENSUS CORE — bright emissive sphere that flares */}
      <mesh ref={coreRef}>
        <icosahedronGeometry args={[1, 3]} />
        <meshStandardMaterial
          ref={coreMat}
          color={WHITE}
          emissive={CYAN}
          emissiveIntensity={2.2}
          toneMapped={false}
          transparent
          opacity={0}
        />
      </mesh>

      {/* soft additive halo bloom around the core */}
      <mesh ref={haloRef}>
        <sphereGeometry args={[1, 24, 24]} />
        <meshBasicMaterial
          ref={haloMat}
          color={PURPLE}
          transparent
          opacity={0}
          toneMapped={false}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          side={THREE.BackSide}
        />
      </mesh>

      {/* consensus ring — the DeGroot averaging circle tightening to the mean */}
      <mesh ref={ringRef}>
        <torusGeometry args={[1, 0.018, 8, 96]} />
        <meshBasicMaterial
          color={PINK}
          transparent
          opacity={0}
          toneMapped={false}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>

      {/* the value the swarm agrees on — appears as the core ignites */}
      <group ref={labelRef} visible={false}>
        <Billboard>
          <Text
            fontSize={0.62}
            color="#6ee7ff"
            anchorX="center"
            anchorY="middle"
            outlineWidth={0.01}
            outlineColor="#04030f"
          >
            consensus
          </Text>
        </Billboard>
      </group>
    </group>
  );
}
