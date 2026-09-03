import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from './i18n';
import EcosystemGraph from './components/EcosystemGraph';
import EcosystemGraph2D from './components/EcosystemGraph2D';
import MetricsPanel from './components/MetricsPanel';
import NodeDetail from './components/NodeDetail';
import ArgusRun from './components/ArgusRun';
import AIAssistant from './components/AIAssistant';
import ReputationGraph from './components/ReputationGraph';
import TransactionFlow from './components/TransactionFlow';
import ControlBar from './components/ControlBar';
import CryptoNotice from './components/CryptoNotice';
import MobileDock, { type MobileSheet } from './components/MobileDock';
import { useIsMobile } from './hooks/useIsMobile';
import { apiUrl } from './api';
import { useMonitorState } from './hooks/useMonitorState';

export interface EcoNode {
  id: string;
  label: string;
  group: string;
  icon: string;
  description: string;
  metrics: Record<string, number>;
  status: 'active' | 'idle' | 'error' | 'unknown' | 'offline' | 'disabled';
  color?: string;
  position: { x: number; y: number; z: number };
  children?: { id: string; label: string; url?: string; category?: string }[];
  collaboration?: { id: string; label: string; role?: string; url?: string; repo?: string; active?: boolean };
  url?: string;
  community_links?: Record<string, string>;
  dioscuri_live?: {
    version?: string;
    uptime_sec?: number;
    dry_run?: boolean;
    telegram?: boolean;
    discord?: boolean;
    theoros_active?: boolean;
    kb_chunks?: number;
    kb_repos?: number;
    kb_last_sync?: string | null;
    kb_sync_ok?: boolean;
    social?: {
      discord_members?: number;
      telegram_members?: number;
      twitter_followers?: number;
      cached_at?: string | null;
      stale?: boolean;
    };
  };
  helios_live?: {
    version?: string;
    uptime_sec?: number;
    dry_run?: boolean;
    queue_pending?: number;
    subscribers?: number;
    views?: number;
    videos?: number;
    cached_at?: string | null;
    stale?: boolean;
    channel_title?: string;
  };
  youtube_url?: string;
  links?: Record<string, string>;
  chat?: boolean;
  metis_live?: {
    version?: string;
    service?: string;
    cluster_nodes?: number;
    cluster?: { id?: string; url?: string; status?: string; healthy?: boolean }[];
    knowledge_entries?: number;
    open_circuit_breakers?: number;
  };
  skopos_live?: {
    version?: string;
    database?: string;
    log_parsers?: string[];
    servers_monitored?: number;
    requests_total?: number;
    security_score?: number;
  };
  argus_live?: {
    economy?: string;
    mode?: string;
    model?: string;
    version?: string;
    uptime_sec?: number;
    wallet?: string;
  };
  gaia_live?: {
    version?: string;
    service?: string;
    device_count?: number;
    online?: number;
    live_relays?: number;
    simulated?: boolean;
    devices?: {
      id: string;
      model?: string;
      site?: string;
      firmware?: string;
      fields?: { name: string; unit?: string }[];
      online?: boolean;
      fault?: string;
      readings_recorded?: number;
      source?: string | null;
      live?: boolean;
    }[];
  };
  onchain?: {
    network?: string;
    chain_id?: number;
    address?: string;
    explorer?: string;
    kind?: string;
    mock?: boolean;
  };
}

export interface EcoLink {
  source: string;
  target: string;
  label: string;
}

export interface TxEvent {
  id: string;
  ts: string;
  agent: string;
  action: string;
  target: string;
  amount: number;
  token: string;
}

export interface Transaction {
  id: string;
  from: string;
  to: string;
  amount: number;
  token: string;
  ts: string;
}

export interface EcosystemState {
  tick: number;
  ts: string;
  nodes: EcoNode[];
  links: EcoLink[];
  events: TxEvent[];
  transactions: Transaction[];
  channels: { id: string; agent: string; amount: number; token: string; status: string; ts: string }[];
  summary: {
    total_invocations_24h: number;
    total_volume_usd: number;
    active_channels: number;
    tvl_usd: number;
    agents_online: number;
    apps_online: number;
    tps_solana: number;
    gas_gwei: number;
    block_number?: number;
    onchain_tx_count?: number;
    mode: string;
    tick: number;
    blockchain_ready?: boolean;
    products_created?: number;
    entities_total?: number;
    evm_rpc?: string;
    usdt_contract?: string;
    scenario_phase?: string;
  };
  scenario?: {
    phase: string;
    phase_progress: number;
    phase_color: string;
    tick_count: number;
    funding_total: number;
    hub_count: number;
    buyer_rounds: number;
  };
  funding_events?: Array<{
    id: string;
    amount: number;
    token: string;
    source: string;
    tx_hash: string;
    ts: string;
    total_funding: number;
    round: number;
  }>;
  layer_errors?: string[];
}

