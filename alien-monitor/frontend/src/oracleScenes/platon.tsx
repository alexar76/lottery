import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

/**
 * PLATON — 3D scene on the Oracle Family portal (`?o=platon`).
 *
 * Platon is a full AIMarket oracle (see oracles/platon/). This scene is the portal
 * showcase; the separate UMBRAL cave product is at /platon/umbral — docs/platon-preview.en.md
 *
 * 32 coupled Stuart-Landau / Kuramoto oscillators integrated live in JS:
 * math): dr = r(1 - r^2), dtheta = omega + kappa·sin(meanPhase - theta). The 32
 * oscillators sit on a Fibonacci SPHERE (a true 3D constellation), each a glowing
 * orb that swells with amplitude r and is coloured by phase theta; a 3D coupling
 * web threads in-phase pairs through the volume; a tilted ring scales with the
 * Kuramoto order parameter; a wireframe icosahedron orbits as the 2D Stiefel
 * "shadow" projection. kappa breathes so the field drifts through bifurcations.
 */

const N = 32;
const R = 3.3; // sphere radius
const MAX_LINKS = 160;
const GOLDEN = Math.PI * (3 - Math.sqrt(5));

const CYAN = new THREE.Color("#6ee7ff");
const PURPLE = new THREE.Color("#c084fc");
const PINK = new THREE.Color("#f472b6");

function phaseColor(theta: number, out: THREE.Color): THREE.Color {
  const u = (Math.sin(theta) + 1) * 0.5;
  if (u < 0.5) out.copy(CYAN).lerp(PURPLE, u * 2);
  else out.copy(PURPLE).lerp(PINK, (u - 0.5) * 2);
  return out;
}

