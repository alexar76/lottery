import { useCallback, useEffect, useRef, useState } from 'react';
import type { Locale } from '../i18n/types';

export function getSpeechRecognitionCtor(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export function speechRecognitionLang(locale: Locale): string {
  if (locale === 'ru') return 'ru-RU';
  if (locale === 'es') return 'es-ES';
  return 'en-US';
}

type MicGate = { proceed: true } | { proceed: false; userMessage: string };

async function gateMicrophone(t: (key: string) => string): Promise<MicGate> {
  if (typeof window === 'undefined') return { proceed: true };

  if (!window.isSecureContext) {
    return { proceed: false, userMessage: t('ai.voice.micNeedsHttps') };
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return { proceed: false, userMessage: t('ai.voice.micNoMediaDevices') };
  }

  try {
    const perm = await navigator.permissions?.query({ name: 'microphone' as PermissionName });
    if (perm?.state === 'denied') {
      return { proceed: false, userMessage: t('ai.voice.micPermBlocked') };
    }
  } catch {
    /* Permissions API may be unavailable. */
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
    return { proceed: true };
  } catch (e) {
    const denied =
      e instanceof DOMException &&
      (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError' || e.name === 'SecurityError');
    if (denied) {
      return { proceed: false, userMessage: t('ai.voice.micDeniedShort') };
    }
    return { proceed: false, userMessage: t('ai.voice.micDeviceBusy') };
  }
}

interface UseVoiceInputOptions {
  locale: Locale;
  disabled?: boolean;
  maxLen?: number;
  getInput: () => string;
  setInput: (value: string) => void;
  t: (key: string) => string;
}

export function useVoiceInput({
  locale,
  disabled = false,
  maxLen = 2000,
  getInput,
  setInput,
  t,
}: UseVoiceInputOptions) {
  const [listening, setListening] = useState(false);
  const [micBusy, setMicBusy] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const snapshotRef = useRef('');
  const finalAccumRef = useRef('');

  const stop = useCallback(() => {
    try {
      recognitionRef.current?.abort();
    } catch {
      /* ignore */
    }
    recognitionRef.current = null;
    setListening(false);
  }, []);

  useEffect(() => () => stop(), [stop]);

  const toggle = useCallback(async () => {
    if (listening) {
      stop();
      return;
    }
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      setVoiceError(t('ai.voice.unavailable'));
      return;
    }
    if (disabled || micBusy) return;

    setVoiceError(null);
    setMicBusy(true);
    const gate = await gateMicrophone(t);
    setMicBusy(false);
    if (!gate.proceed) {
      setVoiceError(gate.userMessage);
      return;
    }

    snapshotRef.current = getInput();
    finalAccumRef.current = '';
    const rec = new Ctor();
    rec.lang = speechRecognitionLang(locale);
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;

    rec.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const piece = event.results[i][0]?.transcript ?? '';
        if (event.results[i].isFinal) finalAccumRef.current += piece;
        else interim += piece;
      }
      const base = snapshotRef.current.trimEnd();
      const spoken = (finalAccumRef.current + interim).trim();
      const sep = base && spoken ? ' ' : '';
      setInput((base + sep + spoken).slice(0, maxLen));
    };

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === 'aborted' || event.error === 'no-speech') return;
      if (event.error === 'not-allowed') {
        setVoiceError(t('ai.voice.micRecognitionDenied'));
      } else {
        setVoiceError(event.message || event.error);
      }
      setListening(false);
      recognitionRef.current = null;
    };

    rec.onend = () => {
      setListening(false);
      recognitionRef.current = null;
    };

    recognitionRef.current = rec;
    setListening(true);
    try {
      rec.start();
    } catch (e) {
      setListening(false);
      recognitionRef.current = null;
      setVoiceError(e instanceof Error ? e.message : t('ai.voice.micStartError'));
    }
  }, [listening, disabled, micBusy, stop, locale, getInput, setInput, maxLen, t]);

  const speechAvailable = getSpeechRecognitionCtor() !== null;

  return {
    listening,
    micBusy,
    voiceError,
    clearVoiceError: () => setVoiceError(null),
    stop,
    toggle,
    speechAvailable,
  };
}
