import { useI18n } from '../i18n';

export type MobileSheet = 'none' | 'controls' | 'node' | 'ai' | 'reputation' | 'tx';

interface Props {
  sheet: MobileSheet;
  onSheetChange: (s: MobileSheet) => void;
  hasNode: boolean;
  showAI: boolean;
  showReputation: boolean;
  showTx: boolean;
  themeColor: string;
}

export default function MobileDock({
  sheet,
  onSheetChange,
  hasNode,
  showAI,
  showReputation,
  showTx,
  themeColor,
}: Props) {
  const { t } = useI18n();

  const toggle = (id: MobileSheet) => {
    onSheetChange(sheet === id ? 'none' : id);
  };

  const btn = (active: boolean) =>
    `flex flex-1 min-w-0 flex-col items-center justify-center gap-0.5 px-1 py-1.5 rounded-xl text-[10px] font-mono uppercase transition-all ${
      active ? 'text-black font-bold' : 'text-white/50'
    }`;

  return (
    <nav
      className="md:hidden fixed inset-x-0 bottom-0 z-50 px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-1 pointer-events-none"
      aria-label={t('mobile.dockLabel')}
    >
      <div
        className="glass-panel pointer-events-auto mx-auto flex max-w-lg items-center justify-around gap-1 rounded-2xl px-2 py-1.5"
        style={{ borderColor: themeColor + '33' }}
      >
        <button
          type="button"
          className={btn(sheet === 'none')}
          style={{
            backgroundColor: sheet === 'none' ? themeColor : 'transparent',
          }}
          onClick={() => onSheetChange('none')}
        >
          <span className="text-base leading-none" aria-hidden>
            ◉
          </span>
          {t('mobile.graph')}
        </button>
        <button
          type="button"
          className={btn(sheet === 'controls')}
          style={{
            backgroundColor: sheet === 'controls' ? themeColor : 'transparent',
          }}
          onClick={() => toggle('controls')}
        >
          <span className="text-base leading-none" aria-hidden>
            ⚙
          </span>
          {t('mobile.settings')}
        </button>
        <button
          type="button"
          disabled={!hasNode}
          className={`${btn(sheet === 'node')} disabled:opacity-30`}
          style={{
            backgroundColor: sheet === 'node' ? themeColor : 'transparent',
          }}
          onClick={() => hasNode && toggle('node')}
        >
          <span className="text-base leading-none" aria-hidden>
            ◈
          </span>
          {t('mobile.node')}
        </button>
        <button
          type="button"
          className={btn(sheet === 'ai' || showAI)}
          style={{
            backgroundColor: sheet === 'ai' || showAI ? themeColor : 'transparent',
          }}
          onClick={() => toggle('ai')}
        >
          <span className="text-base leading-none" aria-hidden>
            ✦
          </span>
          {t('mobile.ai')}
        </button>
        <button
          type="button"
          className={btn(sheet === 'reputation' || showReputation)}
          style={{
            backgroundColor: sheet === 'reputation' || showReputation ? themeColor : 'transparent',
          }}
          onClick={() => toggle('reputation')}
        >
          <span className="text-base leading-none" aria-hidden>
            ⬡
          </span>
          {t('mobile.reputation')}
        </button>
        <button
          type="button"
          className={btn(sheet === 'tx' || showTx)}
          style={{
            backgroundColor: sheet === 'tx' || showTx ? themeColor : 'transparent',
          }}
          onClick={() => toggle('tx')}
        >
          <span className="text-base leading-none" aria-hidden>
            ≡
          </span>
          {t('mobile.log')}
        </button>
      </div>
    </nav>
  );
}
