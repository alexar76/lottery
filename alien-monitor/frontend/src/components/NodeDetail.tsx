import { useEffect, useMemo, useRef, useState } from 'react';
import type { EcoNode } from '../App';
import { useI18n } from '../i18n';
import {
  descriptionWithoutCaps,
  fetchOracleTools,
  parseCapsFromDescription,
  slugFromNodeId,
  type OracleManifest,
} from '../lib/oracleManifest';
import OraclePrimitive3D from './OraclePrimitive3D';
import { oracleSceneMeta } from '../oracleScenes/meta';
import MetisChat from './MetisChat';

interface Props {
  node: EcoNode;
  onClose: () => void;
  themeColor: string;
  mobile?: boolean;
}

function isExpandableMetric(value: unknown): boolean {
  const s = String(value);
  return s.length > 16 || /^0x[a-fA-F0-9]{10,}$/.test(s);
}

function truncateMetric(value: unknown): string {
  const s = String(value);
  if (s.length <= 18) return s;
  if (/^0x[a-fA-F0-9]+$/.test(s) && s.length > 14) {
    return `${s.slice(0, 8)}…${s.slice(-6)}`;
  }
  return `${s.slice(0, 14)}…`;
}

function MetricCell({
  metricKey,
  metricLabel,
  value,
  themeColor,
  expanded,
  onToggle,
}: {
  metricKey: string;
  metricLabel: string;
  value: unknown;
  themeColor: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const full = typeof value === 'number' ? value.toLocaleString() : String(value);
  const expandable = isExpandableMetric(value);
  const display = expanded || !expandable ? full : truncateMetric(value);

  return (
    <div
      role={expandable ? 'button' : undefined}
      tabIndex={expandable ? 0 : undefined}
      onClick={expandable ? onToggle : undefined}
      onKeyDown={
        expandable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onToggle();
              }
            }
          : undefined
      }
      className={`relative px-3 py-2 rounded transition-all duration-300 ease-out ${
        expandable ? 'cursor-pointer hover:brightness-110' : ''
      } ${expanded ? 'col-span-2 z-40' : 'min-w-0'}`}
      style={{
        backgroundColor: themeColor + (expanded ? '18' : '0a'),
        border: `1px solid ${themeColor}${expanded ? '66' : '18'}`,
        transform: expanded
          ? 'perspective(720px) translateZ(28px) scale(1.06) rotateX(6deg)'
          : undefined,
        transformStyle: 'preserve-3d',
        boxShadow: expanded ? `0 12px 32px rgba(0,0,0,0.55), 0 0 20px ${themeColor}33` : undefined,
      }}
    >
      <div
        className={`font-mono font-bold ${expanded ? 'text-base break-all leading-snug' : 'text-sm truncate'}`}
        style={{ color: themeColor }}
        title={expandable && !expanded ? full : undefined}
      >
        {display}
      </div>
      <div className="text-[10px] font-mono text-white/40 mt-0.5">
        {metricLabel}
      </div>
    </div>
  );
}

