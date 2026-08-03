import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Html, Line, OrbitControls, Stars } from '@react-three/drei';
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing';
import * as THREE from 'three';
import type { EcosystemState } from '../App';
import { apiUrl } from '../api';
import { monitorAuthHeaders } from '../monitorAuth';
import { useI18n } from '../i18n';
import { useIsMobile } from '../hooks/useIsMobile';
import {
  buildReputationGraph,
  reputationSignature,
  type ReputationGraph as RepGraphData,
} from '../lib/reputation';

interface Props {
  themeColor: string;
  onClose: () => void;
  monitorState: EcosystemState | null;
  mode: 'test' | 'real' | 'universe';
  mobile?: boolean;
}

const CYAN = new THREE.Color('#6ee7ff');
const PURPLE = new THREE.Color('#c084fc');
const PINK = new THREE.Color('#f472b6');

/** Reputation color: cyan (low) -> purple (mid) -> pink/white-hot (high). */
function rankColor(t: number): THREE.Color {
  const c = new THREE.Color();
  if (t < 0.5) c.copy(CYAN).lerp(PURPLE, t / 0.5);
  else c.copy(PURPLE).lerp(PINK, (t - 0.5) / 0.5);
  return c;
}

const RANK_CSS = (t: number): string => '#' + rankColor(t).getHexString();

interface SceneData {
  positions: THREE.Vector3[];
  colors: THREE.Color[];
  rank: number[];
  edges: Array<{ i: number; j: number; w: number }>;
  topNode: number;
  labels: string[];
  /** node indices that get a floating label (top-ranked, besides the Sun). */
  labelIdx: number[];
}

const LABEL_TOP_N = 6;

function toSceneData(g: RepGraphData): SceneData {
  return {
    positions: g.positions.map((p) => new THREE.Vector3(p[0], p[1], p[2])),
    colors: g.rank.map((t) => rankColor(t)),
    rank: g.rank,
    edges: g.edges,
    topNode: g.topNode,
    labels: g.labels,
    labelIdx: g.ranked.slice(0, LABEL_TOP_N).map((r) => r.index),
  };
}

// ---------------------------------------------------------------------------
// Edges + travelling trust pulses (light flows source -> target, the trust dir)
// ---------------------------------------------------------------------------
const MAX_EDGES_DRAWN = 360;
const MAX_PULSES = 360;

