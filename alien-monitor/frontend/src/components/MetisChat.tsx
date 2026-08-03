import { useEffect, useRef, useState } from 'react';
import { apiUrl } from '../api';
import { monitorAuthHeaders } from '../monitorAuth';
import { useI18n } from '../i18n';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface Props {
  themeColor: string;
  /** Node status from the graph — drives the offline hint. */
  status: string;
}

// OpenAI-compatible model ids Metis serves. "metis" auto-routes.
const MODELS = ['metis', 'metis-fast', 'metis-council'] as const;

/**
 * Live chat with the METIS cognitive layer, proxied through the monitor backend
 * (`POST /api/metis/chat`) so the Metis API key never reaches the browser.
 * Fully offline-safe: a dead Metis yields a readable message, never a crash.
 */
export default function MetisChat({ themeColor, status }: Props) {
  const { t } = useI18n();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState<string>('metis');
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || loading) return;
    const history = [...messages, { role: 'user' as const, content: q }];
    setMessages(history);
    setInput('');
    setLoading(true);
    try {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 90_000);
      const res = await fetch(apiUrl('/api/metis/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...monitorAuthHeaders() },
        body: JSON.stringify({ messages: history, model }),
        signal: controller.signal,
      });
      window.clearTimeout(timer);
      const data = (await res.json().catch(() => ({}))) as { answer?: string; error?: string };
      const answer = data.answer || t('metis.chat.offline');
      setMessages((prev) => [...prev, { role: 'assistant', content: answer }]);
    } catch (err) {
      const msg =
        err instanceof Error && err.name === 'AbortError'
          ? t('metis.chat.timeout')
          : t('metis.chat.offline');
      setMessages((prev) => [...prev, { role: 'assistant', content: msg }]);
    } finally {
      setLoading(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  return (
    <div className="mb-4" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] font-mono uppercase tracking-wider text-white/40">
          {t('metis.chat.title')}
        </div>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="bg-[#0a0a12] border border-white/10 rounded px-1.5 py-0.5 text-[10px] font-mono"
          style={{ color: themeColor }}
          aria-label={t('metis.chat.route')}
        >
          {MODELS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      {status === 'offline' && messages.length === 0 && (
        <p className="text-[11px] text-white/40 mb-2 leading-snug">{t('metis.chat.hint')}</p>
      )}

      <div
        className="rounded p-2 space-y-2 max-h-56 overflow-y-auto"
        style={{ backgroundColor: themeColor + '08', border: `1px solid ${themeColor}18` }}
      >
        {messages.length === 0 && (
          <div className="text-[11px] text-white/35 px-1 py-2">{t('metis.chat.welcome')}</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`text-xs leading-relaxed ${m.role === 'user' ? 'text-right' : 'text-left'}`}>
            <div
              className="inline-block px-2.5 py-1.5 rounded-lg max-w-[88%] whitespace-pre-wrap break-words"
              style={{
                backgroundColor: m.role === 'user' ? themeColor + '22' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${m.role === 'user' ? themeColor + '44' : 'rgba(255,255,255,0.06)'}`,
                color: m.role === 'user' ? '#fff' : 'rgba(255,255,255,0.82)',
              }}
            >
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-1.5 px-1">
            <div className="typing-dot w-1.5 h-1.5 rounded-full" style={{ backgroundColor: themeColor }} />
            <div className="typing-dot w-1.5 h-1.5 rounded-full" style={{ backgroundColor: themeColor }} />
            <div className="typing-dot w-1.5 h-1.5 rounded-full" style={{ backgroundColor: themeColor }} />
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="flex items-end gap-2 mt-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t('metis.chat.placeholder')}
          disabled={loading}
          className="flex-1 min-w-0 bg-transparent border-none outline-none text-xs text-white/90 placeholder:text-white/25 font-mono"
        />
        <button
          onClick={() => send(input)}
          disabled={loading || !input.trim()}
          className="text-xs px-3 py-1 rounded font-mono transition-all shrink-0"
          style={{
            backgroundColor: input.trim() ? themeColor + '33' : 'transparent',
            border: `1px solid ${input.trim() ? themeColor : '#ffffff22'}`,
            color: input.trim() ? themeColor : '#ffffff33',
          }}
        >
          {t('metis.chat.send')}
        </button>
      </div>
    </div>
  );
}
