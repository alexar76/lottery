import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import {
  OrbitControls,
  Sphere,
  Line,
  Html,
  Stars,
} from '@react-three/drei';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { EffectComposer, Bloom, Vignette, Noise } from '@react-three/postprocessing';
import * as THREE from 'three';
import type { EcoNode, EcoLink, EcosystemState } from '../App';
import { useIsMobile } from '../hooks/useIsMobile';

// ---------------------------------------------------------------------------
// Color mapping
// ---------------------------------------------------------------------------
const GROUP_COLORS: Record<string, string> = {
  core: '#00f0ff',
  contract: '#ff00ff',
  client: '#00ff88',
  infra: '#7b2fff',
  sdk: '#ffdd00',
  network: '#3366ff',
  chain: '#ff6633',
  product: '#ffaa44',
  economy: '#ffd700',
  cluster: '#ffcc66',
  agent: '#66ffcc',
  oracle: '#a64dff',
  argus: '#36e6ff',
  community: '#c9a227',
  media: '#ff4466',
  observability: '#00e5cc',
  cognition: '#9b59ff',
  physical: '#43e65a',
};

const GROUP_EMISSIVE: Record<string, string> = {
  core: '#004466',
  contract: '#440044',
  client: '#004422',
  infra: '#220066',
  sdk: '#443300',
  network: '#001144',
  chain: '#441100',
  product: '#553300',
  economy: '#665500',
  cluster: '#664422',
  agent: '#113322',
  oracle: '#3a0a66',
  argus: '#0a3344',
  community: '#3d3010',
  media: '#440a14',
  observability: '#003328',
  cognition: '#220044',
  physical: '#0d4417',
};

const getNodeColor = (g: string) => GROUP_COLORS[g] || '#00f0ff';
const getNodeEmissive = (g: string) => GROUP_EMISSIVE[g] || '#001122';