function TrustGraph({ data }: { data: SceneData }) {
  const { positions, edges, rank, colors, topNode } = data;

  const drawn = useMemo(() => edges.slice(0, MAX_EDGES_DRAWN), [edges]);

  const edgeLines = useMemo(() => {
    return drawn.map((ed) => {
      const a = positions[ed.i];
      const b = positions[ed.j];
      const mid = a.clone().add(b).multiplyScalar(0.5).multiplyScalar(1.14);
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      const pts = curve.getPoints(14);
      const t = rank[ed.j] ?? 0;
      return { pts, col: colors[ed.j] ?? CYAN, opacity: 0.06 + t * 0.34, dest: ed.j };
    });
  }, [drawn, positions, rank, colors]);

  const pulseEdges = useMemo(() => {
    return drawn.map((ed) => {
      const a = positions[ed.i];
      const b = positions[ed.j];
      const mid = a.clone().add(b).multiplyScalar(0.5).multiplyScalar(1.14);
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      return {
        curve,
        srcRank: rank[ed.i] ?? 0,
        col: (colors[ed.j] ?? CYAN).clone(),
        speed: 0.18 + (rank[ed.j] ?? 0) * 0.5,
        offset: ((ed.i * 7 + ed.j * 13) % 100) / 100,
      };
    });
  }, [drawn, positions, rank, colors]);

  const pulseCount = Math.min(pulseEdges.length, MAX_PULSES);
  const pulseRef = useRef<THREE.InstancedMesh>(null);
  const tmp = useMemo(() => new THREE.Object3D(), []);
  const tmpC = useMemo(() => new THREE.Color(), []);

  useFrame(({ clock }) => {
    const inst = pulseRef.current;
    if (!inst) return;
    const time = clock.elapsedTime;
    for (let k = 0; k < pulseCount; k++) {
      const e = pulseEdges[k];
      const u = (time * e.speed + e.offset) % 1;
      const p = e.curve.getPoint(u);
      tmp.position.copy(p);
      const arrive = 0.35 + u * 0.65;
      tmp.scale.setScalar((0.05 + e.srcRank * 0.14) * arrive);
      tmp.updateMatrix();
      inst.setMatrixAt(k, tmp.matrix);
      tmpC.copy(e.col).multiplyScalar(0.6 + arrive * 0.8);
      inst.setColorAt(k, tmpC);
    }
    inst.instanceMatrix.needsUpdate = true;
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
  });

  return (
    <group>
      {edgeLines.map((el, i) => (
        <Line
          key={i}
          points={el.pts}
          color={el.col}
          transparent
          opacity={el.opacity}
          lineWidth={el.dest === topNode ? 1.6 : 0.8}
          depthWrite={false}
        />
      ))}
      {pulseCount > 0 && (
        <instancedMesh
          key={pulseCount}
          ref={pulseRef}
          args={[undefined as unknown as THREE.BufferGeometry, undefined as unknown as THREE.Material, pulseCount]}
          frustumCulled={false}
        >
          <sphereGeometry args={[1, 8, 8]} />
          <meshBasicMaterial toneMapped={false} />
        </instancedMesh>
      )}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Nodes — emissive spheres, radius & glow ∝ reputation
// ---------------------------------------------------------------------------
function Nodes({ data, onSelect }: { data: SceneData; onSelect: (i: number) => void }) {
  const { positions, rank, colors } = data;
  const ref = useRef<THREE.InstancedMesh>(null);
  const tmp = useMemo(() => new THREE.Object3D(), []);
  const n = positions.length;

  const meta = useMemo(
    () =>
      positions.map((p, i) => ({
        p,
        baseR: 0.12 + (rank[i] ?? 0) * 0.55,
        rank: rank[i] ?? 0,
        phase: i * 1.37,
      })),
    [positions, rank],
  );

  // Per-instance colors set imperatively via setColorAt — the SAME reliable path
  // the pulses use. (drei <Instance color> + vertexColors left node spheres black.)
  useEffect(() => {
    const inst = ref.current;
    if (!inst) return;
    for (let i = 0; i < n; i++) {
      inst.setColorAt(i, colors[i].clone().multiplyScalar(1.4 + (rank[i] ?? 0) * 1.4));
    }
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
  }, [colors, rank, n]);

  useFrame(({ clock }) => {
    const inst = ref.current;
    if (!inst) return;
    const t = clock.elapsedTime;
    for (let i = 0; i < meta.length; i++) {
      const d = meta[i];
      const pulse = 1 + Math.sin(t * (1.4 + (1 - d.rank) * 1.6) + d.phase) * 0.08;
      tmp.position.copy(d.p);
      tmp.scale.setScalar(d.baseR * pulse);
      tmp.updateMatrix();
      inst.setMatrixAt(i, tmp.matrix);
    }
    inst.instanceMatrix.needsUpdate = true;
  });

  if (n === 0) return null;

  return (
    <instancedMesh
      ref={ref}
      args={[undefined as unknown as THREE.BufferGeometry, undefined as unknown as THREE.Material, n]}
      frustumCulled={false}
      onClick={(e) => {
        if (e.instanceId == null) return;
        e.stopPropagation();
        onSelect(e.instanceId);
      }}
      onPointerOver={(e) => {
        e.stopPropagation();
        document.body.style.cursor = 'pointer';
      }}
      onPointerOut={() => {
        document.body.style.cursor = '';
      }}
    >
      <sphereGeometry args={[1, 20, 20]} />
      {/* self-lit so nodes always show their reputation color regardless of lights */}
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}

// ---------------------------------------------------------------------------
// The Sun — the highest-reputation node: radiant core + halo + corona ring
// ---------------------------------------------------------------------------
function Sun({ data, label, themeColor }: { data: SceneData; label: string; themeColor: string }) {
  const { positions, topNode } = data;
  const pos = positions[topNode];
  const core = useRef<THREE.Mesh>(null);
  const halo = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.Mesh>(null);
  const matCore = useRef<THREE.MeshStandardMaterial>(null);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (core.current) core.current.scale.setScalar(1 + Math.sin(t * 0.8) * 0.06);
    if (matCore.current) matCore.current.emissiveIntensity = 2.4 + Math.sin(t * 1.3) * 0.6;
    if (halo.current) {
      halo.current.scale.setScalar(1 + Math.sin(t * 0.6 + 1) * 0.12);
      (halo.current.material as THREE.MeshBasicMaterial).opacity = 0.16 + Math.sin(t * 0.9) * 0.05;
    }
    if (ring.current) {
      ring.current.rotation.z += 0.004;
      ring.current.rotation.x = Math.PI / 2 + Math.sin(t * 0.4) * 0.3;
    }
  });

  if (!pos) return null;

  return (
    <group position={pos}>
      <mesh ref={core}>
        <sphereGeometry args={[0.62, 32, 32]} />
        <meshStandardMaterial
          ref={matCore}
          color={PINK}
          emissive={PINK}
          emissiveIntensity={2.6}
          toneMapped={false}
          roughness={0.1}
          metalness={0.1}
        />
      </mesh>
      <mesh ref={halo}>
        <sphereGeometry args={[1.2, 24, 24]} />
        <meshBasicMaterial color={PINK} transparent opacity={0.18} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh ref={ring} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1.45, 0.02, 12, 110]} />
        <meshBasicMaterial color={themeColor} transparent opacity={0.6} toneMapped={false} />
      </mesh>
      <pointLight color={PINK} intensity={3.0} distance={14} />
      <Html position={[0, 1.9, 0]} center distanceFactor={10} style={{ pointerEvents: 'none' }}>
        <div
          className="whitespace-nowrap text-[9px] font-mono font-bold uppercase tracking-wider"
          style={{ color: '#ffd9ef', textShadow: '0 0 8px rgba(244,114,182,0.9)' }}
        >
          {label}
        </div>
      </Html>
    </group>
  );
}

