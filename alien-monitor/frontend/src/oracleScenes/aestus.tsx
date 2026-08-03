import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Billboard, Instance, Instances, Text } from "@react-three/drei";
import * as THREE from "three";

/**
 * AESTUS — RSW time-lock puzzle oracle ("THE THAW VAULT").
 *
 * The real concept: SEAL data so NOBODY can open it before ~T sequential
 * squarings of wall-clock have elapsed — then ANYONE can. The unlock value is
 * b = a^(2^T) mod N, reached only by T squarings b_i = b_{i-1}^2 mod N. Each
 * squaring depends on the one before it, so the chain is inherently SEQUENTIAL:
 * no swarm of parallel attackers can skip ahead. When N's factorisation is
 * unknown (we burn p,q at seal) there is no φ shortcut for anyone, the oracle
 * included. Chronos proves the PAST elapsed; Aestus locks the FUTURE.
 *
 * The motif literalises that:
 *   • a central sealed PAYLOAD — a glowing core — encased in a PRISM of nested
 *     translucent GLASS SHELLS (concentric icy layers; each shell = a block of
 *     the T squarings still to be done);
 *   • ~8 ghostly "worms"/threads spiral inward to attack/parallelise the lock
 *     and ALL STALL at the SAME single frontier link — they cannot pass the
 *     shell still freezing (sequentiality made visible);
 *   • time elapses: shells THAW and peel away one-by-one from the outside in
 *     (the squarings completing), each melting from frozen icy-cyan toward warm
 *     amber; when the last shell melts the core IGNITES and "opens". Then it
 *     re-seals (shells re-form, color re-freezes) and the loop repeats.
 *
 * Accent icy-teal #5eead4 warming to amber #fbbf24 as it thaws.
 */

// ---- palette -------------------------------------------------------------
const ICE = new THREE.Color("#5eead4"); // frozen / sealed
const AMBER = new THREE.Color("#fbbf24"); // thawed / opening
const WORM = new THREE.Color("#a5f3fc"); // ghostly attacker threads
const WHITE = new THREE.Color("#ffffff");

// ---- geometry ------------------------------------------------------------
const SHELLS = 9; // T nested glass layers (one peels per "block" of squarings)
const SHELL_R0 = 0.95; // innermost shell radius (just outside the core)
const SHELL_DR = 0.46; // radial spacing between shells
const WORMS = 8; // parallel attacker threads (all stall at one link)
const WORM_BEADS = 26; // beads per worm tail
const CORE_R = 0.62;

function shellRadius(i: number): number {
  return SHELL_R0 + i * SHELL_DR;
}
const OUTER_R = shellRadius(SHELLS - 1);

// frozen->thawed ramp: icy-teal warming to amber as `m` (melt) goes 0->1
function thawColor(m: number, out: THREE.Color): THREE.Color {
  return out.copy(ICE).lerp(AMBER, m);
}