// ---------------------------------------------------------------------------
// Wormhole — spiral particle tunnel along a connection
// ---------------------------------------------------------------------------
function WormholeTunnel({
  src,
  tgt,
  color,
  intensity,
}: {
  src: THREE.Vector3;
  tgt: THREE.Vector3;
  color: string;
  intensity: number;
}) {
  const pointsRef = useRef<THREE.Points>(null!);
  const particleCount = 60;

  const { positions, randoms } = useMemo(() => {
    const pos = new Float32Array(particleCount * 3);
    const rnd = new Float32Array(particleCount);
    for (let i = 0; i < particleCount; i++) {
      rnd[i] = Math.random();
      pos[i * 3] = 0;
      pos[i * 3 + 1] = 0;
      pos[i * 3 + 2] = 0;
    }
    return { positions: pos, randoms: rnd };
  }, [particleCount]);

  useFrame(({ clock }) => {
    if (!pointsRef.current) return;
    const t = clock.getElapsedTime();
    const posArr = pointsRef.current.geometry.attributes.position.array as Float32Array;

    for (let i = 0; i < particleCount; i++) {
      const progress = ((t * 0.3 + randoms[i]) % 1);
      // Spiral offset
      const spiralRadius = 0.15 * Math.sin(progress * Math.PI);
      const angle = progress * Math.PI * 6 + i * 0.5;
      const ox = Math.cos(angle) * spiralRadius;
      const oy = Math.sin(angle) * spiralRadius;
      const oz = 0;

      // Interpolate between src and tgt
      posArr[i * 3] = src.x + (tgt.x - src.x) * progress + ox;
      posArr[i * 3 + 1] = src.y + (tgt.y - src.y) * progress + oy;
      posArr[i * 3 + 2] = src.z + (tgt.z - src.z) * progress + oz;
    }
    pointsRef.current.geometry.attributes.position.needsUpdate = true;
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          array={positions}
          count={particleCount}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.06}
        color={color}
        transparent
        opacity={0.8 * intensity}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

// ---------------------------------------------------------------------------
// Nebula cloud — particle cluster around a position
// ---------------------------------------------------------------------------
function NebulaCloud({
  center,
  color,
  radius = 2,
  count = 300,
}: {
  center: THREE.Vector3;
  color: string;
  radius?: number;
  count?: number;
}) {
  const pointsRef = useRef<THREE.Points>(null!);
  const { positions } = useMemo(() => {
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = radius * (0.3 + Math.random() * 0.7);
      pos[i * 3] = center.x + r * Math.sin(phi) * Math.cos(theta);
      pos[i * 3 + 1] = center.y + r * Math.sin(phi) * Math.sin(theta);
      pos[i * 3 + 2] = center.z + r * Math.cos(phi);
    }
    return { positions: pos };
  }, [center, radius, count]);

  useFrame(({ clock }) => {
    if (!pointsRef.current) return;
    const t = clock.getElapsedTime();
    pointsRef.current.rotation.y += 0.0001;
    pointsRef.current.rotation.x += 0.00005;
    const mat = pointsRef.current.material as THREE.PointsMaterial;
    mat.opacity = 0.06 + Math.sin(t * 0.5) * 0.02;
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" array={positions} count={count} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial
        size={0.08}
        color={color}
        transparent
        opacity={0.06}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

// ---------------------------------------------------------------------------
// Asteroid belt — ring of particles around origin
// ---------------------------------------------------------------------------
function AsteroidBelt({
  radius,
  color,
  count = 400,
  tilt = 0,
}: {
  radius: number;
  color: string;
  count?: number;
  tilt?: number;
}) {
  const pointsRef = useRef<THREE.Points>(null!);

  const { positions } = useMemo(() => {
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const angle = (i / count) * Math.PI * 2 + (Math.random() - 0.5) * 0.3;
      const r = radius + (Math.random() - 0.5) * 0.6;
      pos[i * 3] = Math.cos(angle) * r;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 0.15;
      pos[i * 3 + 2] = Math.sin(angle) * r;
    }
    return { positions: pos };
  }, [radius, count]);

  useFrame((_, delta) => {
    if (pointsRef.current) {
      pointsRef.current.rotation.y += delta * 0.05;
      if (tilt) pointsRef.current.rotation.x = tilt;
    }
  });

  return (
    <points ref={pointsRef} rotation={[tilt, 0, 0]}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" array={positions} count={count} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial
        size={0.04}
        color={color}
        transparent
        opacity={0.15}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

// ---------------------------------------------------------------------------
// Solar Corona — glowing atmosphere around central hub
// ---------------------------------------------------------------------------
function SolarCorona({ color, intensity }: { color: string; intensity: number }) {
  const groupRef = useRef<THREE.Group>(null!);
  const layers = [0.65, 0.75, 0.9, 1.1];

  useFrame(({ clock }) => {
    if (!groupRef.current) return;
    const t = clock.getElapsedTime();
    groupRef.current.children.forEach((mesh, i) => {
      const s = 1 + Math.sin(t * 2 + i) * 0.08 * intensity;
      mesh.scale.setScalar(s);
      ((mesh as THREE.Mesh).material as THREE.MeshBasicMaterial).opacity = (0.12 - i * 0.02) * intensity;
    });
  });

  return (
    <group ref={groupRef}>
      {layers.map((radius, i) => (
        <mesh key={i}>
          <sphereGeometry args={[radius, 48, 48]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={0.12 - i * 0.02}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      ))}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Cosmic dust — ambient floating particles everywhere
// ---------------------------------------------------------------------------
function CosmicDust({ color, count = 500 }: { color: string; count?: number }) {
  const pointsRef = useRef<THREE.Points>(null!);
  const spread = 25;

  const { positions } = useMemo(() => {
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * spread * 2;
      pos[i * 3 + 1] = (Math.random() - 0.5) * spread * 2;
      pos[i * 3 + 2] = (Math.random() - 0.5) * spread * 2;
    }
    return { positions: pos };
  }, [count, spread]);

  useFrame((_, delta) => {
    if (pointsRef.current) {
      pointsRef.current.rotation.y += delta * 0.02;
      pointsRef.current.rotation.x += delta * 0.01;
    }
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" array={positions} count={count} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial
        size={0.03}
        color={color}
        transparent
        opacity={0.15}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

// ---------------------------------------------------------------------------
// Gravity well — central mass that attracts nodes
// ---------------------------------------------------------------------------
function GravityWell({ color, intensity }: { color: string; intensity: number }) {
  const ringRefs = useRef<THREE.Mesh[]>([]);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    ringRefs.current.forEach((ring, i) => {
      if (!ring) return;
      const phase = i * 0.5;
      const s = 0.8 + (t * 0.3 + phase) % 4;
      ring.scale.set(s, s, s);
      ring.rotation.z += 0.002;
      ring.rotation.x += 0.001;
      (ring.material as THREE.MeshBasicMaterial).opacity =
        Math.max(0, (1 - ((t * 0.3 + phase) % 4) / 4) * 0.2 * intensity);
    });
  });

  return (
    <group>
      {[0, 1, 2, 3].map((i) => (
        <mesh
          key={i}
          ref={(el) => { ringRefs.current[i] = el!; }}
          rotation={[Math.PI / 2 + i * 0.3, i * 0.4, 0]}
        >
          <ringGeometry args={[0.5, 0.54, 80]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={0.2}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Main eco node — planet/sun style
// ---------------------------------------------------------------------------
function EcoNodeMesh({
  node,
  onClick,
  themeColor,
  pulseIntensity,
}: {
  node: EcoNode;
  onClick: (n: EcoNode) => void;
  themeColor: string;
  pulseIntensity: number;
}) {
  const groupRef = useRef<THREE.Group>(null!);
  const coronaRef = useRef<THREE.Mesh>(null!);
  const orbitRingRef = useRef<THREE.Mesh>(null!);
  const [hovered, setHovered] = useState(false);

  const nodeColor = node.group === 'oracle' && node.color ? node.color : getNodeColor(node.group);
  const isActive = node.status === 'active';
  const isOracle = node.group === 'oracle';
  const showCorona = isActive || isOracle;
  const dimmed = node.status === 'offline' || node.status === 'disabled';  // offline or crypto-disabled networks/contracts → greyed out
  const isHub = node.group === 'core' && node.id === 'hub';
  const nodeSize = isHub ? 0.7 : node.group === 'core' ? 0.45 : node.group === 'contract' ? 0.38 : 0.28;
  const baseY = node.position.y;
  const baseX = node.position.x;
  const baseZ = node.position.z;

  // Wobble parameters per node
  const wobble = useMemo(() => ({
    speed: 0.5 + Math.random() * 1.5,
    ampX: 0.1 + Math.random() * 0.2,
    ampY: 0.1 + Math.random() * 0.2,
    ampZ: 0.1 + Math.random() * 0.2,
    phase: Math.random() * Math.PI * 2,
  }), []);

  useFrame(({ clock }) => {
    if (!groupRef.current) return;
    const t = clock.getElapsedTime();
    const p = wobble.phase;

    groupRef.current.position.x = baseX + Math.sin(t * wobble.speed + p) * wobble.ampX;
    groupRef.current.position.y = baseY + Math.cos(t * wobble.speed * 0.7 + p) * wobble.ampY;
    groupRef.current.position.z = baseZ + Math.sin(t * wobble.speed * 0.6 + p + 1) * wobble.ampZ;

    if (showCorona && coronaRef.current) {
      const pulse = isActive
        ? 1 + Math.sin(t * 3 + p) * 0.15 * pulseIntensity
        : 1 + Math.sin(t * 1.2 + p) * 0.04;
      coronaRef.current.scale.setScalar(pulse);
      (coronaRef.current.material as THREE.MeshBasicMaterial).opacity =
        (isActive ? 0.08 : 0.045) + Math.sin(t * (isActive ? 2.5 : 1.4)) * (isActive ? 0.04 : 0.015) * pulseIntensity;
    }

    if (orbitRingRef.current) {
      orbitRingRef.current.rotation.z += 0.003;
      orbitRingRef.current.rotation.x += 0.001;
    }
  });

  return (
    <group ref={groupRef} position={[baseX, baseY, baseZ]}>
      {/* Corona / outer glow */}
      <mesh ref={coronaRef}>
        <sphereGeometry args={[nodeSize * (isHub ? 2.5 : 2), 32, 32]} />
        <meshBasicMaterial
          color={nodeColor}
          transparent
          opacity={isHub ? 0.15 : 0.08}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* Main body */}
      <mesh
        onClick={(e) => { e.stopPropagation(); onClick(node); }}
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => setHovered(false)}
      >
        <sphereGeometry args={[nodeSize, 48, 48]} />
        <meshStandardMaterial
          color={dimmed ? '#3b424d' : nodeColor}
          emissive={dimmed ? '#000000' : getNodeEmissive(node.group)}
          emissiveIntensity={hovered ? 1.4 : dimmed ? 0.05 : isHub ? 0.9 : 0.5}
          metalness={0.4}
          roughness={0.15}
          transparent
          opacity={dimmed ? 0.4 : 1}
        />
      </mesh>

      {/* Hover halo */}
      {hovered && (
        <mesh>
          <sphereGeometry args={[nodeSize * 1.8, 24, 24]} />
          <meshBasicMaterial
            color={nodeColor}
            transparent
            opacity={0.2}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      )}

      {/* Orbital ring for active nodes; faint ring for idle oracles so they stay visible */}
      {(isActive || isOracle) && !isHub && (
        <mesh ref={orbitRingRef} rotation={[Math.PI / 3, 0, 0]}>
          <torusGeometry args={[nodeSize * 1.6, 0.015, 8, 24]} />
          <meshBasicMaterial color={nodeColor} transparent opacity={isActive ? 0.5 : 0.18} depthWrite={false} />
        </mesh>
      )}

      {/* Label */}
      <Html
        position={[0, -nodeSize - 0.35, 0]}
        center
        distanceFactor={14}
        occlude={false}
        style={{ pointerEvents: 'none' }}
      >
        <div
          className="text-[9px] font-mono whitespace-nowrap transition-opacity duration-200"
          style={{
            color: dimmed ? '#6b7280' : nodeColor,
            textShadow: dimmed ? 'none' : `0 0 8px ${nodeColor}, 0 0 2px ${nodeColor}`,
            opacity: hovered ? 1 : dimmed ? 0.38 : 0.55,
            letterSpacing: '0.05em',
          }}
        >
          {node.label}
        </div>
      </Html>

      {/* Status dot */}
      <mesh position={[nodeSize + 0.08, nodeSize + 0.05, 0]}>
        <sphereGeometry args={[0.05, 8, 8]} />
        <meshBasicMaterial
          color={
            node.status === 'active' ? '#00ff88' :
            node.status === 'error' ? '#ff3355' :
            node.status === 'idle' ? '#ffdd00' : '#555'
          }
          transparent
          opacity={0.9}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </group>
  );
}

// ---------------------------------------------------------------------------
// Constellation lines — glowing, animated bezier connections
// ---------------------------------------------------------------------------
function ConstellationLines({
  links,
  nodePositions,
  themeColor,
}: {
  links: EcoLink[];
  nodePositions: Map<string, THREE.Vector3>;
  themeColor: string;
}) {
  const lineData = useMemo(() => {
    const result: { src: THREE.Vector3; tgt: THREE.Vector3 }[] = [];
    for (const link of links) {
      const srcId = typeof link.source === 'string' ? link.source : '';
      const tgtId = typeof link.target === 'string' ? link.target : '';
      const src = nodePositions.get(srcId);
      const tgt = nodePositions.get(tgtId);
      if (src && tgt) result.push({ src, tgt });
    }
    return result;
  }, [links, nodePositions]);

  const points = useMemo(() => {
    return lineData.map((ld) => {
      const mid = new THREE.Vector3().addVectors(ld.src, ld.tgt).multiplyScalar(0.5);
      mid.y += 0.3;
      const curve = new THREE.QuadraticBezierCurve3(ld.src, mid, ld.tgt);
      return curve.getPoints(32);
    });
  }, [lineData]);

  return (
    <group>
      {points.map((pts, i) => (
        <Line
          key={i}
          points={pts}
          color={themeColor}
          lineWidth={0.3}
          transparent
          opacity={0.08}
          depthWrite={false}
        />
      ))}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Star cluster — many small bodies (factory catalog / templates)
// ---------------------------------------------------------------------------
function StarCluster({
  node,
  onClick,
}: {
  node: EcoNode;
  onClick: (n: EcoNode) => void;
}) {
  const groupRef = useRef<THREE.Group>(null!);
  const count = Math.min(Math.max(Number(node.metrics?.count) || 12, 8), 48);
  const clusterColor = getNodeColor('cluster');
  const base = useMemo(
    () => new THREE.Vector3(node.position.x, node.position.y, node.position.z),
    [node.position.x, node.position.y, node.position.z],
  );

  const stars = useMemo(() => {
    const out: { offset: THREE.Vector3; size: number; phase: number }[] = [];
    for (let i = 0; i < count; i++) {
      const u = (i + 0.5) / count;
      const phi = Math.acos(1 - 2 * u);
      const theta = i * GOLDEN_ANGLE_LOCAL;
      const r = 0.35 + (i % 5) * 0.08;
      out.push({
        offset: new THREE.Vector3(
          r * Math.sin(phi) * Math.cos(theta),
          r * Math.sin(phi) * Math.sin(theta) * 0.6,
          r * Math.cos(phi),
        ),
        size: 0.04 + (i % 3) * 0.015,
        phase: Math.random() * Math.PI * 2,
      });
    }
    return out;
  }, [count]);

  useFrame(({ clock }) => {
    if (!groupRef.current) return;
    groupRef.current.position.copy(base);
    const t = clock.getElapsedTime();
    groupRef.current.children.forEach((child, i) => {
      if (!(child instanceof THREE.Mesh)) return;
      const s = stars[i];
      if (!s) return;
      const tw = 1 + Math.sin(t * 2 + s.phase) * 0.15;
      child.position.copy(s.offset).multiplyScalar(tw);
    });
  });

  return (
    <group ref={groupRef} position={[base.x, base.y, base.z]}>
      <mesh
        onClick={(e) => {
          e.stopPropagation();
          onClick(node);
        }}
      >
        <sphereGeometry args={[0.55, 24, 24]} />
        <meshBasicMaterial
          color={clusterColor}
          transparent
          opacity={0.12}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      {stars.map((s, i) => (
        <mesh
          key={i}
          position={s.offset}
          onClick={(e) => {
            e.stopPropagation();
            onClick(node);
          }}
        >
          <sphereGeometry args={[s.size, 8, 8]} />
          <meshStandardMaterial
            color={clusterColor}
            emissive={clusterColor}
            emissiveIntensity={1.2}
            roughness={0.35}
            metalness={0.1}
          />
        </mesh>
      ))}
      <Html distanceFactor={14} position={[0, 0.9, 0]} center>
        <div
          className="text-[9px] font-mono px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap"
          style={{
            color: clusterColor,
            background: 'rgba(0,0,0,0.55)',
            border: `1px solid ${clusterColor}44`,
          }}
        >
          {node.label}
        </div>
      </Html>
    </group>
  );
}

const GOLDEN_ANGLE_LOCAL = 2.399963229728653282;

function focusDistanceForNode(nodeId: string, group: string): number {
  if (nodeId === 'hub') return 14;
  if (group === 'cluster') return 7;
  if (group === 'core') return 10;
  if (group === 'contract') return 8;
  return 6.5;
}

// ---------------------------------------------------------------------------
// Camera — fly to selection and keep OrbitControls target locked
// ---------------------------------------------------------------------------
function CameraRig({
  focusNodeId,
  nodePositions,
  nodeGroups,
}: {
  focusNodeId: string | null;
  nodePositions: Map<string, THREE.Vector3>;
  nodeGroups: Map<string, string>;
}) {
  const { camera } = useThree();
  const controls = useThree((s) => s.controls as OrbitControlsImpl | null);
  const animRef = useRef({
    active: false,
    start: 0,
    from: new THREE.Vector3(),
    to: new THREE.Vector3(),
    lookFrom: new THREE.Vector3(),
    lookTo: new THREE.Vector3(),
  });
  const lastFocusId = useRef<string | null>(null);

  useEffect(() => {
    if (!focusNodeId) {
      lastFocusId.current = null;
      return;
    }
    const target = nodePositions.get(focusNodeId);
    if (!target || lastFocusId.current === focusNodeId) return;
    lastFocusId.current = focusNodeId;

    const group = nodeGroups.get(focusNodeId) ?? 'core';
    const dist = focusDistanceForNode(focusNodeId, group);
    const dir = camera.position.clone().sub(target);
    if (dir.lengthSq() < 0.01) {
      dir.set(0.35, 0.22, 1).normalize();
    } else {
      dir.normalize();
    }
    const to = target.clone().add(dir.multiplyScalar(dist));
    const lookFrom = new THREE.Vector3();
    camera.getWorldDirection(lookFrom).normalize().multiplyScalar(10).add(camera.position);

    animRef.current = {
      active: true,
      start: performance.now(),
      from: camera.position.clone(),
      to,
      lookFrom,
      lookTo: target.clone(),
    };
  }, [focusNodeId, camera, nodePositions, nodeGroups]);

  useFrame(() => {
    const anim = animRef.current;
    if (anim.active) {
      const elapsed = (performance.now() - anim.start) / 1000;
      const duration = 1.4;
      const t = Math.min(elapsed / duration, 1);
      const e = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
      camera.position.lerpVectors(anim.from, anim.to, e);
      const lookX = anim.lookFrom.x + (anim.lookTo.x - anim.lookFrom.x) * e;
      const lookY = anim.lookFrom.y + (anim.lookTo.y - anim.lookFrom.y) * e;
      const lookZ = anim.lookFrom.z + (anim.lookTo.z - anim.lookFrom.z) * e;
      camera.lookAt(lookX, lookY, lookZ);
      if (controls) {
        controls.target.set(lookX, lookY, lookZ);
      }
      if (t >= 1) {
        anim.active = false;
      }
      return;
    }

    if (!focusNodeId || !controls) return;
    const target = nodePositions.get(focusNodeId);
    if (!target) return;
    controls.target.lerp(target, 0.14);
    controls.update();
  });

  return null;
}

// ---------------------------------------------------------------------------
// Scene content
// ---------------------------------------------------------------------------
function SceneContent({
  state,
  onNodeClick,
  themeColor,
  pulseIntensity,
  focusNodeId,
  fundingEvents,
  scenario,
  brightScene = false,
}: {
  state: EcosystemState | null;
  onNodeClick: (n: EcoNode) => void;
  themeColor: string;
  pulseIntensity: number;
  focusNodeId: string | null;
  fundingEvents?: Array<{ id: string; amount: number; token: string; source: string; ts: string }> | null;
  scenario?: { phase: string; phase_progress: number; phase_color: string; tick_count: number; funding_total: number; hub_count: number; buyer_rounds: number } | null;
  /** Brighter lights when Bloom/post-FX is off (safe GPU path). */
  brightScene?: boolean;
}) {
  const nodePositions = useMemo(() => {
    const map = new Map<string, THREE.Vector3>();
    if (state) {
      for (const node of state.nodes) {
        map.set(node.id, new THREE.Vector3(node.position.x, node.position.y, node.position.z));
      }
    }
    return map;
  }, [state]);

  const nodeGroups = useMemo(() => {
    const map = new Map<string, string>();
    if (state) {
      for (const node of state.nodes) {
        map.set(node.id, node.group);
      }
    }
    return map;
  }, [state]);

  const activeLinks = state?.links ?? [];
  const hubPos = new THREE.Vector3(0, 0, 0);

  // Nebula cluster centers
  const nebulaCenters = useMemo(() => [
    { center: new THREE.Vector3(0, 0, 0), color: '#00f0ff', radius: 2.5 },        // core
    { center: new THREE.Vector3(6, 1, 0), color: '#ff00ff', radius: 2.0 },         // contracts
    { center: new THREE.Vector3(-4, 2, -3), color: '#00ff88', radius: 2.0 },       // clients
    { center: new THREE.Vector3(0, -4, -2), color: '#7b2fff', radius: 2.0 },       // plugins
  ], []);

  // Wormhole connections (only major ones)
  const wormholeLinks = useMemo(() => {
    const major = activeLinks.filter((_, i) => i < 12);
    return major.map(link => {
      const srcId = typeof link.source === 'string' ? link.source : '';
      const tgtId = typeof link.target === 'string' ? link.target : '';
      return {
        src: nodePositions.get(srcId) ?? hubPos,
        tgt: nodePositions.get(tgtId) ?? hubPos,
      };
    }).filter(w => w.src && w.tgt);
  }, [activeLinks, nodePositions]);

  return (
    <>
      <CameraRig
        focusNodeId={focusNodeId}
        nodePositions={nodePositions}
        nodeGroups={nodeGroups}
      />

      {/* Lighting — boosted when post-FX disabled (otherwise scene looks like a black void) */}
      <ambientLight intensity={brightScene ? 0.5 : 0.15} />
      <pointLight position={[0, 0, 0]} intensity={brightScene ? 4 : 2.5} color={themeColor} distance={24} />
      <pointLight position={[8, 5, 5]} intensity={brightScene ? 1.2 : 0.4} color="#ff00ff" distance={18} />
      <pointLight position={[-8, -3, -5]} intensity={brightScene ? 0.9 : 0.3} color="#3366ff" distance={18} />

      {/* Deep space starfield */}
      <Stars radius={50} depth={50} count={3000} factor={2.5} saturation={0} fade speed={0.3} />

      {/* Cosmic dust */}
      <CosmicDust color={themeColor} count={400} />

      {/* Nebula clouds around clusters */}
      {nebulaCenters.map((nc, i) => (
        <NebulaCloud key={i} center={nc.center} color={nc.color} radius={nc.radius} />
      ))}

      {/* Asteroid belts at different radii */}
      <AsteroidBelt radius={7} color={themeColor} count={500} tilt={0.3} />
      <AsteroidBelt radius={10} color="#ff00ff" count={350} tilt={-0.4} />
      <AsteroidBelt radius={12} color="#7b2fff" count={300} tilt={0.15} />

      {/* Solar corona around hub */}
      <SolarCorona color={themeColor} intensity={pulseIntensity} />

      {/* Gravity well rings */}
      <GravityWell color={themeColor} intensity={pulseIntensity} />

      {/* Constellation connections */}
      <ConstellationLines links={activeLinks} nodePositions={nodePositions} themeColor={themeColor} />

      {/* Wormhole tunnels */}
      {wormholeLinks.map((wl, i) => (
        <WormholeTunnel
          key={i}
          src={wl.src}
          tgt={wl.tgt}
          color={themeColor}
          intensity={pulseIntensity}
        />
      ))}

      {/* External funding stream */}
      <FundingStream
        hubPosition={hubPos}
        active={(fundingEvents?.length ?? 0) > 0}
        intensity={pulseIntensity}
      />

      {/* Phase ring around hub */}
      {scenario && (
        <PhaseRing
          phaseColor={scenario.phase_color}
          progress={scenario.phase_progress}
          active={true}
        />
      )}

      {/* Ecosystem nodes */}
      {state?.nodes.map((node) =>
        node.group === 'cluster' ? (
          <StarCluster key={node.id} node={node} onClick={onNodeClick} />
        ) : (
          <EcoNodeMesh
            key={node.id}
            node={node}
            onClick={onNodeClick}
            themeColor={themeColor}
            pulseIntensity={pulseIntensity}
          />
        ),
      )}

      {/* Outer orbital ring */}
      <mesh rotation={[Math.PI / 2.2, 0.2, 0]}>
        <torusGeometry args={[8.5, 0.02, 8, 160]} />
        <meshBasicMaterial color={themeColor} transparent opacity={0.06} depthWrite={false} />
      </mesh>
      <mesh rotation={[Math.PI / 2.5, -0.3, 0.1]}>
        <torusGeometry args={[9.5, 0.015, 8, 140]} />
        <meshBasicMaterial color="#ff00ff" transparent opacity={0.04} depthWrite={false} />
      </mesh>

      <OrbitControls
        makeDefault
        enableDamping
        enablePan
        dampingFactor={0.06}
        minDistance={3}
        maxDistance={52}
        maxPolarAngle={Math.PI * 0.78}
        touches={{ ONE: 2, TWO: 2 }}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Funding Stream — cosmic particles flowing from outside toward hub
// ---------------------------------------------------------------------------
function FundingStream({
  hubPosition,
  active,
  intensity,
}: {
  hubPosition: THREE.Vector3;
  active: boolean;
  intensity: number;
}) {
  const pointsRef = useRef<THREE.Points>(null!);
  const particleCount = 80;

  const { positions, origins } = useMemo(() => {
    const pos = new Float32Array(particleCount * 3);
    const org = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      // Particles originate from outside the scene
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.random() * Math.PI * 0.6 + 0.2;
      const dist = 15 + Math.random() * 10;
      org[i * 3] = Math.cos(theta) * Math.cos(phi) * dist;
      org[i * 3 + 1] = Math.sin(phi) * dist * 0.7;
      org[i * 3 + 2] = Math.sin(theta) * Math.cos(phi) * dist;
      pos[i * 3] = org[i * 3];
      pos[i * 3 + 1] = org[i * 3 + 1];
      pos[i * 3 + 2] = org[i * 3 + 2];
    }
    return { positions: pos, origins: org };
  }, [particleCount]);

  useFrame(({ clock }) => {
    if (!pointsRef.current || !active) return;
    const t = clock.getElapsedTime();
    const posArr = pointsRef.current.geometry.attributes.position.array as Float32Array;

    for (let i = 0; i < particleCount; i++) {
      const progress = ((t * 0.15 + i * 0.012) % 1);
      const ease = progress < 0.5
        ? 2 * progress * progress
        : -1 + (4 - 2 * progress) * progress;

      posArr[i * 3] = origins[i * 3] + (hubPosition.x - origins[i * 3]) * ease;
      posArr[i * 3 + 1] = origins[i * 3 + 1] + (hubPosition.y - origins[i * 3 + 1]) * ease;
      posArr[i * 3 + 2] = origins[i * 3 + 2] + (hubPosition.z - origins[i * 3 + 2]) * ease;
    }
    pointsRef.current.geometry.attributes.position.needsUpdate = true;

    const mat = pointsRef.current.material as THREE.PointsMaterial;
    mat.opacity = active ? 0.25 * intensity : 0;
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" array={positions} count={particleCount} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial
        size={0.08}
        color="#ffdd00"
        transparent
        opacity={0}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

// ---------------------------------------------------------------------------
// Phase Ring — rotating ring showing evolution phase progress
// ---------------------------------------------------------------------------
function PhaseRing({
  phaseColor,
  progress,
  active,
}: {
  phaseColor: string;
  progress: number;
  active: boolean;
}) {
  const ringRef = useRef<THREE.Mesh>(null!);

  useFrame((_, delta) => {
    if (ringRef.current) {
      ringRef.current.rotation.z += delta * (0.3 + progress * 0.6);
      ringRef.current.rotation.x += delta * 0.1;
    }
  });

  if (!active) return null;

  const ringRadius = 1.5 + progress * 0.5;

  return (
    <group>
      {/* Phase progress ring */}
      <mesh ref={ringRef} rotation={[Math.PI / 2.5, 0, 0]}>
        <torusGeometry args={[ringRadius, 0.03, 16, 100, progress * Math.PI * 2]} />
        <meshBasicMaterial
          color={phaseColor}
          transparent
          opacity={0.6}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      {/* Full ring ghost */}
      <mesh rotation={[Math.PI / 2.5, 0, 0]}>
        <torusGeometry args={[ringRadius, 0.015, 8, 100]} />
        <meshBasicMaterial
          color={phaseColor}
          transparent
          opacity={0.1}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </group>
  );
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------
interface Props {
  state: EcosystemState | null;
  onNodeClick: (node: EcoNode) => void;
  focusNodeId?: string | null;
  themeColor: string;
  pulseIntensity: number;
  fundingEvents?: Array<{
    id: string;
    amount: number;
    token: string;
    source: string;
    ts: string;
  }> | null;
  scenario?: {
    phase: string;
    phase_progress: number;
    phase_color: string;
    tick_count: number;
    funding_total: number;
    hub_count: number;
    buyer_rounds: number;
  } | null;
}

function useCosmicPostFx(): boolean {
  const isMobile = useIsMobile();
  return useMemo(() => {
    if (isMobile) return false;
    if (typeof window === 'undefined') return true;
    const params = new URLSearchParams(window.location.search);
    if (params.get('safe') === '1' || params.get('fx') === '0') return false;
    if (import.meta.env.VITE_DISABLE_POSTFX === '1') return false;
    return true;
  }, [isMobile]);
}

/** If Bloom/post-FX crashes, keep the 3D scene — drop only the composer pass. */
class PostFxBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  render() {
    if (this.state.failed) return null;
    return this.props.children;
  }
}

export default function EcosystemGraph({
  state,
  onNodeClick,
  focusNodeId = null,
  themeColor,
  pulseIntensity,
  fundingEvents,
  scenario,
}: Props) {
  const isMobile = useIsMobile();
  const enablePostFx = useCosmicPostFx();

  return (
    <div className="absolute inset-0 touch-none">
      <Canvas
        frameloop="always"
        gl={{
          antialias: true,
          alpha: false,
          preserveDrawingBuffer: true,
          powerPreference: 'high-performance',
          failIfMajorPerformanceCaveat: false,
          toneMapping: THREE.ACESFilmicToneMapping,
          toneMappingExposure: 1.35,
          outputColorSpace: THREE.SRGBColorSpace,
        }}
        camera={{ position: [0, 4, 16], fov: isMobile ? 58 : 52, near: 0.1, far: 120 }}
        dpr={isMobile ? [1, 1.25] : [1, 2]}
      >
        <SceneContent
          state={state}
          onNodeClick={onNodeClick}
          themeColor={themeColor}
          pulseIntensity={pulseIntensity}
          focusNodeId={focusNodeId}
          fundingEvents={fundingEvents}
          scenario={scenario}
          brightScene={!enablePostFx}
        />

        {enablePostFx && (
          <PostFxBoundary>
            <EffectComposer multisampling={0} enableNormalPass={false}>
              <Bloom
                luminanceThreshold={0.15}
                luminanceSmoothing={0.9}
                intensity={0.85}
                radius={0.55}
                mipmapBlur
              />
              <Vignette darkness={0.45} offset={0.12} />
              <Noise opacity={0.012} />
            </EffectComposer>
          </PostFxBoundary>
        )}
      </Canvas>

      {/* Radial vignette overlay for depth */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: enablePostFx
            ? 'radial-gradient(ellipse at center, transparent 35%, rgba(5,5,12,0.7) 100%)'
            : 'radial-gradient(ellipse at center, transparent 55%, rgba(5,5,12,0.45) 100%)',
        }}
      />
    </div>
  );
}
