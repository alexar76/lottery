# Alien Monitor — User Guide

## Quick Start

### Prerequisites
- **Node.js 20+** and **npm**
- **Python 3.11+** with pip
- A modern browser (Chrome/Firefox/Safari)

### One-Command Launch
```bash
cd alien-monitor
./start.sh
```
Opens at **http://localhost:5173** in TEST mode (simulated data).

---

## Understanding the Visualization

### The Universe Layout

The 3D space represents the AIMarket ecosystem as a **cosmic structure**:

| Region | Position | Contains |
|--------|----------|----------|
| **Center** (0, 0, 0) | Core of the universe | AIMarket Hub — the gravitational center |
| **Right** (+X) | Outer system | EVM contracts, Ethereum, NFT contract |
| **Left** (-X) | Outer system | SDKs, Service Mesh, CLI tools |
| **Top** (+Y) | Upper plane | Federation peers, Desktop Apps |
| **Bottom** (-Y) | Lower plane | Plugins cluster, ACEX |
| **Far** (+Z) | Deep space | Solana escrow, Solana chain |

### What You're Looking At

Each **celestial body** is a live component of the ecosystem:

- **Size** = Importance (core components are larger)
- **Color** = Component type (cyan=core, magenta=contracts, green=clients, purple=infra, yellow=SDKs, blue=network, orange=blockchain)
- **Pulse/Glow** = Activity level (active nodes pulse rhythmically)
- **Orbital Ring** = Active component with ongoing operations
- **Status Dot** (top-right of node) = Green=active, Yellow=idle, Red=error, Grey=unknown

### Connection Types

| Visual | Meaning |
|--------|---------|
| **Constellation lines** (faint bezier curves) | Permanent logical connections |
| **Wormhole tunnels** (spiral particles) | Active data/payment flows |
| **Asteroid belts** (orbital rings) | Network/blockchain activity |
| **Nebula clouds** (diffuse particle clusters) | Groups of related components |

---

## Controls Reference

### Mouse/Keyboard
| Action | Control |
|--------|---------|
| **Rotate view** | Left-click + drag anywhere |
| **Zoom in/out** | Scroll wheel up/down |
| **Pan** | Right-click + drag |
| **Inspect node** | Left-click on any planet/node |
| **Close inspector** | Press `Escape` or click `×` on panel |
| **Reset camera** | Refresh the page |

### UI Controls (top-right panel)
| Button | Function |
|--------|----------|
| **TEST / LIVE** | Switch between simulated and real data |
| **CY / MG / GR** | Change theme color (Cyan, Magenta, Green) |
| **AI** | Toggle AI Assistant chat panel |
| **LOG** | Toggle transaction activity stream |
| **PULSE** slider | Adjust glow/pulse animation intensity (0-100%) |

### Touch (mobile/tablet)
| Gesture | Action |
|---------|--------|
| One finger drag | Rotate |
| Two finger pinch | Zoom |
| Two finger drag | Pan |
| Tap on node | Inspect |

---

## Node Reference

### Core Components

**AIMarket Hub** (center, cyan, large sun)
- The central registry for AI capabilities and payment routing
- Metrics: federated peers, registered capabilities, open channels, 24h invocations
- URL: usually `http://localhost:9083`

**AI-Factory** (right-upper, cyan planet)
- Autonomous product pipeline: design → build → test → publish
- Metrics: products created, tasks pending/done
- URL: usually `http://localhost:9081`

**AI Service Mesh** (left, cyan planet)
- Agent discovery, verification, orchestration, escrow
- Metrics: registered agents, active tasks, activity events
- URL: usually `http://localhost:8090`

**ACEX** (lower-right, cyan planet)
- Agent Capital Exchange — ALP, CapShares, AgentNotes, Pulse AMM
- Metrics: 24h volume, active listings

### Smart Contracts

**EVM Escrow** (right, magenta crystal)
- Payment channels on Ethereum/Base/Arbitrum (USDT/USDC)
- Metrics: active channels, TVL, chain name

