import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { EcoNode } from '../App';
import { useI18n } from '../i18n';

// One beat of an Argus run. In TEST this is scripted; in real/universe it is
// filled from the node's live `argus_run` (WardenVerdict, oracle calls, invoke/settle).
type BeatKind = 'oracle' | 'warden' | 'hire' | 'receipt';
type BeatStatus = 'ok' | 'blocked' | 'paid' | 'sealed';

interface Beat {
  kind: BeatKind;
  title: string;
  detail: string;
  meta: string;
  status: BeatStatus;
}

export interface ArgusRunData {
  id: string;
  goal: string;
  beats: Beat[];
  spendUsd: number;
  receiptHash: string;
  signer: string;
  verifyUrl?: string; // basescan tx in LIVE
}

// Scripted demo — plays with no live data (TEST / fallback). Real runs override
// this from the clicked node's `argus_run` field.
const DEMO_RUN: ArgusRunData = {
  id: 'run_demo_7f3a',
  goal: 'Draw a fair winner from a verified random seed — and don’t get owned doing it.',
  beats: [
    {
      kind: 'oracle',
      title: 'Called a verifiable oracle',
      detail: 'platon.random@v1 → Ed25519-signed, unbiasable randomness + proof',
      meta: '0x9f3c…a1 · proof ✓ · $0.004',
      status: 'ok',
    },
    {
      kind: 'warden',
      title: 'WARDEN refused a malicious tool',
      detail: 'fs-helper exposed an “exfiltrate_env” tool with a hidden-unicode injection in its description',
      meta: 'gate: static-scan · TOOL_DEF_INJECTION · severity high',
      status: 'blocked',
    },
    {
      kind: 'hire',
      title: 'Hired another agent',
      detail: 'discover → open USDC channel → invoke translate@v2 → settle (reputation-checked first)',
      meta: 'TranslatorPro · LUMEN 0.81 · $0.012 · receipt ✓',
      status: 'paid',
    },
    {
      kind: 'receipt',
      title: 'Sealed a verifiable receipt',
      detail: 'Every step is signed. Verify the proofs — don’t trust the agent.',
      meta: 'sha256 0x4b…e9 · signer 0x12…35',
      status: 'sealed',
    },
  ],
  spendUsd: 0.016,
  receiptHash: '0x4b9e…e9',
  signer: '0x12…35',
};

const ICON: Record<BeatKind, string> = { oracle: '\u{1F52E}', warden: '\u{1F6E1}️', hire: '\u{1F91D}', receipt: '\u{1F9FE}' };
const STATUS_COLOR: Record<BeatStatus, string> = {
  ok: '#00f0ff',
  blocked: '#ff3b6b',
  paid: '#00ff88',
  sealed: '#ffcc33',
};

function truncAddr(s: string): string {
  return s.length > 13 ? `${s.slice(0, 6)}…${s.slice(-4)}` : s;
}

interface Props {
  node: EcoNode;
  mode: 'test' | 'real' | 'universe';
  themeColor: string;
  onClose: () => void;
  mobile?: boolean;
}

