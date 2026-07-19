import { useI18n } from '../i18n';

// Where the "how to enable crypto" disclaimer lives, per locale. Overridable at
// build time (VITE_CRYPTO_DOCS_URL) so a deployment can point at its own docs
// host; defaults to the doc shipped in the repo on GitHub.
const DOCS_BASE =
  (import.meta.env.VITE_CRYPTO_DOCS_URL as string | undefined)?.replace(/\/$/, '') ||
  'https://github.com/alexar76/aicom/blob/main/docs';
const DOC_BY_LOCALE: Record<string, string> = {
  en: `${DOCS_BASE}/crypto-switch.md`,
  ru: `${DOCS_BASE}/crypto-switch.ru.md`,
  es: `${DOCS_BASE}/crypto-switch.es.md`,
};

interface Props {
  mode: 'test' | 'real' | 'universe' | null;
  cryptoEnabled: boolean | null;
  themeColor: string;
}

/**
 * Honest-state badge: in LIVE with the ecosystem crypto switch OFF, the real
 * chain is intentionally not contacted, so the on-chain nodes are greyed and
 * this badge explains WHY (off in settings, not service down) + links to the
 * docs on how to turn the real on-chain economy on. Renders nothing otherwise.
 */
export default function CryptoNotice({ mode, cryptoEnabled, themeColor }: Props) {
  const { t, locale } = useI18n();
  if (mode !== 'real' || cryptoEnabled !== false) return null;
  const href = DOC_BY_LOCALE[locale] ?? DOC_BY_LOCALE.en;

  return (
    <div className="absolute bottom-[7.25rem] left-2 z-20 md:bottom-14 md:left-4 max-w-[80vw]">
      <div
        className="glass-panel flex items-center gap-2 rounded-lg px-3 py-1.5"
        style={{ borderColor: '#ffaa0055', boxShadow: '0 0 14px #ffaa0022' }}
        title={t(
          'crypto.disabledHint',
          undefined,
          'Crypto is OFF by default — no blockchain is required to run the ecosystem. The real on-chain economy is disabled in settings, so the chain, escrow, NFT, ACEX and lottery nodes show their true offline state. Set AIFACTORY_CRYPTO_ENABLED=1 to enable LIVE on Base.',
        )}
      >
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: '#ffaa00', boxShadow: '0 0 8px #ffaa00' }}
          aria-hidden
        />
        <span className="text-[11px] font-mono text-amber-200/90 leading-tight">
          {t('crypto.disabledBadge', undefined, 'Real blockchain disabled in settings')}
        </span>
        <a
          href={href}
          target="_blank"
          rel="noopener"
          className="text-[11px] font-mono font-bold underline decoration-dotted underline-offset-2 whitespace-nowrap"
          style={{ color: themeColor }}
        >
          {t('crypto.howToEnable', undefined, 'How to enable →')}
        </a>
      </div>
    </div>
  );
}