**Solana Escrow** (far-right, magenta crystal)
- Payment channels on Solana (USDC)
- Metrics: active channels, TVL

**Capability NFT** (right, magenta crystal)
- ERC-721 transferable entitlements
- Metrics: minted NFTs, unique holders

### Client Applications

**Desktop Apps** (upper-left, green planet)
- 9 desktop applications: Capability Composer, Cold Outreach Coach, Creator Algorithm Coach, Discovery Prospector, Freelance Contract Reviewer, Interview Prep Coach, Personal Finance Coach, Reputation Dashboard, Local Security Audit (Tauri)
- Metrics: apps currently online

**Widget** (upper-right, green dot)
- Embeddable `<script>` tag storefront
- Metrics: themes available, impressions

**CLI Tools** (lower-left, green dot)
- ai_company_cli, ai_market_agent, ai_market_sdk
- Metrics: commands executed

### Infrastructure

**Plugins** (bottom-center, purple nebula cluster)
- 15 hub plugins: safety, TEE, channels, streaming, reputation, auction, orchestrator, NFT, ZK, provenance, MCP packager, personas, promo, dataset, data-cap
- Metrics: plugins loaded out of 15 total

**Federation** (upper-left, blue network node)
- BFS peer discovery across federated hubs
- Metrics: discovered peers, crawl operations

### SDKs
**Dart SDK**, **TypeScript SDK**, **Rust SDK** (left side, yellow dots)
- Client libraries for different platforms
- All follow the discover → channel → invoke → settle lifecycle

### Blockchains
**Ethereum** (far-right, orange sun)
- L1 with L2s: Base, Arbitrum, Optimism, Polygon
- Metrics: current gas price (GWEI), latest block number

**Solana** (far-right-bottom, orange sun)
- High-performance L1
- Metrics: current slot, transactions per second

---

## Modes

### TEST Mode (Yellow indicator)
- Simulates a vibrant ecosystem
- Generates realistic metrics with natural variance
- Creates fake agents (AlphaBot, CodeNova, DataWhisperer, etc.)
- Simulates transaction flows, channel operations, invocations
- Perfect for: demos, development, UI testing

### LIVE Mode (Green indicator)
- Connects to real running infrastructure
- Reads from Hub `/stats/live`, Mesh `/v1/stats`, Prometheus metrics
- Shows actual on-chain data where available
- Requires: running AIMarket Hub, Service Mesh, Prometheus

---

## AI Assistant

Click the **AI** button (top-right) to open the chat panel.

The assistant knows about:
- Every component's purpose, API endpoints, and architecture
- Plugin system and all 15 plugins
- SDK lifecycle and protocol flow
- Smart contract functionality
- Desktop app capabilities
- Test vs real mode differences

**Example questions:**
- "How do payment channels work?"
- "What plugins does the hub have?"
- "Explain the invoke lifecycle"
- "What blockchains are supported?"
- "What does the TEE plugin do?"

---

## Troubleshooting

### "Connecting to ecosystem..." stays forever
- The backend server may not be running
- Check: `curl http://localhost:9100/api/health`
- Restart: `./start.sh`

### 3D graph is slow / laggy
- Reduce PULSE slider below 50%
- Close other GPU-heavy applications
- Lower browser window size
- The frontend targets DPR [1, 1.5] for performance

### AI Assistant returns generic answers
- The Anthropic API key may not be set
- Set: `export ANTHROPIC_API_KEY=your-key`
- Without the key, a built-in rule-based fallback answers common questions

### Backend won't start
- Check Python version: `python3 --version` (needs 3.11+)
- Install deps: `cd backend && pip install -r requirements.txt`
- Check port conflict: `lsof -i :9100`

### "Cannot connect to EVM RPC" (--with-infra mode)
- Ganache may not be installed: `npm install -g ganache`
- Or use test mode instead (simulated blockchain data)