export default function Scene() {
  const group = useRef<THREE.Group>(null);
  const coreRef = useRef<THREE.Mesh>(null);
  const coreGlowRef = useRef<THREE.Mesh>(null);
  const shellRefs = useRef<Array<THREE.Mesh | null>>([]);
  const wormRefs = useRef<Array<THREE.InstancedMesh | null>>([]);
  const stallRef = useRef<THREE.InstancedMesh>(null);

  // Each worm spirals in toward the core along its own axis; precompute a
  // direction + spin offset per worm. Beads are placed each frame along the
  // inward spiral but CLAMPED at the current freezing frontier (the stall).
  const worms = useMemo(() => {
    const arr: { axis: THREE.Vector3; phase: number; tilt: number }[] = [];
    for (let w = 0; w < WORMS; w++) {
      // even-ish directions on a sphere (golden-angle) so they surround the vault
      const y = 1 - (w + 0.5) * (2 / WORMS);
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const phi = w * 2.39996; // golden angle
      arr.push({
        axis: new THREE.Vector3(Math.cos(phi) * r, y, Math.sin(phi) * r).normalize(),
        phase: w * 0.7,
        tilt: w * 1.3,
      });
    }
    return arr;
  }, []);

  // scratch (no per-frame allocation)
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const tmpColor = useMemo(() => new THREE.Color(), []);
  const vIn = useMemo(() => new THREE.Vector3(), []);
  const vOut = useMemo(() => new THREE.Vector3(), []);
  const perp = useMemo(() => new THREE.Vector3(), []);
  const up = useMemo(() => new THREE.Vector3(0, 1, 0), []);

  const LOOP = 18; // seconds: thaw all shells + ignite + a re-seal hold

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;

    // slow cinematic drift of the whole vault
    if (group.current) {
      group.current.rotation.y = t * 0.1;
      group.current.rotation.x = 0.32 + Math.sin(t * 0.16) * 0.07;
      group.current.position.y = Math.sin(t * 0.22) * 0.3;
    }

    // ---- loop phase: thaw for ~80%, ignite/hold, then re-seal --------------
    const phase = (t % LOOP) / LOOP;
    const thaw = Math.min(1, phase / 0.8); // 0..1 across the thaw, then clamps
    const eased = thaw * thaw * (3 - 2 * thaw); // smoothstep
    // melted shells, fractional: the outermost melts first (frontier moves in).
    const melted = eased * SHELLS; // 0..SHELLS shells gone
    const frontier = SHELLS - melted; // current freezing-edge shell index
    const opening = phase > 0.86; // last shell gone → core ignites

    // ---- the nested glass shells ------------------------------------------
    // Shell i (0=inner) is melted once `melted` passes (SHELLS-1 - i). It fades
    // out + warms as it melts; unmelted shells stay frozen icy-teal.
    for (let i = 0; i < SHELLS; i++) {
      const mesh = shellRefs.current[i];
      if (!mesh) continue;
      // how far this shell is into melting: 0 frozen .. 1 fully gone
      const meltOf = THREE.MathUtils.clamp(melted - (SHELLS - 1 - i), 0, 1);
      const mat = mesh.material as THREE.MeshStandardMaterial;
      // color warms toward amber as the global thaw advances; the actively
      // melting shell flares warmest at its frontier.
      thawColor(eased * 0.6 + meltOf * 0.4, tmpColor);
      mat.emissive.copy(tmpColor);
      mat.emissiveIntensity = 0.9 + (1 - meltOf) * 0.6 + Math.sin(t * 2 + i) * 0.06;
      // opacity: solid-ish frozen glass → transparent as it melts away
      const frozen = 0.16 + 0.02 * Math.sin(t * 1.5 + i * 0.8);
      mat.opacity = frozen * (1 - meltOf);
      // a gentle "breathing" + slight shrink as it melts (peeling inward)
      const s = 1 + Math.sin(t * 1.2 + i * 0.5) * 0.012 - meltOf * 0.06;
      mesh.scale.setScalar(s);
      mesh.visible = mat.opacity > 0.004;
    }

    // ---- the sealed payload core ------------------------------------------
    if (coreRef.current) {
      const m = coreRef.current.material as THREE.MeshStandardMaterial;
      // dim & icy while sealed; blazes warm-white the instant the last shell melts
      const ignite = opening ? (phase - 0.86) / 0.14 : 0;
      thawColor(eased, tmpColor);
      if (opening) tmpColor.lerp(WHITE, Math.min(1, ignite * 1.2));
      m.emissive.copy(tmpColor);
      m.emissiveIntensity = 1.2 + eased * 1.6 + (opening ? ignite * 4.5 : 0);
      const pulse = 1 + Math.sin(t * 3) * 0.04 + (opening ? ignite * 0.4 : 0);
      coreRef.current.scale.setScalar(pulse);
    }
    if (coreGlowRef.current) {
      const ignite = opening ? (phase - 0.86) / 0.14 : 0;
      const gm = coreGlowRef.current.material as THREE.MeshBasicMaterial;
      thawColor(eased, tmpColor);
      if (opening) tmpColor.lerp(WHITE, ignite);
      gm.color.copy(tmpColor);
      gm.opacity = 0.12 + eased * 0.12 + (opening ? ignite * 0.5 : 0);
      const gs = 1.5 + Math.sin(t * 2.4) * 0.1 + (opening ? ignite * 1.6 : 0);
      coreGlowRef.current.scale.setScalar(gs);
    }

    // ---- the attacker worms: spiral inward, ALL stall at the same link -----
    // The frontier shell is the freezing edge none of them can pass. We clamp
    // every worm's head to just outside `frontier` — they pile up at one link,
    // visibly unable to parallelise past the sequential frontier.
    const stallR = shellRadius(THREE.MathUtils.clamp(frontier, 0, SHELLS - 1)) + 0.08;
    for (let w = 0; w < WORMS; w++) {
      const mesh = wormRefs.current[w];
      if (!mesh) continue;
      const worm = worms[w];
      // build an orthonormal frame around the worm's inward axis
      vIn.copy(worm.axis);
      perp.copy(vIn).cross(up);
      if (perp.lengthSq() < 1e-4) perp.set(1, 0, 0);
      perp.normalize();
      // worm head sits at the stall radius, jittering against the frozen wall
      const headR = stallR + 0.05 + Math.abs(Math.sin(t * 4 + worm.phase)) * 0.06;
      for (let k = 0; k < WORM_BEADS; k++) {
        const u = k / (WORM_BEADS - 1); // 0 head .. 1 tail
        const rr = headR + u * (OUTER_R + 1.5 - headR); // tail trails outward
        const ang = worm.tilt + t * 0.9 + u * 5.5; // spiral wind
        // point on the inward spiral: along axis*rr, swirled by perp/up
        vOut
          .copy(vIn)
          .multiplyScalar(rr)
          .addScaledVector(perp, Math.cos(ang) * 0.28 * (rr / OUTER_R))
          .addScaledVector(up, Math.sin(ang) * 0.28 * (rr / OUTER_R));
        const s = (u < 0.04 ? 0.12 : 0.06) * (1 - u * 0.7); // fat head, thin tail
        dummy.position.copy(vOut);
        dummy.scale.setScalar(Math.max(0.012, s));
        dummy.updateMatrix();
        mesh.setMatrixAt(k, dummy.matrix);
        // ghostly cyan, brightest at the head where it presses the frozen wall
        tmpColor.copy(WORM).lerp(WHITE, k === 0 ? 0.6 : 0).multiplyScalar(1 - u * 0.6);
        mesh.setColorAt(k, tmpColor);
      }
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }

    // ---- the stall ring: bright sparks where every worm head jams ----------
    // One spark per worm at the shared frozen frontier — the single link none
    // of them can skip. Flares as the frontier shell is about to give.
    if (stallRef.current) {
      const give = 1 - (frontier - Math.floor(frontier)); // 0..1 as shell melts
      for (let w = 0; w < WORMS; w++) {
        const worm = worms[w];
        vOut.copy(worm.axis).multiplyScalar(stallR + 0.05);
        const flare = 0.09 + give * 0.12 + Math.abs(Math.sin(t * 6 + worm.phase)) * 0.04;
        dummy.position.copy(vOut);
        dummy.scale.setScalar(flare);
        dummy.updateMatrix();
        stallRef.current.setMatrixAt(w, dummy.matrix);
        thawColor(give, tmpColor);
        tmpColor.lerp(WHITE, 0.4);
        stallRef.current.setColorAt(w, tmpColor);
      }
      stallRef.current.instanceMatrix.needsUpdate = true;
      if (stallRef.current.instanceColor) stallRef.current.instanceColor.needsUpdate = true;
    }
  });

  return (
    <group ref={group} rotation={[0.32, 0, 0]}>
      {/* THE SEALED PAYLOAD — a glowing core, icy while sealed, igniting on open. */}
      <mesh ref={coreRef}>
        <icosahedronGeometry args={[CORE_R, 2]} />
        <meshStandardMaterial
          color="#0a1f1c"
          emissive={ICE}
          emissiveIntensity={1.2}
          roughness={0.25}
          metalness={0.2}
          toneMapped={false}
        />
      </mesh>
      {/* core glow halo (basic, always blooms) */}
      <mesh ref={coreGlowRef}>
        <sphereGeometry args={[CORE_R * 1.5, 24, 24]} />
        <meshBasicMaterial
          color={ICE}
          transparent
          opacity={0.14}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          toneMapped={false}
        />
      </mesh>

      {/* THE PRISM OF GLASS SHELLS — T nested translucent icy layers. Each peels
          away one-by-one from the outside in as the sequential squarings finish. */}
      {Array.from({ length: SHELLS }).map((_, i) => (
        <mesh
          key={i}
          ref={(m) => (shellRefs.current[i] = m)}
        >
          <icosahedronGeometry args={[shellRadius(i), 1]} />
          <meshStandardMaterial
            color="#06201e"
            emissive={ICE}
            emissiveIntensity={1.0}
            transparent
            opacity={0.16}
            roughness={0.05}
            metalness={0.0}
            flatShading
            side={THREE.DoubleSide}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      ))}

      {/* THE ATTACKER WORMS — ~8 ghostly threads spiralling in to parallelise the
          lock; every head jams at the SAME freezing frontier (sequentiality). */}
      {Array.from({ length: WORMS }).map((_, w) => (
        <Instances
          key={w}
          ref={(m) => (wormRefs.current[w] = m as any)}
          limit={WORM_BEADS}
          range={WORM_BEADS}
        >
          <sphereGeometry args={[1, 8, 8]} />
          <meshStandardMaterial
            emissive={WORM}
            emissiveIntensity={2.0}
            color="#000000"
            roughness={0.4}
            toneMapped={false}
          />
          {Array.from({ length: WORM_BEADS }).map((_, k) => (
            <Instance key={k} />
          ))}
        </Instances>
      ))}

      {/* THE STALL — one bright spark per worm at the shared frozen link. */}
      <Instances ref={stallRef as any} limit={WORMS} range={WORMS}>
        <sphereGeometry args={[1, 12, 12]} />
        <meshStandardMaterial
          emissive={ICE}
          emissiveIntensity={3.0}
          color="#000000"
          toneMapped={false}
        />
        {Array.from({ length: WORMS }).map((_, w) => (
          <Instance key={w} />
        ))}
      </Instances>

      {/* Concept label — drifts with the vault, faces the camera. */}
      <Billboard position={[0, -OUTER_R - 1.2, 0]}>
        <Text
          fontSize={0.34}
          color="#5eead4"
          anchorX="center"
          anchorY="middle"
          outlineWidth={0}
          letterSpacing={0.12}
        >
          {"b = a^(2^T) mod N  ·  seal now, opens later"}
        </Text>
      </Billboard>
    </group>
  );
}