export default function ArgusRun({ node, mode, themeColor, onClose, mobile = false }: Props) {
  const { t } = useI18n();
  const live = (node as unknown as { argus_run?: ArgusRunData }).argus_run;
  const isTest = mode === 'test';
  const run: ArgusRunData | null = live ?? (isTest ? DEMO_RUN : null);
  const isDemo = isTest && !live;
  const waitingLive = !isTest && !live;
  const liveMeta = node.argus_live;
  const economyOn = liveMeta?.economy === 'on';
  const isOffline = node.status === 'offline' || node.status === 'error';

  const [step, setStep] = useState(0);
  const [nonce, setNonce] = useState(0);
  const beats = run?.beats ?? [];
  const done = run ? step > beats.length : false;

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  useEffect(() => {
    setStep(0);
    if (!run) return;
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setStep(i);
      if (i > beats.length) clearInterval(id);
    }, 1050);
    return () => clearInterval(id);
  }, [node.id, run?.id, nonce, beats.length]);

  const modeBadge = economyOn
    ? t('argus.economyOn', undefined, 'ECONOMY · Base mainnet')
    : mode === 'test'
      ? t('argus.modeTest', undefined, 'TEST · simulated')
      : mode === 'real'
        ? t('argus.modeLive', undefined, 'LIVE · Base mainnet')
        : t('argus.modeUni', undefined, 'UNI · local chain');
  const modeColor = economyOn ? '#00ff88' : mode === 'test' ? '#ffdd00' : mode === 'real' ? '#00ff88' : '#8844ff';

  return (
    <>
      {mobile && (
        <button type="button" className="mobile-backdrop" aria-label={t('mobile.closeSheet')} onClick={onClose} />
      )}
      <div
        className={`z-40 glass-panel p-4 md:p-5 animate-slide-in overflow-y-auto ${
          mobile
            ? 'fixed inset-x-0 bottom-0 mobile-sheet max-h-[min(80dvh,580px)]'
            : 'absolute left-4 top-24 w-[24rem] max-w-[calc(100vw-2rem)] max-h-[calc(100vh-8rem)]'
        }`}
        style={{
          borderColor: themeColor + '55',
          boxShadow: `0 0 30px rgba(0,0,0,0.5), 0 0 18px ${themeColor}22`,
        }}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xl leading-none shrink-0" aria-hidden>{'\u{1F441}️'}</span>
            <div className="min-w-0">
              <h3 className="text-sm font-bold truncate" style={{ color: themeColor }}>
                {node.label || t('argus.title', undefined, 'Argus — Verifiable Run')}
              </h3>
              <div className="text-[10px] font-mono text-white/40">
                {t('argus.tagline', undefined, "Don’t trust your agent. Verify it.")}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <span
              className="text-[8px] font-mono uppercase px-1.5 py-0.5 rounded tracking-wider"
              style={{ color: modeColor, backgroundColor: modeColor + '1a', border: `1px solid ${modeColor}44` }}
            >
              {modeBadge}
            </span>
            <button
              onClick={onClose}
              className="text-white/40 hover:text-white text-2xl leading-none w-8 h-8 flex items-center justify-center"
              aria-label={t('mobile.closeSheet')}
            >
              {'×'}
            </button>
          </div>
        </div>

        {/* Live agent + on-chain wallet (polled from GET /health) */}
        {(liveMeta || node.onchain || isOffline) && (
          <div
            className="mb-3 rounded-xl p-3 space-y-2"
            style={{ backgroundColor: themeColor + '0a', border: `1px solid ${themeColor}22` }}
          >
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <span className="text-[10px] font-mono uppercase tracking-wider text-white/40">
                {t('argus.liveStatus', undefined, 'Live agent')}
              </span>
              <span
                className="text-[8px] font-mono uppercase px-1.5 py-0.5 rounded tracking-wider"
                style={{
                  color: isOffline ? '#ff3b6b' : economyOn ? '#00ff88' : '#ffaa00',
                  backgroundColor: (isOffline ? '#ff3b6b' : economyOn ? '#00ff88' : '#ffaa00') + '1a',
                  border: `1px solid ${(isOffline ? '#ff3b6b' : economyOn ? '#00ff88' : '#ffaa00')}44`,
                }}
              >
                {isOffline
                  ? t('argus.offline', undefined, 'offline')
                  : economyOn
                    ? t('argus.economyOnShort', undefined, 'economy on')
                    : t('argus.economyOff', undefined, 'economy off')}
              </span>
            </div>
            {liveMeta?.uptime_sec != null && liveMeta.uptime_sec > 0 && (
              <div className="flex items-center justify-between gap-2 text-[10px] font-mono">
                <span className="text-white/40 uppercase">{t('argus.uptime', undefined, 'Uptime')}</span>
                <span className="text-white/70 tabular-nums">{liveMeta.uptime_sec}s</span>
              </div>
            )}
            {liveMeta?.model && (
              <div className="flex items-center justify-between gap-2 text-[10px] font-mono">
                <span className="text-white/40 uppercase">Model</span>
                <span className="text-white/70 truncate">{liveMeta.model}</span>
              </div>
            )}
            {node.onchain && (
              <>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-mono text-white/40 uppercase shrink-0">
                    {t('onchain.network', undefined, 'Network')}
                  </span>
                  <span className="flex items-center gap-1.5 min-w-0">
                    <span className="text-xs font-mono font-bold truncate" style={{ color: themeColor }}>
                      {node.onchain.network}
                    </span>
                    {node.onchain.chain_id != null && (
                      <span className="text-[9px] font-mono text-white/40 shrink-0">#{node.onchain.chain_id}</span>
                    )}
                  </span>
                </div>
                {node.onchain.address && (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-mono text-white/40 uppercase shrink-0">
                      {t('onchain.wallet', undefined, 'Wallet')}
                    </span>
                    {node.onchain.explorer ? (
                      <a
                        href={node.onchain.explorer}
                        target="_blank"
                        rel="noopener"
                        className="text-xs font-mono underline decoration-dotted underline-offset-2 text-right break-all"
                        style={{ color: themeColor }}
                        title={node.onchain.address}
                      >
                        {truncAddr(node.onchain.address)} ↗
                      </a>
                    ) : (
                      <span className="text-xs font-mono text-white/70 text-right break-all" title={node.onchain.address}>
                        {truncAddr(node.onchain.address)}
                      </span>
                    )}
                  </div>
                )}
              </>
            )}
            {node.url && (
              <a
                href={node.url}
                target="_blank"
                rel="noopener"
                className="block text-center text-[10px] font-mono uppercase tracking-wider py-1.5 rounded-lg mt-1"
                style={{ color: themeColor, border: `1px solid ${themeColor}33`, backgroundColor: themeColor + '0d' }}
              >
                {t('argus.openArena', undefined, 'Open Agent Arena')} ↗
              </a>
            )}
          </div>
        )}

        {/* Goal */}
        {run ? (
          <div className="text-[11px] text-white/65 mb-3 leading-snug">
            <span className="text-white/35 font-mono">{t('argus.goal', undefined, 'Goal')}: </span>
            {run.goal}
          </div>
        ) : null}
        {waitingLive && (
          <div
            className="text-[11px] font-mono text-amber-300/90 mb-3 rounded-xl p-3 leading-snug"
            style={{ backgroundColor: '#ffcc3314', border: '1px solid #ffcc3344' }}
          >
            {t(
              'argus.waitingLive',
              undefined,
              'No live run streamed yet. Complete a task in Argus (Telegram, Arena, or POST /ask) — it will appear here within ~2 minutes.',
            )}
          </div>
        )}
        {isDemo && (
          <div className="text-[10px] font-mono text-amber-300/80 mb-3">
            {t('argus.demoRun', undefined, 'TEST mode — scripted demo run (not a live agent trace).')}
          </div>
        )}

        {/* Beats */}
        <div className="flex flex-col gap-2">
          {beats.map((b, idx) => {
            const shown = idx < step;
            const color = STATUS_COLOR[b.status];
            return (
              <AnimatePresence key={idx}>
                {shown && (
                  <motion.div
                    initial={{ opacity: 0, x: -14 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 22 }}
                    className="relative flex items-start gap-2.5 rounded-xl p-2.5"
                    style={{
                      background: `linear-gradient(90deg, ${color}14, transparent)`,
                      border: `1px solid ${color}33`,
                    }}
                  >
                    <motion.div
                      initial={{ scale: 0.6 }}
                      animate={b.status === 'blocked'
                        ? { scale: [1, 1.12, 1] }
                        : { scale: 1, boxShadow: [`0 0 0px ${color}00`, `0 0 14px ${color}aa`, `0 0 6px ${color}55`] }}
                      transition={b.status === 'blocked'
                        ? { repeat: Infinity, duration: 1.1 }
                        : { duration: 0.9 }}
                      className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-base"
                      style={{ backgroundColor: color + '1f', border: `1px solid ${color}55` }}
                      aria-hidden
                    >
                      {ICON[b.kind]}
                    </motion.div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-mono font-bold" style={{ color }}>{b.title}</span>
                        {b.status === 'blocked' && (
                          <span className="text-[8px] font-mono font-black px-1.5 py-0.5 rounded" style={{ color: '#fff', backgroundColor: color }}>
                            {t('argus.blocked', undefined, 'BLOCKED')}
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-white/60 mt-0.5 leading-snug">{b.detail}</div>
                      <div className="text-[9px] font-mono text-white/35 mt-1 break-all">{b.meta}</div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            );
          })}
        </div>

        {/* Receipt + verify */}
        <AnimatePresence>
          {run && done && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-3 rounded-xl p-3"
              style={{ background: `linear-gradient(135deg, ${STATUS_COLOR.sealed}1a, ${themeColor}10)`, border: `1px solid ${STATUS_COLOR.sealed}55` }}
            >
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="min-w-0">
                  <div className="text-xs font-mono font-bold flex items-center gap-1.5" style={{ color: STATUS_COLOR.sealed }}>
                    <span aria-hidden>{'\u{1F9FE}'}</span>{t('argus.receiptTitle', undefined, 'Argus Receipt — sealed')}
                  </div>
                  <div className="text-[9px] font-mono text-white/40 mt-0.5 break-all">
                    {t('argus.receiptHash', undefined, 'sha256')} {run.receiptHash} · {t('argus.signer', undefined, 'signer')} {run.signer}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <div className="text-right">
                    <div className="text-[9px] font-mono text-white/35 uppercase">{t('argus.spend', undefined, 'spend')}</div>
                    <div className="text-sm font-mono font-bold tabular-nums" style={{ color: '#00ff88' }}>${run.spendUsd.toFixed(3)}</div>
                  </div>
                  <a
                    href={run.verifyUrl ?? '#'}
                    target={run.verifyUrl ? '_blank' : undefined}
                    rel="noopener"
                    onClick={(e) => { if (!run.verifyUrl) e.preventDefault(); }}
                    className="px-3 py-1.5 rounded-lg text-[11px] font-mono font-bold uppercase tracking-wider"
                    style={{ color: '#04110a', backgroundColor: STATUS_COLOR.sealed, boxShadow: `0 0 14px ${STATUS_COLOR.sealed}66` }}
                    title={t('argus.verifyHint', undefined, 'Re-checks every signature, oracle proof and payment — independently.')}
                  >
                    {'✓'} {t('argus.verify', undefined, 'Verify')}
                  </a>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Footer */}
        <div className="flex items-center justify-between mt-3">
          <div className="text-[9px] font-mono text-white/30">
            {!run
              ? t('argus.waiting', undefined, 'waiting for live run')
              : step <= beats.length
                ? t('argus.running', { n: Math.min(step, beats.length), total: beats.length }, `step ${Math.min(step, beats.length)}/${beats.length}`)
                : t('argus.complete', undefined, 'run complete — verifiable')}
          </div>
          {run ? (
            <button
              onClick={() => setNonce((n) => n + 1)}
              className="glass-panel px-3 py-1.5 text-[10px] font-mono uppercase rounded-lg"
              style={{ color: themeColor, borderColor: themeColor + '44' }}
            >
              {'↻'} {t('argus.replay', undefined, 'Replay')}
            </button>
          ) : null}
        </div>
      </div>
    </>
  );
}