type MonitorMode = 'test' | 'real' | 'universe';

function isMonitorMode(v: string): v is MonitorMode {
  return v === 'test' || v === 'real' || v === 'universe';
}

export default function App() {
  const { t } = useI18n();
  const isMobile = useIsMobile();
  const [mode, setMode] = useState<MonitorMode | null>(null);
  const [selectedNode, setSelectedNode] = useState<EcoNode | null>(null);
  const [showAI, setShowAI] = useState(false);
  const [showReputation, setShowReputation] = useState(false);
  const [showTx, setShowTx] = useState(true);
  const [mobileSheet, setMobileSheet] = useState<MobileSheet>('none');
  const [theme, setTheme] = useState<'cyan' | 'magenta' | 'green'>('cyan');
  const [pulseIntensity, setPulseIntensity] = useState(1.0);
  // Ecosystem crypto switch (server config) — drives the "blockchain disabled" badge.
  const [cryptoEnabled, setCryptoEnabled] = useState<boolean | null>(null);

  const { state, connectionError } = useMonitorState(mode);
  const graphKey = mode ?? 'loading';
  // 2D emergency map only with ?safe=1 — same full 3D path for Chrome, Samsung Internet, etc.
  const show2dGraph =
    typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).get('safe') === '1'
    && !!state?.nodes?.length;

  // Sync UI mode with server default (ALIEN_MODE) once — never override user toggles via polling.
  useEffect(() => {
    fetch(apiUrl('/api/health'))
      .then((r) => r.json())
      .then((d) => {
        if (typeof d?.crypto_enabled === 'boolean') setCryptoEnabled(d.crypto_enabled);
        if (d?.mode && isMonitorMode(d.mode)) {
          setMode(d.mode);
        } else {
          setMode('universe');
        }
      })
      .catch(() => setMode('universe'));
  }, []);

  const handleNodeClick = useCallback(
    (node: EcoNode) => {
      setSelectedNode(node);
      if (isMobile) {
        setMobileSheet('node');
        setShowAI(false);
        setShowReputation(false);
      }
    },
    [isMobile],
  );

  const focusNodeById = useCallback(
    (nodeId: string) => {
      const node = state?.nodes?.find((n) => n.id === nodeId);
      if (!node) return;
      setSelectedNode(node);
      if (isMobile) {
        setMobileSheet('node');
      }
    },
    [state?.nodes, isMobile],
  );

  useEffect(() => {
    if (!state?.nodes?.length) return;
    const params = new URLSearchParams(window.location.search);
    const nodeId = params.get('node');
    if (nodeId) focusNodeById(nodeId);
  }, [state?.nodes, focusNodeById]);

  const handleCloseNode = useCallback(() => {
    setSelectedNode(null);
    setMobileSheet((s) => (s === 'node' ? 'none' : s));
  }, []);

  const handleToggleAI = useCallback(() => {
    setShowAI((prev) => {
      const next = !prev;
      if (next) {
        setShowReputation(false); // mutually exclusive — shares the AI panel anchor
        if (isMobile) {
          setMobileSheet('ai');
          setShowTx(false);
        }
      }
      return next;
    });
  }, [isMobile]);

  const handleToggleReputation = useCallback(() => {
    setShowReputation((prev) => {
      const next = !prev;
      if (next) {
        setShowAI(false); // mutually exclusive — shares the AI panel anchor
        if (isMobile) {
          setMobileSheet('reputation');
          setShowTx(false);
        }
      } else if (isMobile) {
        setMobileSheet((s) => (s === 'reputation' ? 'none' : s));
      }
      return next;
    });
  }, [isMobile]);

  const handleToggleTx = useCallback(() => {
    setShowTx((prev) => {
      const next = !prev;
      if (isMobile && next) {
        setMobileSheet('tx');
        setShowAI(false);
        setShowReputation(false);
      }
      return next;
    });
  }, [isMobile]);

  const handleMobileSheet = useCallback(
    (sheet: MobileSheet) => {
      setMobileSheet(sheet);
      if (sheet === 'none') {
        setShowAI(false);
        setShowReputation(false);
        setShowTx(false);
        return;
      }
      if (sheet === 'ai') {
        setShowAI(true);
        setShowReputation(false);
        setShowTx(false);
        return;
      }
      if (sheet === 'reputation') {
        setShowReputation(true);
        setShowAI(false);
        setShowTx(false);
        return;
      }
      if (sheet === 'tx') {
        setShowTx(true);
        setShowAI(false);
        setShowReputation(false);
        return;
      }
      if (sheet === 'node' && !selectedNode) {
        setMobileSheet('none');
      }
      if (sheet === 'controls') {
        setShowAI(false);
        setShowReputation(false);
        setShowTx(false);
      }
    },
    [selectedNode],
  );

  const handleModeChange = useCallback((newMode: MonitorMode) => {
    setMode(newMode);
  }, []);

  const themeColor = {
    cyan: '#00f0ff',
    magenta: '#ff00ff',
    green: '#00ff88',
  }[theme];

  return (
    <div className="relative w-full min-h-[100dvh] h-[100dvh] bg-[#0a0a0f] overflow-hidden">
      {/* Grid background */}
      <div className="absolute inset-0 grid-bg opacity-40 pointer-events-none" />

      {/* Scan line effect */}
      <div className="scan-line" />

      {state?.layer_errors?.some((e) => /prometheus/i.test(e)) && (
        <div
          className="absolute top-2 left-1/2 z-30 max-w-[92vw] -translate-x-1/2 rounded border border-amber-500/40 bg-amber-950/80 px-3 py-1.5 text-center text-[11px] font-mono text-amber-200/90 md:top-3 md:text-xs"
          role="status"
        >
          {t('monitor.prometheusDegraded')}
        </div>
      )}

      {!mode && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center pointer-events-none gap-3">
          <div className="w-10 h-10 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" />
          <span className="text-xs font-mono text-white/50 uppercase tracking-widest">{t('connecting')}</span>
        </div>
      )}

      {mode && !state && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center pointer-events-none gap-3 px-6 text-center">
          <div
            className="w-10 h-10 rounded-full border-2 border-t-transparent animate-spin"
            style={{ borderColor: `${themeColor}55`, borderTopColor: themeColor }}
          />
          <span className="text-sm font-mono opacity-70">{t('app.connecting')}</span>
          {connectionError === 'auth' && (
            <span className="text-xs font-mono text-amber-200/90 max-w-md leading-relaxed">
              {t('app.connectFailedAuth')}
            </span>
          )}
          {connectionError === 'network' && (
            <span className="text-xs font-mono text-amber-200/90 max-w-md leading-relaxed">
              {t('app.connectFailedNetwork')}
            </span>
          )}
        </div>
      )}

      {/* Main 3D graph — always visible; remount on mode/tick avoids stale WebGL after TEST/LIVE/UNI switch */}
      <div className="absolute inset-0">
        {!show2dGraph && (
          <EcosystemGraph
            key={graphKey}
            state={state}
            onNodeClick={handleNodeClick}
            focusNodeId={selectedNode?.id ?? null}
            themeColor={themeColor}
            pulseIntensity={pulseIntensity}
            fundingEvents={state?.funding_events ?? null}
            scenario={state?.scenario ?? null}
          />
        )}
        {show2dGraph && (
          <EcosystemGraph2D state={state} onNodeClick={handleNodeClick} themeColor={themeColor} />
        )}
      </div>

      {/* Top metrics bar */}
      <MetricsPanel
        summary={state?.summary ?? null}
        scenario={state?.scenario ?? null}
        mode={mode ?? 'universe'}
        themeColor={themeColor}
      />

      {/* Mobile backdrop for sheets */}
      {isMobile && mobileSheet !== 'none' && (
        <button
          type="button"
          className="md:hidden fixed inset-0 z-30 bg-black/55 backdrop-blur-[2px]"
          aria-label={t('mobile.closeSheet')}
          onClick={() => handleMobileSheet('none')}
        />
      )}

      {/* Control bar — desktop top-right; mobile settings sheet */}
      {mode && (
      <ControlBar
        mode={mode}
        onModeChange={handleModeChange}
        theme={theme}
        onThemeChange={setTheme}
        showAI={showAI}
        onToggleAI={handleToggleAI}
        showReputation={showReputation}
        onToggleReputation={handleToggleReputation}
        showTx={showTx}
        onToggleTx={handleToggleTx}
        pulseIntensity={pulseIntensity}
        onPulseChange={setPulseIntensity}
        themeColor={themeColor}
        mobileOpen={isMobile && mobileSheet === 'controls'}
        onMobileClose={() => handleMobileSheet('none')}
      />
      )}

      {/* Node detail panel */}
      {selectedNode && (!isMobile || mobileSheet === 'node') && (
        selectedNode.id === 'argus' || selectedNode.group === 'argus' ? (
          <ArgusRun
            node={selectedNode}
            mode={mode ?? 'universe'}
            themeColor={themeColor}
            onClose={handleCloseNode}
            mobile={isMobile}
          />
        ) : (
          <NodeDetail
            node={selectedNode}
            onClose={handleCloseNode}
            themeColor={themeColor}
            mobile={isMobile}
          />
        )
      )}

      {/* AI Assistant */}
      {showAI && (!isMobile || mobileSheet === 'ai') && (
        <AIAssistant
          themeColor={themeColor}
          onClose={() => {
            setShowAI(false);
            setMobileSheet((s) => (s === 'ai' ? 'none' : s));
          }}
          monitorState={state}
          selectedNodeId={selectedNode?.id ?? null}
          onFocusNode={focusNodeById}
          mobile={isMobile}
        />
      )}

      {/* Reputation graph (LUMEN EigenTrust/PageRank over the live ecosystem) */}
      {showReputation && (!isMobile || mobileSheet === 'reputation') && (
        <ReputationGraph
          themeColor={themeColor}
          onClose={() => {
            setShowReputation(false);
            setMobileSheet((s) => (s === 'reputation' ? 'none' : s));
          }}
          monitorState={state}
          mode={mode ?? 'universe'}
          mobile={isMobile}
        />
      )}

      {/* Transaction flow */}
      {showTx && state && (!isMobile || mobileSheet === 'tx') && (
        <TransactionFlow
          transactions={state.transactions}
          events={state.events}
          themeColor={themeColor}
          mobile={isMobile}
        />
      )}

      {isMobile && (
        <MobileDock
          sheet={mobileSheet}
          onSheetChange={handleMobileSheet}
          hasNode={!!selectedNode}
          showAI={showAI}
          showReputation={showReputation}
          showTx={showTx}
          themeColor={themeColor}
        />
      )}

      {/* Holographic corner decorations — desktop only */}
      <CornerDecorations themeColor={themeColor} />

      {/* Mode indicator */}
      {mode && (
      <div className="absolute bottom-[4.75rem] left-2 z-10 flex items-center gap-2 md:bottom-4 md:left-4 max-w-[55vw]">
        <div
          className="w-2 h-2 rounded-full animate-pulse"
          style={{
            backgroundColor: mode === 'test' ? '#ffdd00' : mode === 'universe' ? state?.scenario?.phase_color ?? '#8844ff' : '#00ff88',
            boxShadow: `0 0 8px ${mode === 'test' ? '#ffdd00' : mode === 'universe' ? state?.scenario?.phase_color ?? '#8844ff' : '#00ff88'}`,
          }}
        />
        <span className="text-xs font-mono opacity-60">
          {mode === 'test'
            ? t('mode.footerSimulation')
            : mode === 'universe'
              ? t('mode.footerUniverse', {
                  phase: t(
                    `scenario.${state?.scenario?.phase ?? 'BOOTSTRAP'}`,
                    undefined,
                    state?.scenario?.phase ?? 'BOOTSTRAP',
                  ),
                })
              : t('mode.footerLive')}
        </span>
        {state && (
          <span className="text-xs font-mono opacity-40 ml-2">
            {t('tick', { n: state.tick })}
          </span>
        )}
      </div>
      )}

      {/* Honest-state badge: LIVE + crypto OFF → real blockchain disabled in settings */}
      <CryptoNotice mode={mode} cryptoEnabled={cryptoEnabled} themeColor={themeColor} />
    </div>
  );
}

