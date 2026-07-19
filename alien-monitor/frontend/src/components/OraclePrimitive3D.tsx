import { Component, Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import type { ComponentType, LazyExoticComponent, ReactNode } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Stars } from '@react-three/drei';
import { SCENE_LOADERS } from '../oracleScenes/loaders';
import { oracleSceneMeta } from '../oracleScenes/meta';

/**
 * Local, self-contained 3D preview of an oracle's mathematical primitive, shown
 * in the node detail panel — a thumbnail of the selected node. Renders the real
 * animated R3F scene (ported from the Oracle Family portal) for the 13 WebGL
 * oracles, and a bundled HTML-canvas iframe for the 4 "ambient" oracles, so the
 * preview always works with no dependency on the remote site.
 *
 * The preview is non-interactive (auto-spins only); clicking anywhere on it
 * opens the FULL-SCREEN live 3D visualization in a new tab — see liveSceneUrl.
 */

// Cache one lazy component per slug so re-opening a panel never re-creates it.
const sceneCache: Record<string, LazyExoticComponent<ComponentType>> = {};
function getScene(slug: string): LazyExoticComponent<ComponentType> | null {
  const loader = SCENE_LOADERS[slug];
  if (!loader) return null;
  if (!sceneCache[slug]) sceneCache[slug] = lazy(loader);
  return sceneCache[slug];
}

const ASSET_BASE = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');

class SceneBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error) {
    console.warn('[OraclePrimitive3D] local scene failed — using fallback', error);
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function Poster({ accent, label }: { accent: string; label?: string }) {
  return (
    <div
      className="absolute inset-0 flex items-center justify-center"
      style={{
        background: `radial-gradient(115% 85% at 50% 16%, ${accent}33, transparent 60%), radial-gradient(90% 70% at 82% 104%, ${accent}22, transparent 70%), #04030f`,
      }}
    >
      {label && (
        <span className="font-mono text-xs tracking-wider" style={{ color: accent, opacity: 0.7 }}>
          {label}
        </span>
      )}
    </div>
  );
}

/**
 * Ambient oracles ship as full-viewport HTML-canvas visuals (fixed-size HUD,
 * corner-anchored text). To read well in a small thumbnail we render the iframe
 * at a full-screen virtual size and CSS-scale it to COVER the box, keeping the
 * HUD proportions the scene was authored for. pointer-events are disabled so a
 * click falls through to the wrapping "open full scene" link.
 */
const AMBIENT_W = 1280;
const AMBIENT_H = 720;
/** Full portal scene (`?o=slug&embed=1`) — the preview that worked before local R3F. */
function PortalEmbedFrame({ embedUrl, title }: { embedUrl: string; title: string }) {
  return (
    <iframe
      src={embedUrl}
      title={title}
      loading="lazy"
      className="absolute inset-0 h-full w-full"
      style={{ border: 'none', pointerEvents: 'none' }}
      sandbox="allow-scripts allow-same-origin"
      tabIndex={-1}
      aria-hidden="true"
    />
  );
}

function AmbientFrame({ slug, boxHeight }: { slug: string; boxHeight: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [boxW, setBoxW] = useState(320);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(([e]) => setBoxW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // Cover-fit: scale from the top-left, then shift up/left by half the overflow
  // so the scaled scene is centered (px offsets — % would resolve against the
  // un-scaled 1280×720 and mis-center).
  const scale = Math.max(boxW / AMBIENT_W, boxHeight / AMBIENT_H);
  const offX = (AMBIENT_W * scale - boxW) / 2;
  const offY = (AMBIENT_H * scale - boxHeight) / 2;
  return (
    <div ref={ref} className="absolute inset-0" style={{ overflow: 'hidden' }}>
      <iframe
        src={`${ASSET_BASE}/ambient/${slug}/index.html`}
        title={`${slug} live preview`}
        loading="lazy"
        tabIndex={-1}
        aria-hidden="true"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: AMBIENT_W,
          height: AMBIENT_H,
          border: 'none',
          pointerEvents: 'none',
          transformOrigin: 'top left',
          transform: `translate(${-offX}px, ${-offY}px) scale(${scale})`,
        }}
      />
    </div>
  );
}

interface Props {
  slug: string;
  /** Panel theme colour, used for the poster glow + math caption. */
  accent: string;
  mobile?: boolean;
  /** Full-screen live 3D scene; clicking the preview opens it (if present). */
  liveSceneUrl?: string;
  /** Oracle-family portal embed (`?embed=1`) — preferred for WebGL oracles. */
  embedUrl?: string;
  openLabel?: string;
  primitiveLabel?: string;
}

export default function OraclePrimitive3D({
  slug,
  accent,
  mobile = false,
  liveSceneUrl,
  embedUrl,
  openLabel,
  primitiveLabel,
}: Props) {
  const meta = oracleSceneMeta(slug);
  const tint = meta?.accent || accent;
  const Scene = !meta?.ambient ? getScene(slug) : null;
  const height = mobile ? 180 : 210;

  // Nothing we can render locally for this slug → let the caller hide the block.
  const renderable = meta?.ambient || !!Scene;

  const poster = <Poster accent={tint} label={slug.toUpperCase()} />;

  const portalEmbed = !meta?.ambient && embedUrl ? embedUrl : null;

  const body = useMemo(() => {
    if (meta?.ambient) {
      return <AmbientFrame slug={slug} boxHeight={height} />;
    }
    // Portal iframe: full animated scene without a second WebGL context in Monitor.
    if (portalEmbed) {
      return <PortalEmbedFrame embedUrl={portalEmbed} title={`${slug} live scene`} />;
    }
    if (Scene) {
      return (
        <SceneBoundary fallback={portalEmbed ? <PortalEmbedFrame embedUrl={portalEmbed} title={`${slug} live scene`} /> : poster}>
          <Canvas
            className="absolute inset-0"
            // Non-interactive thumbnail: it only auto-spins; a click opens the
            // full scene via the wrapping link.
            style={{ pointerEvents: 'none' }}
            camera={{ position: meta?.camera || [0, 2, 14], fov: 48 }}
            dpr={[1, 1.5]}
            gl={{ antialias: true, alpha: false, powerPreference: 'low-power' }}
            frameloop="always"
          >
            <color attach="background" args={['#04030f']} />
            <fog attach="fog" args={['#04030f', 18, 55]} />
            <ambientLight intensity={0.18} />
            <pointLight position={[8, 10, 6]} intensity={2.2} color="#6ee7ff" />
            <pointLight position={[-6, 5, -4]} intensity={1.5} color="#c084fc" />
            <pointLight position={[0, -3, 8]} intensity={0.6} color="#f472b6" />
            <Stars radius={90} depth={45} count={700} factor={3} fade speed={0.5} />
            <Suspense fallback={null}>
              <Scene />
            </Suspense>
            <OrbitControls enablePan={false} enableZoom={false} enableRotate={false} autoRotate autoRotateSpeed={0.55} />
          </Canvas>
        </SceneBoundary>
      );
    }
    return poster;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, meta?.ambient, portalEmbed, Scene, height, tint, poster]);

  if (!renderable) return null;

  const box = (
    <div
      className="group relative w-full rounded-lg"
      style={{
        height,
        overflow: 'hidden',
        border: `1px solid ${tint}33`,
        backgroundColor: '#04030f',
        boxShadow: `inset 0 0 24px ${tint}11`,
      }}
    >
      {body}
      {liveSceneUrl && (
        <div
          className="pointer-events-none absolute inset-0 flex items-end justify-end p-2 opacity-0 transition-opacity duration-200 group-hover:opacity-100"
          style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.55), transparent 45%)' }}
        >
          <span className="font-mono text-[10px] tracking-wide" style={{ color: tint }}>
            {openLabel || 'Open full scene'} ↗
          </span>
        </div>
      )}
    </div>
  );

  return (
    <div className="mb-4">
      {liveSceneUrl ? (
        <a
          href={liveSceneUrl}
          target="_blank"
          rel="noreferrer"
          aria-label={`${openLabel || 'Open full scene'} — ${slug}`}
          className="block cursor-pointer"
          onClick={(e) => e.stopPropagation()}
        >
          {box}
        </a>
      ) : (
        box
      )}
      {primitiveLabel && (
        <p className="mt-1.5 text-[10px] font-mono leading-snug text-white/40">{primitiveLabel}</p>
      )}
    </div>
  );
}
