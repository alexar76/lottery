#!/usr/bin/env bash
# Relayer pytest coverage → docs/badges/coverage.svg (real % badge).
# Solidity forge coverage fails on stack-too-deep for AIAgentLottery; contracts are
# gated by forge test in the same CI job.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f alien-monitor/backend/live_lottery_feed.py ]]; then
  rm -rf alien-monitor
  git clone --depth 1 https://github.com/alexar76/alien-monitor.git alien-monitor
fi

python -m pip install --upgrade pip
pip install -e "relayer[dev]" pytest-cov

cd relayer
pytest tests/ -q --cov=ailottery_relayer --cov-report=json:coverage.json
cd "$ROOT"

python scripts/generate_coverage_badge.py relayer/coverage.json docs/badges/coverage.svg

if [[ "${AICOM_CI_ENFORCE_BADGE_SYNC:-}" == "1" ]]; then
  git diff --quiet docs/badges/coverage.svg || {
    echo "docs/badges/coverage.svg drift — regenerate in monorepo and re-mirror" >&2
    exit 1
  }
fi
