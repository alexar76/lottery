# Alien Monitor i18n

UI strings live in JSON catalogs per locale:

| File | Language |
|------|----------|
| `locales/en.json` | English (fallback) |
| `locales/ru.json` | Russian |
| `locales/es.json` | Spanish |

## Usage

```tsx
import { useI18n } from '../i18n';

const { t, locale, setLocale } = useI18n();
t('metrics.invocations');
t('tick', { n: 42 });
t('nodeDetail.metricKeys.chain_id'); // unknown keys fall back to key path
```

## Adding a locale

1. Copy `en.json` → `locales/<code>.json`
2. Add code to `types.ts` → `LOCALES` and `LOCALE_LABELS`
3. Import in `context.tsx` → `catalogs`

## Backend AI

`POST /api/ai/ask` accepts `{ "question", "locale", "provider", "model_role", "state", "selected_node_id" }`.
Live `state` is the WebSocket ecosystem snapshot (tick, nodes, events). Default LLM: DeepSeek `deepseek-v4-pro` via parent `data/config/model_providers.yaml`.
