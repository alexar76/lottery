import { useEffect, useRef, useState } from 'react';
import type { EcosystemState } from '../App';
import { apiUrl } from '../api';
import { monitorAuthHeaders } from '../monitorAuth';
import { useI18n } from '../i18n';
import { useVoiceInput } from '../hooks/useVoiceInput';

interface Props {
  themeColor: string;
  onClose: () => void;
  monitorState: EcosystemState | null;
  selectedNodeId: string | null;
  onFocusNode?: (nodeId: string) => void;
  mobile?: boolean;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface AiProvider {
  id: string;
  provider_type: string;
  models: { heavy: string; light: string };
  available: boolean;
  is_default: boolean;
}

const SUGGESTION_KEYS = [
  'hub',
  'now',
  'skopos',
  'metis',
  'reputation',
  'factory',
  'navigate',
  'channels',
  'plugins',
  'desktop',
  'acex',
] as const;

interface AiFocusAction {
  type: 'focus_node';
  node_id: string;
  requested_id?: string;
}

function MicIcon({ off }: { off?: boolean }) {
  if (off) {
    return (
      <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
        <path d="M1 1l22 22" />
        <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6" />
        <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

export default function AIAssistant({
  themeColor,
  onClose,
  monitorState,
  selectedNodeId,
  onFocusNode,
  mobile = false,
}: Props) {
  const { t, locale } = useI18n();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [providerId, setProviderId] = useState<string>('');
  const [modelRole, setModelRole] = useState<'heavy' | 'light'>('heavy');
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef('');
  inputRef.current = input;

  const {
    listening: voiceListening,
    micBusy,
    voiceError,
    clearVoiceError,
    stop: stopVoiceInput,
    toggle: toggleVoiceInput,
    speechAvailable,
  } = useVoiceInput({
    locale,
    disabled: loading,
    getInput: () => inputRef.current,
    setInput,
    t,
  });

  useEffect(() => {
    setMessages([{ role: 'assistant', content: t('ai.welcome') }]);
  }, [locale, t]);

  useEffect(() => {
    fetch(apiUrl('/api/ai/providers'), { headers: monitorAuthHeaders() })
      .then((r) => r.json())
      .then((data) => {
        const list: AiProvider[] = data.providers ?? [];
        setProviders(list);
        const def = list.find((p) => p.is_default) ?? list.find((p) => p.available) ?? list[0];
        if (def) setProviderId(def.id);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || loading) return;
    stopVoiceInput();
    clearVoiceError();
    const userMsg: Message = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 90_000);
      const res = await fetch(apiUrl('/api/ai/ask'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...monitorAuthHeaders() },
        body: JSON.stringify({
          question: text,
          locale,
          provider: providerId || undefined,
          model_role: modelRole,
          selected_node_id: selectedNodeId ?? undefined,
          state: monitorState ?? undefined,
        }),
        signal: controller.signal,
      });
      window.clearTimeout(timeout);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`);
      }
      const answer = (data as { answer?: string }).answer;
      if (!answer) {
        throw new Error('empty answer');
      }
      setMessages((prev) => [...prev, { role: 'assistant', content: answer }]);
      const actions = (data as { actions?: AiFocusAction[] }).actions ?? [];
      for (const action of actions) {
        if (action.type === 'focus_node' && action.node_id && onFocusNode) {
          onFocusNode(action.node_id);
        }
      }
    } catch (err) {
      const msg =
        err instanceof Error && err.name === 'AbortError'
          ? t('ai.timeout')
          : err instanceof Error
            ? `${t('ai.error')}: ${err.message}`
            : t('ai.offline');
      setMessages((prev) => [...prev, { role: 'assistant', content: msg }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
    if (e.key === 'Escape') onClose();
  };

  const activeProvider = providers.find((p) => p.id === providerId);

  useEffect(() => {
    if (!mobile) return undefined;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [mobile]);

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
        className={`z-40 glass-panel flex flex-col animate-slide-up min-h-0 ${
          mobile
            ? 'fixed inset-x-2 top-[max(0.5rem,var(--safe-top))] bottom-[max(0.5rem,var(--safe-bottom))] rounded-2xl'
            : 'absolute right-4 top-32 w-96 max-h-[calc(100vh-220px)]'
        }`}
        style={{
          borderColor: themeColor + '44',
          boxShadow: `0 0 30px rgba(0,0,0,0.5), 0 0 15px ${themeColor}22`,
        }}
      >
      <div
        className="flex items-center justify-between px-4 py-3 border-b"
        style={{ borderColor: themeColor + '22' }}
      >
        <div className="flex items-center gap-2">
          <div className="text-sm" style={{ color: themeColor }}>
            &#x25C9;
          </div>
          <span className="text-xs font-semibold tracking-wider" style={{ color: themeColor }}>
            {t('ai.title')}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-white/40 hover:text-white/80 transition-colors text-2xl leading-none w-10 h-10 flex items-center justify-center shrink-0"
          aria-label={t('mobile.closeSheet')}
        >
          ×
        </button>
      </div>

      {providers.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-2 px-4 py-2 border-b text-[10px] font-mono"
          style={{ borderColor: themeColor + '18' }}
        >
          <label className="text-white/40">{t('ai.provider')}</label>
          <select
            value={providerId}
            onChange={(e) => setProviderId(e.target.value)}
            className="bg-[#0a0a12] border border-white/10 rounded px-2 py-0.5 text-white/80 max-w-[140px]"
            style={{ color: themeColor }}
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id} disabled={!p.available}>
                {p.id}
                {!p.available ? ' (no key)' : ''}
              </option>
            ))}
          </select>
          <select
            value={modelRole}
            onChange={(e) => setModelRole(e.target.value as 'heavy' | 'light')}
            className="bg-[#0a0a12] border border-white/10 rounded px-2 py-0.5 text-white/80"
          >
            <option value="heavy">{t('ai.modelHeavy')}</option>
            <option value="light">{t('ai.modelLight')}</option>
          </select>
          {activeProvider && (
            <span className="text-white/30 truncate" title={activeProvider.models[modelRole]}>
              {activeProvider.models[modelRole]}
            </span>
          )}
        </div>
      )}

      {monitorState && (
        <div className="px-4 py-1.5 text-[9px] font-mono text-white/35 border-b" style={{ borderColor: themeColor + '12' }}>
          {t('ai.liveContext', { tick: monitorState.tick })}
        </div>
      )}

      <div
        className={`flex-1 overflow-y-auto p-4 space-y-3 min-h-0 ${mobile ? '' : ''}`}
        style={mobile ? undefined : { maxHeight: '360px' }}
      >
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`text-xs leading-relaxed ${
              msg.role === 'user' ? 'text-right' : 'text-left'
            }`}
          >
            <div
              className={`inline-block px-3 py-2 rounded-lg max-w-[85%] ${
                msg.role === 'user' ? 'text-white' : 'text-white/80'
              }`}
              style={{
                backgroundColor:
                  msg.role === 'user' ? themeColor + '22' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${
                  msg.role === 'user' ? themeColor + '44' : 'rgba(255,255,255,0.06)'
                }`,
              }}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex items-center gap-1.5 px-2">
            <div className="typing-dot w-1.5 h-1.5 rounded-full" style={{ backgroundColor: themeColor }} />
            <div className="typing-dot w-1.5 h-1.5 rounded-full" style={{ backgroundColor: themeColor }} />
            <div className="typing-dot w-1.5 h-1.5 rounded-full" style={{ backgroundColor: themeColor }} />
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {messages.length <= 1 && (
        <div className="px-4 pb-2">
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTION_KEYS.map((key) => (
              <button
                key={key}
                onClick={() => sendMessage(t(`ai.suggestions.${key}`))}
                className="text-[10px] px-2 py-1 rounded-full transition-colors"
                style={{
                  backgroundColor: themeColor + '0f',
                  border: `1px solid ${themeColor}22`,
                  color: themeColor,
                }}
              >
                {t(`ai.suggestions.${key}`)}
              </button>
            ))}
          </div>
        </div>
      )}

      {voiceError && (
        <div className="px-4 py-2 text-[10px] text-rose-300/90 border-t border-rose-500/20 bg-rose-950/30">
          {voiceError}
        </div>
      )}

      <div
        className="flex items-end gap-2 px-4 py-3 border-t"
        style={{ borderColor: themeColor + '22' }}
      >
        <div className="relative flex-1 min-w-0">
          <input
            type="text"
            value={input}
            onChange={(e) => {
              clearVoiceError();
              setInput(e.target.value);
            }}
            onKeyDown={handleKeyDown}
            placeholder={t('ai.placeholder')}
            className="w-full bg-transparent border-none outline-none text-xs text-white/90 placeholder:text-white/25 font-mono pr-9"
            disabled={loading}
          />
          <button
            type="button"
            onClick={() => void toggleVoiceInput()}
            disabled={loading || micBusy}
            aria-pressed={voiceListening}
            aria-label={voiceListening ? t('ai.voice.stopDictation') : t('ai.voice.dictation')}
            title={
              speechAvailable
                ? voiceListening
                  ? t('ai.voice.stopDictation')
                  : t('ai.voice.dictation')
                : t('ai.voice.unavailable')
            }
            className="absolute right-0 bottom-0 flex h-7 w-7 items-center justify-center rounded-full transition-all disabled:opacity-35"
            style={{
              color: voiceListening ? '#ff6b8a' : themeColor,
              backgroundColor: voiceListening ? '#ff6b8a22' : themeColor + '18',
              border: `1px solid ${voiceListening ? '#ff6b8a55' : themeColor + '44'}`,
              boxShadow: voiceListening ? '0 0 12px #ff6b8a44' : undefined,
            }}
          >
            {micBusy ? (
              <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
            ) : (
              <MicIcon off={voiceListening} />
            )}
          </button>
        </div>
        <button
          onClick={() => sendMessage(input)}
          disabled={loading || !input.trim()}
          className="text-xs px-3 py-1 rounded font-mono transition-all shrink-0"
          style={{
            backgroundColor: input.trim() ? themeColor + '33' : 'transparent',
            border: `1px solid ${input.trim() ? themeColor : '#ffffff22'}`,
            color: input.trim() ? themeColor : '#ffffff33',
          }}
        >
          {t('ai.send')}
        </button>
      </div>
    </div>
    </>
  );
}
