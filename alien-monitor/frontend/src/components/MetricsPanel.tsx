import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';

interface Summary {
  total_invocations_24h: number;
  total_volume_usd: number;
  active_channels: number;
  tvl_usd: number;
  agents_online: number;
  apps_online: number;
  tps_solana: number;
  gas_gwei: number;
  mode: string;
  tick: number;
  blockchain_ready?: boolean;
  block_number?: number;
  onchain_tx_count?: number;
  scenario_phase?: string;
}

interface ScenarioData {
  phase: string;
  phase_progress: number;
  phase_color: string;
  tick_count: number;
  funding_total: number;
  hub_count: number;
  buyer_rounds: number;
}

interface Props {
  summary: Summary | null;
  scenario: ScenarioData | null;
  mode: string;
  themeColor: string;
}

export default function MetricsPanel({ summary, scenario, mode, themeColor }: Props) {
  const { t } = useI18n();
  const [animatedValues, setAnimatedValues] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!summary) return;
    const targets: Record<string, number> = {
      invocations: summary.total_invocations_24h,
      volume: summary.total_volume_usd,
      channels: summary.active_channels,
      tvl: summary.tvl_usd,
      agents: summary.agents_online,
      apps: summary.apps_online,
    };

    // Animate toward targets
    const interval = setInterval(() => {
      setAnimatedValues((prev) => {
        const next: Record<string, number> = {};
        for (const [key, target] of Object.entries(targets)) {
          const current = prev[key] ?? target * 0.7;
          next[key] = current + (target - current) * 0.15;
        }
        return next;
      });
    }, 120);

    return () => clearInterval(interval);
  }, [summary]);

  if (!summary) {
    return (
      <div className="absolute top-0 left-0 right-0 z-20 p-2 pt-[max(0.5rem,env(safe-area-inset-top))] md:p-4">
        <div className="glass-panel px-4 py-2 md:px-6 md:py-3 flex items-center justify-center">
          <span className="text-sm font-mono opacity-60">{t('app.connecting')}</span>
        </div>
      </div>
    );
  }

  const fmt = (v: number | undefined) => {
    if (v === undefined) return '--';
    if (v >= 1000000) return `${(v / 1000000).toFixed(1)}M`;
    if (v >= 1000) return `${(v / 1000).toFixed(1)}K`;
    return v.toFixed(0);
  };

  const fmtUSD = (v: number | undefined) => {
    if (v === undefined) return '$--';
    if (v >= 1000000) return `$${(v / 1000000).toFixed(2)}M`;
    if (v >= 1000) return `$${(v / 1000).toFixed(1)}K`;
    return `$${v.toFixed(0)}`;
  };

  const metrics = [
    { label: t('metrics.invocations'), value: fmt(animatedValues.invocations), key: 'invocations' },
    { label: t('metrics.volume24h'), value: fmtUSD(animatedValues.volume), key: 'volume' },
    { label: t('metrics.channels'), value: fmt(animatedValues.channels), key: 'channels' },
    { label: t('metrics.tvl'), value: fmtUSD(animatedValues.tvl), key: 'tvl' },
    { label: t('metrics.agents'), value: fmt(animatedValues.agents), key: 'agents' },
    { label: t('metrics.apps'), value: fmt(animatedValues.apps), key: 'apps' },
  ];

  const metricCell = (m: { label: string; value: string; key: string }) => (
    <div key={m.key} className="flex flex-col items-center min-w-[4.25rem] shrink-0 snap-start">
      <div
        className="text-base md:text-lg font-mono font-bold tabular-nums"
        style={{ color: themeColor }}
      >
        {m.value}
      </div>
      <div className="text-[9px] md:text-[10px] font-mono opacity-50 uppercase tracking-wider text-center leading-tight">
        {m.label}
      </div>
    </div>
  );

  return (
    <div className="absolute top-0 left-0 right-0 z-20 p-2 pt-[max(0.5rem,env(safe-area-inset-top))] md:p-4 flex justify-center pointer-events-none">
      <div className="glass-panel pointer-events-auto w-full max-w-[100vw] md:w-auto px-3 py-2 md:px-6 md:py-3 flex flex-col md:flex-row md:items-center gap-2 md:gap-8">
        {/* Title */}
        <div className="flex items-center justify-between gap-2 md:justify-start md:gap-3 md:mr-4 shrink-0 w-full md:w-auto">
          <div className="flex items-center gap-2 md:gap-3 min-w-0">
            <div
              className="text-lg md:text-xl shrink-0"
              style={{ color: themeColor, textShadow: `0 0 10px ${themeColor}` }}
            >
              &#x25C9;
            </div>
            <div className="min-w-0">
              <div className="text-xs md:text-sm font-semibold tracking-wider truncate" style={{ color: themeColor }}>
                {t('app.title')}
              </div>
              <div className="text-[9px] md:text-[10px] font-mono opacity-50 truncate">
                {mode === 'test'
                  ? t('mode.simulation')
                  : mode === 'universe'
                    ? t('mode.universe')
                    : t('mode.live')}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 md:hidden shrink-0">
            {(mode === 'universe' || mode === 'real') && summary.blockchain_ready ? (
              <>
                <MiniStat label={t('metrics.block')} value={`#${summary.block_number ?? '--'}`} color="#7b2fff" />
                <MiniStat label={t('metrics.onchainTx')} value={String(summary.onchain_tx_count ?? 0)} color="#00ff88" />
              </>
            ) : (
              <>
                <MiniStat
                  label={t('metrics.solanaTps')}
                  value={summary.tps_solana ? `${(summary.tps_solana / 1000).toFixed(1)}k` : '--'}
                  color="#ff6633"
                />
                <MiniStat label={t('metrics.ethGas')} value={String(summary.gas_gwei ?? '--')} color="#ffdd00" />
              </>
            )}
          </div>
        </div>

        {/* Metrics — horizontal scroll on mobile */}
        <div className="metrics-scroll flex items-center gap-4 md:gap-6 overflow-x-auto pb-0.5 -mx-1 px-1 snap-x snap-mandatory md:overflow-visible">
          {metrics.map(metricCell)}
        </div>

        {/* UNI scenario metrics */}
        {mode === 'universe' && scenario && (
          <div className="flex items-center gap-3 md:gap-4 md:pl-4 md:border-l border-[#1a2332] overflow-x-auto pb-0.5 snap-x md:overflow-visible shrink-0">
            <div className="flex flex-col items-center min-w-[60px]">
              <div className="text-sm font-mono font-bold" style={{ color: scenario.phase_color }}>
                {t(`scenario.${scenario.phase}`, undefined, scenario.phase)}
              </div>
              <div className="text-[10px] font-mono opacity-50">{t('metrics.phase')}</div>
            </div>
            <div className="flex flex-col items-center min-w-[60px]">
              <div className="text-sm font-mono font-bold text-[#ffdd00]">
                ${scenario.funding_total.toFixed(0)}
              </div>
              <div className="text-[10px] font-mono opacity-50">{t('metrics.funding')}</div>
            </div>
            <div className="flex flex-col items-center min-w-[60px]">
              <div className="text-sm font-mono font-bold text-[#00ff88]">
                {scenario.buyer_rounds}
              </div>
              <div className="text-[10px] font-mono opacity-50">{t('metrics.buyerRnd')}</div>
            </div>
            <div className="flex flex-col items-center min-w-[50px]">
              <div className="text-sm font-mono font-bold text-[#ff44ff]">
                {scenario.hub_count}
              </div>
              <div className="text-[10px] font-mono opacity-50">{t('metrics.hubs')}</div>
            </div>
            {/* Phase progress bar */}
            <div className="flex flex-col items-center min-w-[60px]">
              <div className="w-12 h-1.5 rounded-full bg-[#1a2332] overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${Math.round(scenario.phase_progress * 100)}%`,
                    backgroundColor: scenario.phase_color,
                  }}
                />
              </div>
              <div className="text-[10px] font-mono opacity-50">
                {Math.round(scenario.phase_progress * 100)}%
              </div>
            </div>
          </div>
        )}

        {/* Divider + TPS / Gas / Blockchain analytics */}
        <div className="flex items-center gap-3 md:gap-4 md:pl-4 md:border-l border-[#1a2332] overflow-x-auto pb-0.5 snap-x md:overflow-visible shrink-0">
          {(mode === 'universe' || mode === 'real') && summary.blockchain_ready ? (
            <>
              <div className="flex flex-col items-center">
                <div className="text-sm font-mono" style={{ color: themeColor }}>
                  #{summary.block_number?.toLocaleString() ?? '--'}
                </div>
                <div className="text-[10px] font-mono opacity-50">{t('metrics.block')}</div>
              </div>
              <div className="flex flex-col items-center">
                <div className="text-sm font-mono text-[#00ff88]">
                  {summary.onchain_tx_count ?? 0}
                </div>
                <div className="text-[10px] font-mono opacity-50">{t('metrics.onchainTx')}</div>
              </div>
              <div className="flex flex-col items-center">
                <div className="text-sm font-mono text-[#ffdd00]">
                  {summary.gas_gwei?.toLocaleString() ?? '--'}
                </div>
                <div className="text-[10px] font-mono opacity-50">{t('metrics.gasUsed')}</div>
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-col items-center">
                <div className="text-sm font-mono text-[#ff6633]">
                  {summary.tps_solana?.toLocaleString() ?? '--'}
                </div>
                <div className="text-[10px] font-mono opacity-50">{t('metrics.solanaTps')}</div>
              </div>
              <div className="flex flex-col items-center">
                <div className="text-sm font-mono text-[#ffdd00]">
                  {summary.gas_gwei ?? '--'} GWEI
                </div>
                <div className="text-[10px] font-mono opacity-50">{t('metrics.ethGas')}</div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex flex-col items-end">
      <div className="text-[11px] font-mono font-bold tabular-nums" style={{ color }}>
        {value}
      </div>
      <div className="text-[8px] font-mono opacity-40">{label}</div>
    </div>
  );
}
