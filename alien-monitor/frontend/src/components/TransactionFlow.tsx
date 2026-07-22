import { useEffect, useRef, useState } from 'react';
import type { Transaction, TxEvent } from '../App';
import { useI18n } from '../i18n';

interface Props {
  transactions: Transaction[];
  events: TxEvent[];
  themeColor: string;
  mobile?: boolean;
}

export default function TransactionFlow({ transactions, events, themeColor, mobile = false }: Props) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(!mobile);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = 0;
    }
  }, [transactions.length, events.length]);

  // Check for funding items in events
  const fundingItems = events.filter((ev: any) => ev.type === 'funding_stream' || ev.source === 'external');

  // Merge and sort by time (newest first)
  const allItems = [
    ...transactions.map((tx) => ({ ...tx, _type: 'tx' as const })),
    ...events.map((ev) => ({ ...ev, _type: 'event' as const })),
  ].sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime()).slice(0, 15);

  if (!visible) {
    return (
      <button
        onClick={() => setVisible(true)}
        className="
          fixed z-20 glass-panel px-3 py-2 text-xs font-mono
          left-1/2 -translate-x-1/2 bottom-[calc(4.5rem+var(--safe-bottom))]
          md:left-auto md:translate-x-0 md:right-4 md:bottom-4
        "
        style={{ color: themeColor, borderColor: themeColor + '44' }}
      >
        {t('activity.show')} ({allItems.length})
      </button>
    );
  }

  return (
    <div
      className={`z-40 glass-panel animate-slide-up ${
        mobile
          ? 'fixed inset-x-0 bottom-0 w-full max-h-[min(50vh,360px)] rounded-t-2xl pb-[max(0.25rem,env(safe-area-inset-bottom))]'
          : 'absolute bottom-4 right-4 w-80'
      }`}
      style={{ borderColor: themeColor + '44' }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 border-b"
        style={{ borderColor: themeColor + '22' }}
      >
        <div className="flex items-center gap-2">
          <div
            className="w-1.5 h-1.5 rounded-full animate-pulse"
            style={{ backgroundColor: '#00ff88', boxShadow: '0 0 6px #00ff88' }}
          />
          <span className="text-[10px] font-mono uppercase tracking-wider" style={{ color: themeColor }}>
            {t('activity.title')}
          </span>
          <span className="text-[10px] font-mono text-white/30">
            {allItems.length}
          </span>
        </div>
        <button
          onClick={() => setVisible(false)}
          className="text-white/30 hover:text-white/60 text-sm leading-none w-8 h-8 flex items-center justify-center"
          aria-label={t('activity.collapse', undefined, 'Collapse')}
        >
          _
        </button>
      </div>

      {/* Items */}
      <div
        ref={listRef}
        className="overflow-y-auto"
        style={{ maxHeight: mobile ? 'min(38vh, 220px)' : '180px' }}
      >
        {allItems.map((item, i) => {
          const isTx = item._type === 'tx';
          const tx = isTx ? (item as Transaction & { _type: string }) : null;
          const ev = !isTx ? (item as TxEvent & { _type: string }) : null;

          return (
            <div
              key={item.id}
              className="tx-enter px-3 py-1.5 flex items-center gap-2 text-[10px] font-mono border-b"
              style={{
                borderColor: '#ffffff06',
                animationDelay: `${i * 30}ms`,
              }}
            >
              {/* Icon */}
              <span style={{ color: (item as any).source === 'external' ? '#ffdd00' : isTx ? '#ffdd00' : themeColor }}>
                {(item as any).source === 'external' ? '✦' : isTx ? '↓' : '●'}
              </span>

              {/* Content */}
              <div className="flex-1 min-w-0">
                {(item as any).source === 'external' ? (
                  <>
                    <span className="text-[#ffdd00] font-bold">{t('activity.external')}</span>
                    <span className="text-white/30 mx-1">→</span>
                    <span className="text-white/70">{t('activity.fundingTarget')}</span>
                  </>
                ) : isTx && tx ? (
                  <>
                    <span className="text-white/70">{tx.from}</span>
                    <span className="text-white/30 mx-1">→</span>
                    <span className="text-white/70">{tx.to}</span>
                  </>
                ) : ev ? (
                  <>
                    <span className="text-white/70">{ev.agent}</span>
                    <span className="text-white/40 mx-1">{ev.action}</span>
                    <span className="text-white/50">{ev.target}</span>
                  </>
                ) : null}
              </div>

              {/* Amount */}
              {item.amount > 0 && (
                <span
                  className="tabular-nums shrink-0"
                  style={{ color: (item as any).source === 'external' ? '#ffdd00' : item.amount > 5 ? '#00ff88' : '#ffffff50' }}
                >
                  ${item.amount.toFixed(2)}
                </span>
              )}

              {/* Token badge */}
              {item.token && (
                <span
                  className="text-[8px] px-1 rounded shrink-0"
                  style={{
                    backgroundColor: (item as any).source === 'external' ? '#ffdd0022' : themeColor + '18',
                    color: (item as any).source === 'external' ? '#ffdd00' : themeColor,
                    border: `1px solid ${(item as any).source === 'external' ? '#ffdd0044' : themeColor + '33'}`,
                  }}
                >
                  {item.token}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