function CornerDecorations({ themeColor }: { themeColor: string }) {
  return (
    <>
      {/* Top-left corner */}
      <svg
        className="absolute top-0 left-0 w-32 h-32 pointer-events-none z-10 opacity-30 hidden md:block"
        viewBox="0 0 100 100"
      >
        <line x1="0" y1="2" x2="60" y2="2" stroke={themeColor} strokeWidth="1" />
        <line x1="2" y1="0" x2="2" y2="60" stroke={themeColor} strokeWidth="1" />
        <circle cx="8" cy="8" r="3" fill="none" stroke={themeColor} strokeWidth="0.5" opacity="0.5" />
      </svg>
      {/* Top-right corner */}
      <svg
        className="absolute top-0 right-0 w-32 h-32 pointer-events-none z-10 opacity-30 hidden md:block"
        viewBox="0 0 100 100"
      >
        <line x1="40" y1="2" x2="100" y2="2" stroke={themeColor} strokeWidth="1" />
        <line x1="98" y1="0" x2="98" y2="60" stroke={themeColor} strokeWidth="1" />
        <circle cx="92" cy="8" r="3" fill="none" stroke={themeColor} strokeWidth="0.5" opacity="0.5" />
      </svg>
      {/* Bottom-right corner */}
      <svg
        className="absolute bottom-0 right-0 w-32 h-32 pointer-events-none z-10 opacity-30 hidden md:block"
        viewBox="0 0 100 100"
      >
        <line x1="40" y1="98" x2="100" y2="98" stroke={themeColor} strokeWidth="1" />
        <line x1="98" y1="40" x2="98" y2="100" stroke={themeColor} strokeWidth="1" />
        <circle cx="92" cy="92" r="3" fill="none" stroke={themeColor} strokeWidth="0.5" opacity="0.5" />
      </svg>
    </>
  );
}