export default function Scene() {
  const group = useRef<THREE.Group>(null);
  const coresRef = useRef<THREE.InstancedMesh>(null);
  const halosRef = useRef<THREE.InstancedMesh>(null);
  const ringRef = useRef<THREE.Mesh>(null);
  const projRef = useRef<THREE.Mesh>(null);

  // fibonacci-sphere unit directions for the 32 oscillators
  const dirs = useMemo(() => {
    const out: THREE.Vector3[] = [];
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2;
      const rad = Math.sqrt(Math.max(0, 1 - y * y));
      const th = i * GOLDEN;
      out.push(new THREE.Vector3(Math.cos(th) * rad, y, Math.sin(th) * rad));
    }
    return out;
  }, []);

  const sim = useMemo(() => {
    const r = new Float64Array(N);
    const th = new Float64Array(N);
    const omega = new Float64Array(N);
    for (let i = 0; i < N; i++) {
      r[i] = 0.3 + Math.random() * 0.6;
      th[i] = Math.random() * Math.PI * 2;
      omega[i] = 0.8 + (i / (N - 1)) * 1.6;
    }
    return { r, th, omega };
  }, []);

  const pos = useMemo(() => dirs.map(() => new THREE.Vector3()), [dirs]);

  const linkGeom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(MAX_LINKS * 2 * 3), 3));
    return g;
  }, []);
  const linkMat = useMemo(
    () => new THREE.LineBasicMaterial({ color: CYAN.clone(), transparent: true, opacity: 0.25, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }),
    []
  );

  const dummy = useMemo(() => new THREE.Object3D(), []);
  const col = useMemo(() => new THREE.Color(), []);

  useFrame(({ clock }, delta) => {
    const dt = Math.min(0.033, delta);
    const t = clock.elapsedTime;
    const { r, th, omega } = sim;
    const kappa = 0.6 + 0.35 * Math.sin(t * 0.25);

    let sx = 0, sy = 0;
    for (let i = 0; i < N; i++) { sx += Math.cos(th[i]); sy += Math.sin(th[i]); }
    const meanPhase = Math.atan2(sy, sx);
    const order = Math.hypot(sx, sy) / N;

    for (let i = 0; i < N; i++) {
      r[i] += dt * r[i] * (1 - r[i] * r[i]);
      if (r[i] < 0.02) r[i] = 0.02;
      th[i] += dt * (omega[i] + kappa * Math.sin(meanPhase - th[i]));
      // orb sits on the sphere, pushed out slightly by amplitude
      pos[i].copy(dirs[i]).multiplyScalar(R * (1 + r[i] * 0.14));
    }

    const cores = coresRef.current, halos = halosRef.current;
    if (cores) {
      for (let i = 0; i < N; i++) {
        const s = 0.12 + r[i] * 0.32;
        dummy.position.copy(pos[i]); dummy.scale.setScalar(s); dummy.updateMatrix();
        cores.setMatrixAt(i, dummy.matrix);
        phaseColor(th[i], col); cores.setColorAt(i, col);
        if (halos) {
          dummy.scale.setScalar(s * 2.6); dummy.updateMatrix();
          halos.setMatrixAt(i, dummy.matrix); halos.setColorAt(i, col);
        }
      }
      cores.instanceMatrix.needsUpdate = true;
      if (cores.instanceColor) cores.instanceColor.needsUpdate = true;
      if (halos) {
        halos.instanceMatrix.needsUpdate = true;
        if (halos.instanceColor) halos.instanceColor.needsUpdate = true;
      }
    }

    // 3D coupling web through the volume
    const arr = linkGeom.attributes.position.array as Float32Array;
    let s = 0;
    for (let i = 0; i < N && s < MAX_LINKS; i++) {
      for (let j = i + 1; j < N && s < MAX_LINKS; j++) {
        const dp = Math.abs(th[i] - th[j]) % (Math.PI * 2);
        const diff = Math.min(dp, Math.PI * 2 - dp);
        if (diff < 0.45 && r[i] > 0.35 && r[j] > 0.35) {
          arr[s * 6] = pos[i].x; arr[s * 6 + 1] = pos[i].y; arr[s * 6 + 2] = pos[i].z;
          arr[s * 6 + 3] = pos[j].x; arr[s * 6 + 4] = pos[j].y; arr[s * 6 + 5] = pos[j].z;
          s++;
        }
      }
    }
    for (let k = s * 6; k < arr.length; k++) arr[k] = 0;
    linkGeom.attributes.position.needsUpdate = true;
    linkGeom.setDrawRange(0, s * 2);

    if (ringRef.current) {
      ringRef.current.rotation.z = t * 0.3;
      ringRef.current.rotation.x = Math.PI / 2 + Math.sin(t * 0.4) * 0.5;
      ringRef.current.scale.setScalar(1 + order * 0.5);
      (ringRef.current.material as THREE.MeshBasicMaterial).opacity = 0.25 + order * 0.5;
    }

    if (projRef.current) {
      const a1 = t * 0.3;
      const a2 = t * 0.21 + 1.1;
      let px = 0;
      let py = 0;
      for (let i = 0; i < N; i++) {
        px += r[i] * Math.cos(th[i] + a1);
        py += r[i] * Math.sin(th[i] + a2);
      }
      const sc = Math.max(Math.hypot(px, py), 1e-6);
      const orbit = R + 2.4;
      const fly = 0.55 + Math.sin(t * 0.85) * 0.35;
      projRef.current.position.set(
        (px / sc) * orbit + Math.sin(t * 0.7 + a1) * fly,
        Math.sin(t * 0.55) * 1.2 + order * 0.9 + 0.4,
        (py / sc) * orbit + Math.cos(t * 0.5) * fly
      );
      projRef.current.rotation.x = t * 0.65;
      projRef.current.rotation.y = t * 0.48;
      projRef.current.rotation.z = t * 0.32;
      (projRef.current.material as THREE.MeshBasicMaterial).opacity = 0.65 + order * 0.35;
    }

    if (group.current) { group.current.rotation.y = t * 0.12; group.current.rotation.x = Math.sin(t * 0.15) * 0.12; }
  });

  return (
    <group ref={group}>
      <instancedMesh ref={coresRef} args={[undefined as any, undefined as any, N]} frustumCulled={false}>
        <sphereGeometry args={[1, 18, 18]} />
        <meshStandardMaterial vertexColors emissive="#ffffff" emissiveIntensity={2.4} roughness={0.18} metalness={0.5} toneMapped={false} />
      </instancedMesh>
      <instancedMesh ref={halosRef} args={[undefined as any, undefined as any, N]} frustumCulled={false}>
        <sphereGeometry args={[1, 12, 12]} />
        <meshBasicMaterial vertexColors transparent opacity={0.16} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </instancedMesh>

      <lineSegments geometry={linkGeom} material={linkMat} frustumCulled={false} />

      {/* faint inner core sphere for depth */}
      <mesh>
        <sphereGeometry args={[R * 0.62, 32, 32]} />
        <meshBasicMaterial color="#1a1040" transparent opacity={0.25} side={THREE.BackSide} />
      </mesh>

      <mesh ref={ringRef} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[R + 0.6, 0.03, 10, 160]} />
        <meshBasicMaterial color="#c084fc" transparent opacity={0.4} toneMapped={false} />
      </mesh>

      <mesh ref={projRef}>
        <icosahedronGeometry args={[0.72, 1]} />
        <meshBasicMaterial color="#6ee7ff" wireframe transparent opacity={0.85} toneMapped={false} />
      </mesh>
    </group>
  );
}
