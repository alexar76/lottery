#!/usr/bin/env bash
# =============================================================================
# Alien Monitor — One-command ecosystem launcher
#
# Usage:
#   ./start.sh              # Test mode (simulated data)
#   ./start.sh --real       # Real mode (live infrastructure)
#   ./start.sh --with-infra # Test mode + Ganache + Solana validator
#
# What it does:
#   1. Installs Python + Node deps if needed
#   2. Starts test blockchain infra (--with-infra)
#   3. Seeds fake USDT/USDC tokens
#   4. Starts backend (FastAPI + WebSocket)
#   5. Starts frontend (Vite dev server)
#   6. Opens browser at http://localhost:5173
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODE="test"
WITH_INFRA=0
BACKEND_PORT="${ALIEN_PORT:-9100}"
FRONTEND_PORT=5173

usage() {
  cat <<'EOF'
Alien Monitor — AIMarket Ecosystem Visualizer

Usage:
  ./start.sh [options]

Options:
  --real            Connect to live infrastructure (hub, mesh, prometheus)
  --universe        UNI mode (local chain + live Hub/Mesh/Factory polls)
  --with-infra      Start test blockchain (Ganache + Solana validator)
  --backend-only    Start only the backend server
  --frontend-only   Start only the frontend dev server
  --port PORT       Backend port (default: 9100)
  -h, --help        This help

Examples:
  ./start.sh                          # Test mode with simulated data
  ./start.sh --universe               # UNI: local chain + live ecosystem layers
  ./start.sh --with-infra             # Test mode + real blockchain infra
  ./start.sh --real                   # Connect to live AIMarket infra
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --real)           MODE="real"; shift ;;
    --universe)       MODE="universe"; shift ;;
    --with-infra)     WITH_INFRA=1; shift ;;
    --backend-only)   BACKEND_ONLY=1; shift ;;
    --frontend-only)  FRONTEND_ONLY=1; shift ;;
    --port)           BACKEND_PORT="${2:-9100}"; shift 2 ;;
    -h|--help)        usage; exit 0 ;;
    *)                echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        👽 ALIEN MONITOR — Ecosystem Pulse Visualizer        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Mode:     $MODE"
echo "  Backend:  http://localhost:${BACKEND_PORT}"
echo "  Frontend: http://localhost:${FRONTEND_PORT}"
echo "  Infra:    $([ "$WITH_INFRA" -eq 1 ] && echo 'YES (Ganache + Solana)' || echo 'NO (simulated)')"
echo ""

# ── 1. Check dependencies ──────────────────────────────────────────────────

check_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: $1 is required. Install it first." >&2; exit 1; }
}

if [ "${BACKEND_ONLY:-0}" != "1" ]; then
  check_cmd node
fi
check_cmd python3

# ── 2. Install Python deps ─────────────────────────────────────────────────

if [ ! -d "$ROOT/backend/.venv" ]; then
  echo "Creating Python venv..."
  python3 -m venv "$ROOT/backend/.venv"
fi
source "$ROOT/backend/.venv/bin/activate"
pip install -q -r "$ROOT/backend/requirements.txt"
echo "Python deps: OK"

# ── 3. Start test blockchain infra ─────────────────────────────────────────

