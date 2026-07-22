import type { EcosystemState, EcoNode } from '../App';

const GROUP_COLORS: Record<string, string> = {
  core: '#00f0ff',
  contract: '#ff00ff',
  client: '#00ff88',
  infra: '#7b2fff',
  sdk: '#ffdd00',
  network: '#3366ff',
  chain: '#ff6633',
  product: '#ffaa44',
  cluster: '#ffcc66',
  agent: '#66ffcc',
  oracle: '#a64dff',
  argus: '#36e6ff',
  community: '#c9a227',
  observability: '#00e5cc',
  cognition: '#9b59ff',
  physical: '#43e65a',
};

type Props = {
  state: EcosystemState | null;
  onNodeClick: (n: EcoNode) => void;
  themeColor: string;
};

/** 2D fallback when WebGL canvas is blank (GPU / StrictMode / post-FX issues). */
export default function EcosystemGraph2D({ state, onNodeClick, themeColor }: Props) {
  const nodes = state?.nodes ?? [];
  if (!nodes.length) return null;

  const xs = nodes.map((n) => n.position.x);
  const zs = nodes.map((n) => n.position.z);
  const minX = Math.min(...xs, -1);
  const maxX = Math.max(...xs, 1);
  const minZ = Math.min(...zs, -1);
  const maxZ = Math.max(...zs, 1);
  const spanX = maxX - minX || 1;
  const spanZ = maxZ - minZ || 1;

  const xy = (n: EcoNode) => ({
    x: ((n.position.x - minX) / spanX) * 78 + 11,
    y: ((n.position.z - minZ) / spanZ) * 72 + 14,
  });
  const pos = (n: EcoNode) => ({
    left: `${xy(n).x}%`,
    top: `${xy(n).y}%`,
  });

  return (
    <div className="absolute inset-0 z-[5] overflow-hidden pointer-events-none">
      <svg viewBox="0 0 100 100" className="absolute inset-0 w-full h-full opacity-35" aria-hidden preserveAspectRatio="none">
        {(state?.links ?? []).slice(0, 24).map((link, i) => {
          const a = nodes.find((n) => n.id === link.source);
          const b = nodes.find((n) => n.id === link.target);
          if (!a || !b) return null;
          const pa = xy(a);
          const pb = xy(b);
          return (
            <line
              key={i}
              x1={pa.x}
              y1={pa.y}
              x2={pb.x}
              y2={pb.y}
              stroke={themeColor}
              strokeWidth="0.4"
              strokeOpacity="0.45"
            />
          );
        })}
      </svg>
      {nodes.map((node) => {
        const p = pos(node);
        const color = GROUP_COLORS[node.group] || themeColor;
        const size = node.group === 'core' ? 18 : 10;
        return (
          <button
            key={node.id}
            type="button"
            className="absolute pointer-events-auto rounded-full border border-white/20 transition-transform hover:scale-125 focus:outline-none focus:ring-2 focus:ring-white/40"
            style={{
              ...p,
              width: size,
              height: size,
              marginLeft: -size / 2,
              marginTop: -size / 2,
              backgroundColor: color,
              boxShadow: `0 0 ${size}px ${color}88`,
            }}
            title={node.label}
            onClick={() => onNodeClick(node)}
          />
        );
      })}
    </div>
  );
}