export default function NodeDetail({ node, onClose, themeColor, mobile = false }: Props) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLDivElement>(null);
  const [expandedMetric, setExpandedMetric] = useState<string | null>(null);
  const [expandedChild, setExpandedChild] = useState<string | null>(null);

  const metricLabel = (key: string) =>
    t(`nodeDetail.metricKeys.${key}`, undefined, key.replace(/_/g, ' '));

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (expandedChild) setExpandedChild(null);
        else if (expandedMetric) setExpandedMetric(null);
        else onClose();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose, expandedMetric, expandedChild]);

  const toggleMetric = (key: string) => {
    setExpandedMetric((prev) => (prev === key ? null : key));
  };

  const statusColor =
    node.status === 'active' ? '#00ff88' :
    node.status === 'error' ? '#ff3355' :
    node.status === 'idle' ? '#ffdd00' : '#666666';

  useEffect(() => {
    if (!mobile) return undefined;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [mobile]);

  // --- Oracle preview + products/services ---
  const isOracle = node.group === 'oracle' && node.id.startsWith('oracle-');
  const oracleSlug = isOracle ? slugFromNodeId(node.id) : '';
  // We can render a local math-primitive preview only for slugs we know a scene
  // (or bundled ambient visual) for. Unknown oracle nodes (e.g. the UMBRAL cave)
  // simply skip the preview block.
  const previewMeta = isOracle ? oracleSceneMeta(oracleSlug) : undefined;
  const embedUrl = useMemo(() => {
    if (!isOracle || !node.url) return undefined;
    return node.url + (node.url.includes('?') ? '&' : '?') + 'embed=1';
  }, [isOracle, node.url]);

  // Capability ids parsed off the node — the always-available fallback.
  const fallbackCaps = useMemo(
    () => (isOracle ? parseCapsFromDescription(node.description) : []),
    [isOracle, node.description],
  );
  const oracleBlurb = useMemo(
    () => (isOracle ? descriptionWithoutCaps(node.description) : ''),
    [isOracle, node.description],
  );

  // Live products & services from the oracle's AI-Market manifest (best-effort, cached).
  const [manifest, setManifest] = useState<OracleManifest | null>(null);
  useEffect(() => {
    if (!isOracle) {
      setManifest(null);
      return undefined;
    }
    let alive = true;
    setManifest(null);
    fetchOracleTools(node.url, oracleSlug)
      .then((m) => {
        if (alive) setManifest(m);
      })
      .catch(() => {
        if (alive) setManifest(null);
      });
    return () => {
      alive = false;
    };
  }, [isOracle, node.url, oracleSlug]);
  const manifestTools = manifest?.tools ?? null;

  return (
    <>
      {mobile && (
        <button
          type="button"
          className="mobile-backdrop"
          aria-label={t('mobile.closeSheet')}
          onClick={onClose}
        />
      )}
      <div
      ref={panelRef}
      className={`z-40 glass-panel p-4 md:p-5 animate-slide-in overflow-visible ${
        mobile
          ? 'fixed inset-x-0 bottom-0 mobile-sheet max-h-[min(72dvh,520px)] overflow-y-auto'
          : 'absolute left-4 top-24 w-80 max-h-[calc(100vh-8rem)] overflow-y-auto'
      }`}
      style={{
        borderColor: themeColor + '44',
        boxShadow: `0 0 30px rgba(0,0,0,0.5), 0 0 15px ${themeColor}22`,
        perspective: '900px',
      }}
      onClick={() => {
        if (expandedMetric) setExpandedMetric(null);
        if (expandedChild) setExpandedChild(null);
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <div
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: statusColor, boxShadow: `0 0 6px ${statusColor}` }}
          />
          <h3 className="text-sm font-semibold truncate" style={{ color: themeColor }}>
            {node.label}
          </h3>
        </div>
        <button
          onClick={onClose}
          className="text-white/40 hover:text-white/80 transition-colors text-2xl leading-none w-10 h-10 flex items-center justify-center shrink-0"
          aria-label={t('mobile.closeSheet')}
        >
          ×
        </button>
      </div>

      {/* Description — localized per node id, with the backend English text as fallback. */}
      <p className="text-xs text-white/60 mb-4 leading-relaxed">
        {t(`nodeDetail.desc.${node.id}`, undefined, isOracle ? oracleBlurb : node.description)}
      </p>

      {/* Oracle math-primitive preview — a real, locally-rendered 3D scene of the
          oracle's mathematics (or a bundled ambient canvas), with a clickable
          link to the full live scene. No dependency on the remote site. */}
      {previewMeta && (
        <div className="mb-4" onClick={(e) => e.stopPropagation()}>
          <OraclePrimitive3D
            slug={oracleSlug}
            accent={themeColor}
            mobile={mobile}
            liveSceneUrl={node.url}
            embedUrl={embedUrl}
            openLabel={t('nodeDetail.oracle.openScene')}
            primitiveLabel={previewMeta.primitive}
          />
        </div>
      )}

      {/* Group badge */}
      <div className="mb-4">
        <span
          className="inline-block px-2 py-0.5 rounded text-[10px] font-mono uppercase"
          style={{
            backgroundColor: themeColor + '18',
            color: themeColor,
            border: `1px solid ${themeColor}44`,
          }}
        >
          {t(`group.${node.group}`, undefined, node.group)}
        </span>
        <span
          className="inline-block ml-2 px-2 py-0.5 rounded text-[10px] font-mono uppercase"
          style={{
            backgroundColor: statusColor + '18',
            color: statusColor,
            border: `1px solid ${statusColor}44`,
          }}
        >
          {t(`status.${node.status}`)}
        </span>
      </div>

      {/* Oracle products & services — capabilities (id · what · price) + math one-liner.
          Prefers the live AI-Market manifest; falls back to capability ids on the node. */}
      {isOracle && (manifestTools?.length || fallbackCaps.length > 0) && (
        <div className="mb-4" onClick={(e) => e.stopPropagation()}>
          <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-2">
            {t('nodeDetail.oracle.products')}
          </div>
          <div className="space-y-1.5">
            {manifestTools && manifestTools.length > 0
              ? manifestTools.map((tool) => (
                  <div
                    key={tool.capability_id}
                    className="px-3 py-2 rounded"
                    style={{
                      backgroundColor: themeColor + '0a',
                      border: `1px solid ${themeColor}18`,
                    }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className="font-mono text-xs font-semibold truncate"
                        style={{ color: themeColor }}
                        title={tool.capability_id}
                      >
                        {tool.capability_id}
                      </span>
                      {typeof tool.price_per_call_usd === 'number' && (
                        <span className="font-mono text-[10px] text-white/50 shrink-0">
                          ${tool.price_per_call_usd}
                        </span>
                      )}
                    </div>
                    {tool.description && (
                      <div className="text-[11px] text-white/50 mt-0.5 leading-snug">
                        {tool.description}
                      </div>
                    )}
                  </div>
                ))
              : fallbackCaps.map((cap) => (
                  <div
                    key={cap}
                    className="px-3 py-1.5 rounded font-mono text-xs"
                    style={{
                      backgroundColor: themeColor + '0a',
                      border: `1px solid ${themeColor}18`,
                      color: themeColor,
                    }}
                  >
                    {cap}
                  </div>
                ))}
          </div>
          {/* Math one-liner — oracle-level description from the manifest when available. */}
          {manifest?.description && (
            <p className="mt-2 text-[11px] text-white/45 leading-snug">
              <span className="font-mono uppercase tracking-wider text-white/30">
                {t('nodeDetail.oracle.math')}:
              </span>{' '}
              {manifest.description}
            </p>
          )}
        </div>
      )}

      {/* Metrics */}
      {Object.keys(node.metrics).length > 0 && (
        <div className="mb-4" onClick={(e) => e.stopPropagation()}>
          <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-2">
            {t('nodeDetail.metrics')}
          </div>
          <div className="grid grid-cols-2 gap-2 min-w-0">
            {Object.entries(node.metrics).map(([key, value]) => (
              <MetricCell
                key={key}
                metricKey={key}
                metricLabel={metricLabel(key)}
                value={value}
                themeColor={themeColor}
                expanded={expandedMetric === key}
                onToggle={() => toggleMetric(key)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Sub-components — generic nodes, or DIOSCURI twins + collaboration split */}
      {node.id === 'dioscuri' && (node.children?.length || node.collaboration) ? (
        <div className="mb-4" onClick={(e) => e.stopPropagation()}>
          {node.children && node.children.length > 0 && (
            <>
              <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-2">
                {t('nodeDetail.dioscuri.twinsTitle')}
              </div>
              <div className="space-y-1">
                {node.children.map((child) => {
                  const isExpanded = expandedChild === child.id;
                  return (
                    <div key={child.id}>
                      <button
                        type="button"
                        onClick={() => setExpandedChild(isExpanded ? null : child.id)}
                        className="w-full px-3 py-1.5 rounded text-xs flex items-center gap-2 transition-colors hover:brightness-110 cursor-pointer text-left"
                        style={{
                          backgroundColor: themeColor + (isExpanded ? '16' : '08'),
                          border: isExpanded ? `1px solid ${themeColor}44` : undefined,
                        }}
                      >
                        <div
                          className="w-1.5 h-1.5 rounded-full shrink-0"
                          style={{ backgroundColor: themeColor, opacity: isExpanded ? 1 : 0.6 }}
                        />
                        <span className="text-white/70">{child.label}</span>
                        <span className="ml-auto text-white/30">{isExpanded ? '▾' : '▸'}</span>
                      </button>
                      {isExpanded && (
                        <div
                          className="mt-1 ml-3 mr-1 px-3 py-2 rounded text-xs"
                          style={{
                            backgroundColor: themeColor + '10',
                            border: `1px solid ${themeColor}28`,
                          }}
                        >
                          <div className="text-white/55 mb-2 leading-relaxed">
                            {child.id === 'castor'
                              ? t('nodeDetail.dioscuri.castorBlurb')
                              : t('nodeDetail.dioscuri.polluxBlurb')}
                          </div>
                          {child.url && (
                            <a
                              href={child.url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 font-mono transition-colors hover:brightness-110"
                              style={{ color: themeColor }}
                            >
                              {child.id === 'castor'
                                ? t('nodeDetail.dioscuri.castorLink')
                                : t('nodeDetail.dioscuri.polluxLink')}{' '}
                              ↗
                            </a>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
          {node.collaboration && (
            <>
              <div
                className="my-3 border-t border-dashed"
                style={{ borderColor: themeColor + '28' }}
              />
              <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-1">
                {t('nodeDetail.dioscuri.collaborationTitle')}
              </div>
              <div className="text-[9px] font-mono text-white/35 mb-2 leading-relaxed">
                {t('nodeDetail.dioscuri.collaborationNote')}
              </div>
              {(() => {
                const collab = node.collaboration!;
                const collabColor = '#4de8ff';
                const isExpanded = expandedChild === collab.id;
                const theorosActive = collab.active === true;
                const statusLabel = theorosActive
                  ? t('nodeDetail.dioscuri.theorosActive')
                  : t('nodeDetail.dioscuri.theorosInactive');
                const statusStyle = theorosActive
                  ? { backgroundColor: '#22c55e22', color: '#86efac' }
                  : { backgroundColor: '#ffffff12', color: '#ffffff55' };
                return (
                  <div>
                    <button
                      type="button"
                      onClick={() => setExpandedChild(isExpanded ? null : collab.id)}
                      className="w-full px-3 py-2 rounded text-xs flex items-center gap-2 transition-colors hover:brightness-110 cursor-pointer text-left"
                      style={{
                        backgroundColor: collabColor + (isExpanded ? '18' : '0c'),
                        border: `1px solid ${collabColor}${isExpanded ? '66' : '33'}`,
                      }}
                    >
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0"
                        style={{ backgroundColor: collabColor + '22', color: collabColor }}>
                        {t('nodeDetail.dioscuri.collaborationBadge')}
                      </span>
                      <span className="text-white/80 font-medium">{collab.label}</span>
                      <span
                        className="text-[9px] font-mono px-1.5 py-0.5 rounded shrink-0"
                        style={statusStyle}
                      >
                        {statusLabel}
                      </span>
                      <span className="ml-auto text-white/30">{isExpanded ? '▾' : '▸'}</span>
                    </button>
                    {isExpanded && (
                      <div
                        className="mt-1 px-3 py-2 rounded text-xs"
                        style={{
                          backgroundColor: collabColor + '0c',
                          border: `1px solid ${collabColor}33`,
                        }}
                      >
                        <div className="text-white/55 mb-2 leading-relaxed">
                          {t('nodeDetail.dioscuri.theorosBlurb')}
                        </div>
                        <div className="flex flex-col gap-1.5">
                          {collab.url && (
                            <a
                              href={collab.url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 font-mono transition-colors hover:brightness-110"
                              style={{ color: collabColor }}
                            >
                              {t('nodeDetail.dioscuri.theorosLanding')} ↗
                            </a>
                          )}
                          {collab.repo && (
                            <a
                              href={collab.repo}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 font-mono text-white/45 hover:text-white/70"
                            >
                              {t('nodeDetail.dioscuri.theorosRepo')} ↗
                            </a>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })()}
            </>
          )}
        </div>
      ) : node.children && node.children.length > 0 ? (
        <div onClick={(e) => e.stopPropagation()}>
          <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-2">
            {t('nodeDetail.subcomponents', { count: node.children.length })}
          </div>
          <div className="space-y-1 max-h-56 overflow-y-auto">
            {node.children.map((child) => {
              const childBody = (
                <>
                  <div
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ backgroundColor: themeColor, opacity: 0.6 }}
                  />
                  <span className="text-white/70">{child.label}</span>
                  {child.url && <span className="ml-auto text-white/30">↗</span>}
                </>
              );
              return child.url ? (
                <a
                  key={child.id}
                  href={child.url}
                  target="_blank"
                  rel="noreferrer"
                  className="px-3 py-1.5 rounded text-xs flex items-center gap-2 transition-colors hover:brightness-110"
                  style={{ backgroundColor: themeColor + '08', color: themeColor }}
                >
                  {childBody}
                </a>
              ) : (
                <div
                  key={child.id}
                  className="px-3 py-1.5 rounded text-xs flex items-center gap-2"
                  style={{ backgroundColor: themeColor + '08' }}
                >
                  {childBody}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* DIOSCURI community links — twins only (THEOROS lives under Collaboration). */}
      {node.id === 'dioscuri' && node.community_links && Object.keys(node.community_links).length > 0 && (
        <div className="mb-4" onClick={(e) => e.stopPropagation()}>
          <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-2">
            {t('nodeDetail.community.title')}
          </div>
          <div className="space-y-1.5">
            {node.community_links.telegram && (
              <a
                href={node.community_links.telegram}
                target="_blank"
                rel="noreferrer"
                className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
              >
                {t('nodeDetail.community.telegramBot')} ↗
              </a>
            )}
            {node.community_links.telegram_channel && (
              <a
                href={node.community_links.telegram_channel}
                target="_blank"
                rel="noreferrer"
                className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
              >
                {t('nodeDetail.community.telegramChannel')} ↗
              </a>
            )}
            {node.community_links.discord && (
              <a
                href={node.community_links.discord}
                target="_blank"
                rel="noreferrer"
                className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
              >
                {t('nodeDetail.community.discord')} ↗
              </a>
            )}
            {node.community_links.github && (
              <a
                href={node.community_links.github}
                target="_blank"
                rel="noreferrer"
                className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
              >
                {t('nodeDetail.community.github')} ↗
              </a>
            )}
          </div>
        </div>
      )}

      {/* HELIOS YouTube channel link */}
      {node.id === 'helios' && node.youtube_url && (
        <div className="mb-4" onClick={(e) => e.stopPropagation()}>
          <a
            href={node.youtube_url}
            target="_blank"
            rel="noreferrer"
            className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
            style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
          >
            YouTube channel ↗
          </a>
          {node.helios_live?.cached_at && (
            <div className="text-[9px] font-mono text-white/30 mt-1">
              stats cached {node.helios_live.cached_at}
              {node.helios_live.stale ? ' (stale)' : ''}
            </div>
          )}
        </div>
      )}

      {/* SKOPOS — dashboard + docs links (public status in metrics). */}
      {node.id === 'skopos' && node.links && Object.keys(node.links).length > 0 && (
        <div className="mb-4" onClick={(e) => e.stopPropagation()}>
          <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-2">
            {t('nodeDetail.links', undefined, 'Links')}
          </div>
          <div className="space-y-1.5">
            {node.links.dashboard && (
              <a
                href={node.links.dashboard}
                target="_blank"
                rel="noreferrer"
                className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                style={{ backgroundColor: themeColor + '1e', border: `1px solid ${themeColor}55`, color: themeColor }}
              >
                {t('skopos.dashboard', undefined, '🛰️ Open SKOPOS dashboard')} ↗
              </a>
            )}
            {node.links.github && (
              <a
                href={node.links.github}
                target="_blank"
                rel="noreferrer"
                className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
              >
                {t('nodeDetail.community.github')} ↗
              </a>
            )}
            {node.links.docs && (
              <a
                href={node.links.docs}
                target="_blank"
                rel="noreferrer"
                className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
              >
                {t('skopos.docs', undefined, 'Documentation')} ↗
              </a>
            )}
            {node.links.integration && (
              <a
                href={node.links.integration}
                target="_blank"
                rel="noreferrer"
                className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
              >
                {t('skopos.integration', undefined, 'Ecosystem integration')} ↗
              </a>
            )}
          </div>
          {node.skopos_live && (
            <div className="mt-3 text-[11px] font-mono text-white/45 space-y-1">
              {node.skopos_live.database && (
                <div>{t('skopos.db', undefined, 'Database')}: {String(node.skopos_live.database)}</div>
              )}
              {Array.isArray(node.skopos_live.log_parsers) && node.skopos_live.log_parsers.length > 0 && (
                <div>{t('skopos.parsers', undefined, 'Log parsers')}: {node.skopos_live.log_parsers.join(', ')}</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* GAIA — physical-oracle device fleet: click-through device list + what each transmits. */}
      {node.id === 'gaia' && (
        <div className="mb-4" onClick={(e) => e.stopPropagation()}>
          {node.gaia_live && (() => {
            const total = node.gaia_live!.device_count ?? (node.gaia_live!.devices?.length || 0);
            const live = node.gaia_live!.live_relays ?? 0;
            const sim = Math.max(0, total - live);
            return (
              <div
                className="mb-3 px-3 py-2 rounded text-[11px] font-mono flex flex-wrap items-center gap-x-3 gap-y-1"
                style={{ backgroundColor: themeColor + '10', border: `1px solid ${themeColor}30`, color: themeColor }}
              >
                {live > 0 && (
                  <span style={{ color: '#43e65a' }}>🌍 {live} {t('gaia.n_live', undefined, 'live')} · {t('gaia.real_apis', undefined, 'real public-API sensors')}</span>
                )}
                {sim > 0 && (
                  <span className="text-white/45">⚙ {sim} {t('gaia.n_sim', undefined, 'simulated (deterministic)')}</span>
                )}
              </div>
            );
          })()}
          {Array.isArray(node.gaia_live?.devices) && node.gaia_live!.devices!.length > 0 && (
            <>
              <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-2">
                {t('gaia.devices', undefined, 'Devices')} ({node.gaia_live!.devices!.length})
              </div>
              <div className="space-y-2">
                {[...node.gaia_live!.devices!]
                  .sort((a, b) => (b.live ? 1 : 0) - (a.live ? 1 : 0))
                  .map((d) => {
                  const faulted = !!d.fault && d.fault !== 'none';
                  const statusBg = faulted ? '#ff333322' : d.online ? '#43e65a22' : '#88888822';
                  const statusFg = faulted ? '#ff6666' : d.online ? '#43e65a' : '#aaaaaa';
                  const accent = d.live ? '#43e65a' : '#8a8a8a';
                  return (
                    <div
                      key={d.id}
                      className="px-3 py-2 rounded"
                      style={{ backgroundColor: themeColor + '0d', border: `1px solid ${themeColor}22`, borderLeft: `3px solid ${accent}` }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-mono font-semibold" style={{ color: themeColor }}>{d.id}</span>
                        <span className="flex items-center gap-1 whitespace-nowrap">
                          <span
                            className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded"
                            style={d.live
                              ? { backgroundColor: '#43e65a26', color: '#43e65a', border: '1px solid #43e65a66' }
                              : { backgroundColor: '#8a8a8a22', color: '#b4b4b4', border: '1px solid #8a8a8a44' }}
                          >
                            {d.live ? t('gaia.kind_live', undefined, '🌍 LIVE') : t('gaia.kind_sim', undefined, '⚙ SIM')}
                          </span>
                          <span
                            className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                            style={{ backgroundColor: statusBg, color: statusFg }}
                          >
                            {faulted
                              ? d.fault
                              : d.online
                                ? t('gaia.online', undefined, 'online')
                                : t('gaia.offline', undefined, 'offline')}
                          </span>
                        </span>
                      </div>
                      {d.model && <div className="text-[10px] font-mono text-white/45 mt-0.5">{d.model}</div>}
                      <div className="text-[10px] font-mono text-white/35 mt-1">
                        {d.site ? `${d.site} · ` : ''}{t('gaia.transmits', undefined, 'transmits')}:
                      </div>
                      {Array.isArray(d.fields) && d.fields.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {d.fields.map((f) => (
                            <span
                              key={f.name}
                              className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                              style={{ backgroundColor: themeColor + '14', color: themeColor }}
                            >
                              {f.name}{f.unit ? ` (${f.unit})` : ''}
                            </span>
                          ))}
                        </div>
                      )}
                      {d.live && d.source && (
                        <div className="text-[9px] font-mono mt-1" style={{ color: '#43e65a', opacity: 0.75 }}>
                          {t('gaia.live_source', undefined, 'live source')} → {d.source}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
          {node.links && Object.keys(node.links).length > 0 && (
            <div className="mt-3 space-y-1.5">
              {node.links.landing && (
                <a
                  href={node.links.landing}
                  target="_blank"
                  rel="noreferrer"
                  className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                  style={{ backgroundColor: themeColor + '1e', border: `1px solid ${themeColor}55`, color: themeColor }}
                >
                  {t('gaia.landing', undefined, '🌍 Open GAIA gateway')} ↗
                </a>
              )}
              {node.links.github && (
                <a
                  href={node.links.github}
                  target="_blank"
                  rel="noreferrer"
                  className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                  style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
                >
                  {t('nodeDetail.community.github')} ↗
                </a>
              )}
            </div>
          )}
        </div>
      )}

      {/* METIS — live chat with the cognitive layer + repo/docs links. */}
      {node.id === 'metis' && (
        <>
          <MetisChat themeColor={themeColor} status={node.status} />
          {node.links && Object.keys(node.links).length > 0 && (
            <div className="mb-4" onClick={(e) => e.stopPropagation()}>
              <div className="text-[10px] font-mono uppercase tracking-wider text-white/40 mb-2">
                {t('nodeDetail.links', undefined, 'Links')}
              </div>
              <div className="space-y-1.5">
                {node.links.landing && (
                  <a
                    href={node.links.landing}
                    target="_blank"
                    rel="noreferrer"
                    className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                    style={{ backgroundColor: themeColor + '1e', border: `1px solid ${themeColor}55`, color: themeColor }}
                  >
                    {t('metis.landing', undefined, '🌌 Interactive 3D + live cognition')} ↗
                  </a>
                )}
                {node.links.github && (
                  <a
                    href={node.links.github}
                    target="_blank"
                    rel="noreferrer"
                    className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                    style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
                  >
                    {t('nodeDetail.community.github')} ↗
                  </a>
                )}
                {node.links.docs && (
                  <a
                    href={node.links.docs}
                    target="_blank"
                    rel="noreferrer"
                    className="block px-3 py-2 rounded text-xs font-mono transition-colors hover:brightness-110"
                    style={{ backgroundColor: themeColor + '12', border: `1px solid ${themeColor}33`, color: themeColor }}
                  >
                    {t('metis.docs', undefined, 'Documentation')} ↗
                  </a>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* URL if present — clickable, opens in a new tab. */}
      {node.url && (
        <div className="mt-4 pt-3 border-t" style={{ borderColor: themeColor + '22' }}>
          <a
            href={node.url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-[10px] font-mono break-all transition-colors underline decoration-dotted underline-offset-2"
            style={{ color: themeColor }}
          >
            {node.url} ↗
          </a>
        </div>
      )}
    </div>
    </>
  );
}