if [ "$WITH_INFRA" -eq 1 ]; then
  echo ""
  echo "── Starting test blockchain infrastructure..."

  # Start Ganache if available
  if command -v ganache >/dev/null 2>&1; then
    echo "Starting Ganache (EVM test chain on :8545)..."
    ganache \
      --wallet.deterministic \
      --wallet.totalAccounts 20 \
      --wallet.defaultBalance 1000 \
      --chain.chainId 1337 \
      --chain.networkId 1337 \
      --port 8545 \
      --quiet &
    GANACHE_PID=$!
    echo "Ganache PID: $GANACHE_PID"
    sleep 3
  elif command -v npx >/dev/null 2>&1; then
    echo "Starting Ganache via npx..."
    npx ganache \
      --wallet.deterministic \
      --wallet.totalAccounts 20 \
      --wallet.defaultBalance 1000 \
      --chain.chainId 1337 \
      --port 8545 \
      --quiet &
    GANACHE_PID=$!
    sleep 3
  else
    echo "WARNING: Ganache not found. Install it: npm install -g ganache"
    echo "  Or use: ./start.sh  (test mode simulates blockchain data)"
  fi

  # Start Solana test validator if available (opt-in — ~1.5GB RAM)
  if [[ "${ALIEN_UNIVERSE_ENABLE_SOLANA:-0}" =~ ^([1]|[tT]rue|[yY]es|[oO]n)$ ]]; then
    if command -v solana-test-validator >/dev/null 2>&1; then
      echo "Starting Solana test validator (:8899)..."
      solana-test-validator --reset --quiet --rpc-port 8899 --bind-address 127.0.0.1 &
      SOLANA_PID=$!
      echo "Solana PID: $SOLANA_PID"
      sleep 5
    else
      echo "NOTE: solana-test-validator not found. Install Solana CLI for full infra."
    fi
  else
    echo "Solana skipped (ALIEN_UNIVERSE_ENABLE_SOLANA=0)"
  fi

  # Seed fake tokens
  if [ -n "${GANACHE_PID:-}" ]; then
    echo "Seeding fake USDT on Ganache..."
    python3 "$ROOT/infrastructure/seed/seed_evm.py" || echo "EVN seed skipped (cast not available)"
  fi
  if [ -n "${SOLANA_PID:-}" ]; then
    echo "Seeding fake USDC on Solana..."
    python3 "$ROOT/infrastructure/seed/seed_solana.py" || echo "Solana seed skipped (spl-token not available)"
  fi
fi

# ── 4. Start backend ───────────────────────────────────────────────────────

echo ""
echo "── Starting Alien Monitor backend..."

export ALIEN_MODE="$MODE"
export ALIEN_PORT="$BACKEND_PORT"

python3 "$ROOT/backend/main.py" &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"
sleep 2

if [ "$MODE" = "universe" ]; then
  echo "Bootstrapping UNI ecosystem (local chain + live layers)..."
  _uni_auth=()
  if [ -n "${ALIEN_API_TOKEN:-}" ]; then
    _uni_auth=(-H "Authorization: Bearer ${ALIEN_API_TOKEN}")
  fi
  curl -sf -X POST "${_uni_auth[@]}" "http://localhost:${BACKEND_PORT}/api/universe/start" >/dev/null \
    && echo "UNI: OK (chain + layer polling)" \
    || echo "WARNING: universe/start failed — set ALIEN_API_TOKEN and: curl -X POST -H \"Authorization: Bearer \$ALIEN_API_TOKEN\" http://localhost:${BACKEND_PORT}/api/universe/start"
fi

# ── 5. Start frontend ──────────────────────────────────────────────────────

if [ "${BACKEND_ONLY:-0}" != "1" ]; then
  echo ""
  echo "── Starting frontend dev server..."

  cd "$ROOT/frontend"

  if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install --silent
  fi

  npx vite --port "$FRONTEND_PORT" --host &
  FRONTEND_PID=$!
  echo "Frontend PID: $FRONTEND_PID"

  cd "$ROOT"
fi

# ── 6. Done ─────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  👽 ALIEN MONITOR IS ALIVE                                  ║"
echo "║                                                            ║"
echo "║  Open: http://localhost:${FRONTEND_PORT}                       ║"
echo "║  API:  http://localhost:${BACKEND_PORT}/api/health              ║"
echo "║  WS:   ws://localhost:${BACKEND_PORT}/ws                       ║"
echo "║                                                            ║"
echo "║  Controls:                                                 ║"
echo "║    - Drag to rotate 3D graph                                ║"
echo "║    - Scroll to zoom                                         ║"
echo "║    - Click nodes for details                                ║"
echo "║    - Toggle AI assistant (top-right)                        ║"
echo "║    - Switch TEST/LIVE mode                                   ║"
echo "║    - Change theme colors                                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Press Ctrl+C to stop all services."

# ── Cleanup on exit ─────────────────────────────────────────────────────────

cleanup() {
  echo ""
  echo "Shutting down Alien Monitor..."
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  [ -n "${GANACHE_PID:-}" ] && kill "$GANACHE_PID" 2>/dev/null || true
  [ -n "${SOLANA_PID:-}" ] && kill "$SOLANA_PID" 2>/dev/null || true
  echo "Goodbye! 👽"
}

trap cleanup EXIT INT TERM

# Wait for any process to exit
wait
