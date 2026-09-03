# Alien Monitor — Security Assessment

## Scope

This assessment covers the Alien Monitor application (backend + frontend + infrastructure), evaluating data flows, attack surfaces, dependency risks, and deployment security.

---

## Architecture & Data Flow

```
Browser (Frontend)         Backend (FastAPI)         External Services
┌──────────────┐          ┌──────────────┐          ┌─────────────┐
│  React App   │◄─ HTTP ─►│  /api/*      │◄─ HTTP ─►│  Hub :9083  │
│  Three.js    │          │              │          │  Mesh :8090 │
│              │◄─ WS ───►│  /ws         │          │  Prom :9090 │
│              │          │              │          │  App :9081  │
│  AI Chat     │◄─ HTTP ─►│  /api/ai/ask │◄─ HTTP ─►│  Anthropic  │
└──────────────┘          └──────────────┘          └─────────────┘
```

---

## 1. API Security

### Authentication
| Endpoint | Auth | Risk |
|----------|------|------|
| `GET /api/health` | None | Low — public health check |
| `GET /api/state` | None | Low — read-only metrics |
| `GET /api/summary` | None | Low — aggregated stats |
| `GET /api/topology` | None | Low — static graph structure |
| `POST /api/ai/ask` | None | Medium — third-party API cost |
| `WS /ws` | None | Low — read-only state push |

### Findings

**F-1: AI endpoint is unauthenticated** — Severity: Medium
Any client can send unlimited requests to `/api/ai/ask`, which proxies to the Anthropic API and incurs cost.
- **Mitigation:** Add a rate limiter (e.g., 20 req/min per IP) or require a local API token for the AI endpoint.
- **Status:** Accepted risk for local dev; recommended before public deployment.

**F-2: No CORS restrictions in production** — Severity: Low
CORS is set to `allow_origins=["*"]` for development convenience.
- **Mitigation:** In production, restrict to known frontend origins.
- **Status:** Acceptable for localhost/internal use.

**F-3: WebSocket has no message size limit** — Severity: Low
No cap on incoming WebSocket message size — could allow memory exhaustion.
- **Mitigation:** Add message size validation (already small — only mode commands accepted).
- **Status:** Low risk due to single-command protocol.

---

## 2. Dependency Audit

### Python Backend
| Package | Version | Known CVEs | Risk |
|---------|---------|-----------|------|
| fastapi | >=0.115.0 | None critical | Low |
| uvicorn | >=0.32.0 | None critical | Low |
| httpx | >=0.27.0 | None critical | Low |
| anthropic | >=0.39.0 | None critical | Low |
| websockets | >=12.0 | None critical | Low |

### Node.js Frontend
| Package | Risk Assessment |
|---------|----------------|
| three.js 0.170 | WebGL — browser sandboxed, low risk |
| @react-three/fiber | R3F renderer — no server-side exposure |
| @react-three/postprocessing | GPU shader only — no network access |
| react 18.3 | Stable release, low risk |
| vite 5.4 | Build tool only — not in production bundle |
| tailwindcss 3.4 | CSS generator only — build-time |

### Findings

**F-4: npm audit shows 2 moderate vulnerabilities** — Severity: Low
These are in dev-only build tooling (not in production bundle).
- **Mitigation:** Run `npm audit fix` periodically.
- **Status:** Accepted — no production impact.

---

## 3. Data Exposure

### What the monitor DOES expose
| Data | Source | Sensitivity |
|------|--------|-------------|
| Node topology (names, URLs) | Hardcoded in Python | Low — public architecture |
| Metrics (counts, volumes) | Simulated or from live APIs | Low — aggregated, no PII |
| Agent names (fake) | Simulator | None — synthetic test data |
| Transaction amounts (fake) | Simulator | None — synthetic test data |
| AI chat messages | User input → Anthropic API | Medium — may contain queries about internal systems |

### What the monitor DOES NOT expose
- Private keys or seed phrases
- Real user wallet addresses (test mode uses synthetic data)
- Database contents
- Environment secrets (`.env` is gitignored)
- Hub signing keys

### Findings

**F-5: AI chat messages sent to Anthropic API** — Severity: Medium
User questions are forwarded to Anthropic's API. If running in LIVE mode with real infrastructure details in questions, those details leave the local network.
- **Mitigation:** Add a disclaimer in the AI panel. Use local-only fallback answers for sensitive queries.
- **Status:** Documented — AI panel shows it's using Claude API.

**F-6: Backend URLs exposed in topology API** — Severity: Low
`/api/topology` returns internal service URLs (e.g., `http://localhost:9083`).
- **Mitigation:** Only expose topology to localhost. Restrict in production via reverse proxy.
- **Status:** Acceptable for internal monitoring tool.

---

## 4. Infrastructure Security

### Docker Compose Test Network
- **Ganache** runs on port 8545 — bind to `127.0.0.1` only (currently `0.0.0.0`)
- **Solana test validator** on port 8899 — bind to `127.0.0.1` only
- **Fake tokens** have no real value — no financial risk

### Findings

**F-7: Blockchain ports exposed on 0.0.0.0** — Severity: Medium
Ganache (8545) and Solana (8899) bind to all interfaces, allowing external connections.
- **Mitigation:** Bind to `127.0.0.1` in docker-compose.test.yml. Only expose if remote access is needed.
- **Status:** Needs fix before any non-localhost deployment.

---

## 5. WebSocket Security

### Current Implementation
- No authentication required to connect
- Clients can only receive state (read-only)
- Mode switching (test/real) does not affect server config files
- Message protocol: `{"cmd": "set_mode", "mode": "test"}`

### Findings

**F-8: Mode switching has no authorization** — Severity: Low
Any WebSocket client can toggle between TEST and LIVE modes. In LIVE mode, this triggers real HTTP requests to internal infrastructure.
- **Mitigation:** Acceptable for a monitoring dashboard — it only changes what data is displayed.
- **Status:** By design — monitoring tool, not control plane.

---

## 6. Recommendations

### Before Local Development Use
- [x] All secrets in `.env` (gitignored) — **Done**
- [x] No hardcoded credentials — **Done**
- [x] Synthetic data in test mode — **Done**

### Before Internal Network Deployment
- [ ] Restrict CORS to specific origins
- [ ] Add rate limiting to `/api/ai/ask`
- [ ] Bind blockchain ports to `127.0.0.1`
- [ ] Add `ANTHROPIC_API_KEY` validation on startup

### Before Public Deployment
- [ ] Add authentication (API keys or OAuth) to all endpoints
- [ ] HTTPS only (TLS termination at reverse proxy)
- [ ] WebSocket authentication
- [ ] Audit logging for AI queries
- [ ] Content Security Policy headers
- [ ] Rate limit all endpoints
- [ ] Disable AI endpoint or require auth

---

## Summary

| Risk Level | Count | Description |
|------------|-------|-------------|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 3 | Unauthenticated AI endpoint, AI data leaving network, exposed blockchain ports |
| Low | 5 | CORS wildcard, WebSocket message size, dependency CVEs, topology URL exposure, mode switching |

**Overall Assessment:** Safe for local development and internal network use. The monitor is a read-only observation tool with no control-plane access. For public deployment, add authentication and HTTPS as recommended above.