// ---------------------------------------------------------------------------
// Floating labels for the top-ranked nodes (besides the Sun) + the selected node,
// so the graph isn't "only the #1 node is named".
// ---------------------------------------------------------------------------
function NodeLabels({ data, selected }: { data: SceneData; selected: number | null }) {
  const { positions, rank, topNode, labels, labelIdx } = data;
  const show = new Set<number>(labelIdx);
  if (selected != null) show.add(selected);
  show.delete(topNode); // the Sun renders its own (larger) label
  return (
    <>
      {[...show].map((i) => {
        const p = positions[i];
        if (!p) return null;
        const r = 0.12 + (rank[i] ?? 0) * 0.55;
        const isSel = i === selected;
        return (
          <Html
            key={i}
            position={[p.x, p.y + r + 0.45, p.z]}
            center
            distanceFactor={11}
            style={{ pointerEvents: 'none' }}
            zIndexRange={[10, 0]}
          >
            <div
              className="whitespace-nowrap text-[8px] font-mono tracking-wide"
              style={{
                color: isSel ? '#ffffff' : RANK_CSS(rank[i] ?? 0),
                opacity: isSel ? 1 : 0.78,
                textShadow: '0 0 6px rgba(0,0,0,0.95)',
                fontWeight: isSel ? 700 : 500,
              }}
            >
              {labels[i]}
            </div>
          </Html>
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Selection ring — highlights the clicked node
// ---------------------------------------------------------------------------
function SelectionRing({ pos, radius }: { pos: THREE.Vector3; radius: number }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (!ref.current) return;
    ref.current.rotation.z += 0.02;
    ref.current.scale.setScalar(1 + Math.sin(clock.elapsedTime * 3) * 0.08);
  });
  return (
    <mesh ref={ref} position={pos}>
      <torusGeometry args={[radius, 0.03, 12, 64]} />
      <meshBasicMaterial color="#ffffff" transparent opacity={0.9} toneMapped={false} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------
function RepScene({
  data,
  topLabel,
  themeColor,
  selected,
  onSelect,
}: {
  data: SceneData;
  topLabel: string;
  themeColor: string;
  selected: number | null;
  onSelect: (i: number) => void;
}) {
  const selPos = selected != null ? data.positions[selected] : null;
  const selR = selected != null ? 0.12 + (data.rank[selected] ?? 0) * 0.55 : 0;
  return (
    <>
      <ambientLight intensity={0.18} />
      <pointLight position={[0, 0, 0]} intensity={1.6} color={themeColor} distance={26} />
      <pointLight position={[8, 6, 6]} intensity={0.6} color="#ff66dd" distance={20} />
      <Stars radius={40} depth={40} count={1200} factor={2} saturation={0} fade speed={0.25} />
      <TrustGraph data={data} />
      <Nodes data={data} onSelect={onSelect} />
      <NodeLabels data={data} selected={selected} />
      {data.topNode >= 0 && <Sun data={data} label={topLabel} themeColor={themeColor} />}
      {selPos && <SelectionRing pos={selPos} radius={selR * 2 + 0.22} />}
      <OrbitControls
        enablePan={false}
        enableDamping
        dampingFactor={0.08}
        autoRotate
        autoRotateSpeed={0.55}
        minDistance={7}
        maxDistance={22}
      />
    </>
  );
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

// ---------------------------------------------------------------------------
// Federation trust enrichment (LIVE / UNI) — real scalar trust per peer
// ---------------------------------------------------------------------------
function usePeerTrust(mode: Props['mode']): Record<string, number> {
  const [peerTrust, setPeerTrust] = useState<Record<string, number>>({});

  useEffect(() => {
    if (mode === 'test') {
      setPeerTrust({});
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    fetch(apiUrl('/api/reputation/peers'), { headers: monitorAuthHeaders(), signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d || !Array.isArray(d.peers)) return;
        const map: Record<string, number> = {};
        for (const p of d.peers) {
          const score = Number(p?.trust_score);
          if (!Number.isFinite(score)) continue;
          for (const key of [p?.url, p?.name, p?.well_known_url]) {
            if (typeof key === 'string' && key.trim()) map[key.trim()] = score;
          }
        }
        setPeerTrust(map);
      })
      .catch(() => {
        /* fail-soft: structural PageRank still renders */
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [mode]);

  return peerTrust;
}

/** Real LUMEN oracle scores (id -> reputation). Fail-soft to local PageRank. */
function useLumenScores(mode: Props['mode']): Record<string, number> | undefined {
  const [scores, setScores] = useState<Record<string, number> | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    fetch(apiUrl('/api/reputation/lumen'), { headers: monitorAuthHeaders(), signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d || !d.ok || !Array.isArray(d.scores) || !Array.isArray(d.ids)) {
          setScores(undefined);
          return;
        }
        const map: Record<string, number> = {};
        d.ids.forEach((id: unknown, i: number) => {
          const s = Number(d.scores[i]);
          if (typeof id === 'string' && Number.isFinite(s)) map[id] = s;
        });
        setScores(Object.keys(map).length ? map : undefined);
      })
      .catch(() => {
        /* fail-soft: the monitor falls back to local PageRank */
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [mode]);
  return scores;
}

function useReputationPostFx(mobile: boolean): boolean {
  return useMemo(() => {
    if (mobile) return false;
    if (typeof window === 'undefined') return true;
    const params = new URLSearchParams(window.location.search);
    if (params.get('safe') === '1' || params.get('fx') === '0') return false;
    if (import.meta.env.VITE_DISABLE_POSTFX === '1') return false;
    return true;
  }, [mobile]);
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------
export default function ReputationGraph({ themeColor, onClose, monitorState, mode, mobile = false }: Props) {
  const { t } = useI18n();
  const isMobile = useIsMobile();
  const enablePostFx = useReputationPostFx(mobile || isMobile);
  const peerTrust = usePeerTrust(mode);
  const lumenScores = useLumenScores(mode);

  const signature = reputationSignature(mode, monitorState, peerTrust, lumenScores);
  // Rebuild only when topology / mode / trust / oracle scores change (not every tick).
  const graph = useMemo(
    () => buildReputationGraph(monitorState, { peerTrust, externalScores: lumenScores }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signature],
  );
  const scene = useMemo(() => toSceneData(graph), [graph]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    if (!mobile) return undefined;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [mobile]);

  // Track the selection by node ID, not array index: the graph rebuilds on every live
  // metric tick (signature change), which used to drop the click and make the info card
  // flicker off. Resolving the id → current index each render keeps the card pinned to
  // the same node across ticks; it only clears if that node truly leaves the graph.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useMemo(() => {
    if (selectedId == null) return null;
    const i = graph.ids.indexOf(selectedId);
    return i >= 0 ? i : null;
  }, [selectedId, graph]);
  const selectByIndex = (i: number) => setSelectedId(graph.ids[i] ?? null);
  // Clear selection only on a real mode switch (a different ecosystem), not every tick.
  useEffect(() => setSelectedId(null), [mode]);
  // Always release a hover cursor when the panel unmounts.
  useEffect(() => () => { document.body.style.cursor = ''; }, []);

  // "Switching…" spinner: the badge flips instantly but the graph reloads with a
  // lag. Show the spinner for a fixed window after a mode change, then ALWAYS
  // clear it — never tied to the backend actually reporting the new mode, so it
  // can't spin forever when a single-mode backend ignores the switch.
  const [syncing, setSyncing] = useState(false);
  const prevModeRef = useRef(mode);
  useEffect(() => {
    if (prevModeRef.current === mode) return undefined;
    prevModeRef.current = mode;
    setSyncing(true);
    const id = window.setTimeout(() => setSyncing(false), 4500);
    return () => window.clearTimeout(id);
  }, [mode]);

  const isLive = mode !== 'test';
  // Badge reflects the actual monitor mode (TEST / UNI / LIVE), color-matched to the switch.
  const modeLabel = mode === 'test' ? t('controls.test') : mode === 'universe' ? t('controls.uni') : t('controls.live');
  const modeColor = mode === 'test' ? '#ffdd00' : '#00ff88';
  const topNode = graph.topNode >= 0 ? graph.ranked[0] : null;
  const ranked = graph.ranked.slice(0, 6);

  const selDetail = useMemo(() => {
    if (selected == null || selected < 0 || selected >= graph.count) return null;
    let inbound = 0; // who trusts this node
    let outbound = 0; // who this node trusts
    for (const e of graph.edges) {
      if (e.j === selected) inbound++;
      if (e.i === selected) outbound++;
    }
    const pos = graph.ranked.findIndex((r) => r.index === selected);
    return {
      label: graph.labels[selected],
      group: graph.groups[selected],
      rank: graph.rank[selected] ?? 0,
      trust: graph.trust[selected],
      pos: pos >= 0 ? pos + 1 : null,
      inbound,
      outbound,
    };
  }, [selected, graph]);

  return (
    <>
      {mobile && (
        <button type="button" className="mobile-backdrop" aria-label={t('mobile.closeSheet')} onClick={onClose} />
      )}
      <div
        className={`z-40 glass-panel flex flex-col animate-slide-up min-h-0 ${
          mobile
            ? 'fixed inset-x-2 top-[max(0.5rem,var(--safe-top))] bottom-[max(0.5rem,var(--safe-bottom))] rounded-2xl'
            : 'absolute right-4 top-32 w-96 max-h-[calc(100vh-220px)]'
        }`}
        style={{
          borderColor: themeColor + '44',
          // Near-opaque so the underlying monitor graph + node labels don't bleed through.
          backgroundColor: 'rgba(8, 10, 18, 0.97)',
          boxShadow: `0 0 30px rgba(0,0,0,0.6), 0 0 15px ${themeColor}22`,
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: themeColor + '22' }}>
          <div className="flex items-center gap-2">
            <span className="text-sm" style={{ color: themeColor }} aria-hidden>
              ⬡
            </span>
            <span className="text-xs font-semibold tracking-wider" style={{ color: themeColor }}>
              {t('reputation.title')}
            </span>
            <span
              className="text-[9px] font-mono px-1.5 py-0.5 rounded uppercase tracking-wider"
              style={{
                color: modeColor,
                backgroundColor: modeColor + '1a',
                border: `1px solid ${modeColor}40`,
              }}
              title={isLive ? t('reputation.liveHint') : t('reputation.simHint')}
            >
              {modeLabel}
            </span>
            {syncing && (
              <span
                className="inline-block w-2.5 h-2.5 rounded-full border-2 animate-spin"
                style={{ borderColor: modeColor, borderTopColor: 'transparent' }}
                title={t('reputation.syncing')}
                aria-label={t('reputation.syncing')}
              />
            )}
          </div>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white/80 transition-colors text-2xl leading-none w-10 h-10 flex items-center justify-center shrink-0"
            aria-label={t('mobile.closeSheet')}
          >
            ×
          </button>
        </div>

        {/* Subtitle / source */}
        <div className="px-4 py-1.5 text-[9px] font-mono text-white/35 border-b" style={{ borderColor: themeColor + '12' }}>
          {isLive && graph.hasLiveTrust
            ? t('reputation.sourceLiveTrust', { n: graph.liveTrustCount })
            : isLive
              ? t('reputation.sourceLive')
              : t('reputation.sourceSim')}
        </div>

        {/* 3D graph */}
        <div
          className={`relative ${mobile ? 'flex-1 min-h-0' : 'h-72'}`}
          style={{ minHeight: mobile ? 0 : 288, background: '#06070e' }}
        >
          {graph.count === 0 ? (
            <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-white/40">
              {monitorState ? t('reputation.empty') : t('reputation.loading')}
            </div>
          ) : (
            <Canvas
              frameloop="always"
              gl={{
                antialias: true,
                alpha: true,
                powerPreference: 'high-performance',
                failIfMajorPerformanceCaveat: false,
                toneMapping: THREE.ACESFilmicToneMapping,
                toneMappingExposure: 1.35,
                outputColorSpace: THREE.SRGBColorSpace,
              }}
              camera={{ position: [0, 1.5, 13], fov: 52, near: 0.1, far: 100 }}
              dpr={mobile || isMobile ? [1, 1.25] : [1, 2]}
              onPointerMissed={() => setSelectedId(null)}
            >
              <group key={`${mode}-${graph.count}`}>
                <RepScene
                  data={scene}
                  topLabel={topNode?.label ?? ''}
                  themeColor={themeColor}
                  selected={selected}
                  onSelect={selectByIndex}
                />
              </group>
              {enablePostFx && (
                <PostFxBoundary>
                  <EffectComposer multisampling={0} enableNormalPass={false}>
                    <Bloom luminanceThreshold={0.15} luminanceSmoothing={0.9} intensity={0.9} radius={0.6} mipmapBlur />
                    <Vignette darkness={0.5} offset={0.1} />
                  </EffectComposer>
                </PostFxBoundary>
              )}
            </Canvas>
          )}
          <div
            className="absolute inset-0 pointer-events-none"
            style={{ background: 'radial-gradient(ellipse at center, transparent 45%, rgba(5,5,12,0.55) 100%)' }}
          />

          {/* Hint when nothing selected */}
          {graph.count > 0 && !selDetail && (
            <div className="absolute left-2 top-2 text-[8px] font-mono text-white/25 pointer-events-none">
              {t('reputation.tapHint')}
            </div>
          )}

          {/* Selected-node detail card */}
          {selDetail && (
            <div
              className="absolute left-2 right-2 bottom-2 rounded-lg border px-3 py-2 backdrop-blur-sm"
              style={{ borderColor: themeColor + '55', background: 'rgba(6,7,14,0.94)' }}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: RANK_CSS(selDetail.rank) }} />
                  <span
                    className="truncate text-[11px] font-semibold"
                    style={{ color: RANK_CSS(selDetail.rank) }}
                    title={selDetail.label}
                  >
                    {selDetail.label}
                  </span>
                </div>
                <button
                  onClick={() => setSelectedId(null)}
                  className="shrink-0 px-1 text-base leading-none text-white/40 hover:text-white/80"
                  aria-label={t('mobile.closeSheet')}
                >
                  ×
                </button>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[9px] font-mono text-white/55">
                {selDetail.pos != null && (
                  <span style={{ color: RANK_CSS(selDetail.rank) }}>{t('reputation.rankPos', { n: selDetail.pos })}</span>
                )}
                <span>
                  {t('reputation.repScore')}: {(selDetail.rank * 100).toFixed(0)}%
                </span>
                <span>{t(`group.${selDetail.group}`, undefined, selDetail.group)}</span>
                <span>
                  {t('reputation.inbound')}: {selDetail.inbound}
                </span>
                <span>
                  {t('reputation.outbound')}: {selDetail.outbound}
                </span>
                {selDetail.trust != null && (
                  <span className="text-emerald-300/80" title={t('reputation.realTrust')}>
                    ◈ {(selDetail.trust * 100).toFixed(0)}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Legend + ranking */}
        <div className="px-4 py-2.5 border-t overflow-y-auto" style={{ borderColor: themeColor + '18' }}>
          {/* Reputation gradient legend */}
          <div className="flex items-center justify-between mb-2 text-[9px] font-mono text-white/40">
            <span>{t('reputation.legendLow')}</span>
            <div
              className="flex-1 mx-2 h-1.5 rounded-full"
              style={{ background: `linear-gradient(90deg, ${RANK_CSS(0)}, ${RANK_CSS(0.5)}, ${RANK_CSS(1)})` }}
            />
            <span>{t('reputation.legendHigh')}</span>
          </div>

          {topNode && (
            <div className="flex items-center justify-between mb-1.5 text-[10px] font-mono">
              <span className="text-white/45">{t('reputation.mostTrusted')}</span>
              <span className="font-semibold" style={{ color: RANK_CSS(1) }}>
                {topNode.label}
              </span>
            </div>
          )}

          <div className="flex flex-col gap-1">
            {ranked.map((r, idx) => (
              <div key={r.id} className="flex items-center gap-2 text-[10px] font-mono">
                <span className="w-3 text-right text-white/30">{idx + 1}</span>
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: RANK_CSS(r.rank) }} />
                <span className="flex-1 truncate text-white/70" title={r.label}>
                  {r.label}
                </span>
                {r.trust != null && (
                  <span className="text-[8px] text-emerald-300/70" title={t('reputation.realTrust')}>
                    ◈{(r.trust * 100).toFixed(0)}
                  </span>
                )}
                <div className="w-14 h-1 rounded-full bg-white/8 overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${Math.max(6, r.rank * 100).toFixed(0)}%`, backgroundColor: RANK_CSS(r.rank) }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="mt-2 pt-2 border-t flex items-center justify-between text-[9px] font-mono text-white/30" style={{ borderColor: themeColor + '12' }}>
            <span>{t('reputation.stats', { nodes: graph.count, edges: graph.edges.length })}</span>
            <span title="EigenTrust / PageRank">PageRank · d=0.85</span>
          </div>
        </div>
      </div>
    </>
  );
}
