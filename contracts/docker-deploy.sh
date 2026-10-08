#!/usr/bin/env bash
# One-shot: wait for anvil, resolve deps, deploy AIAgentLottery, publish the address.
set -euo pipefail

RPC="${RPC_URL:-http://chain:8545}"
ADDR_FILE="${LOTTERY_ADDRESS_FILE:-/shared/lottery.address}"
OZ_TAG="${OZ_TAG:-v5.6.1}"
STD_TAG="${FORGE_STD_TAG:-v1.9.4}"

echo "deploy: waiting for anvil at $RPC …"
until cast block-number --rpc-url "$RPC" >/dev/null 2>&1; do sleep 1; done
echo "deploy: anvil is up (block $(cast block-number --rpc-url "$RPC"))"

mkdir -p lib
if [ -d /libs/openzeppelin-contracts/contracts ] && [ -d /libs/forge-std/src ]; then
    echo "deploy: using vendored libs from /libs (monorepo)"
    ln -sfn /libs/openzeppelin-contracts lib/openzeppelin-contracts
    ln -sfn /libs/forge-std lib/forge-std
else
    echo "deploy: forge install OpenZeppelin@${OZ_TAG} + forge-std@${STD_TAG}"
    git init -q 2>/dev/null || true
    git config user.email deploy@local >/dev/null 2>&1 || true
    git config user.name deploy >/dev/null 2>&1 || true
    forge install "OpenZeppelin/openzeppelin-contracts@${OZ_TAG}" "foundry-rs/forge-std@${STD_TAG}"
fi

echo "deploy: building + broadcasting DeployLottery …"
forge script script/DeployLottery.s.sol:DeployLottery \
    --rpc-url "$RPC" --broadcast -vvv 2>&1 | tee /tmp/deploy.log

# Prefer the broadcast artifact (authoritative), fall back to the console log line.
ADDR="$(jq -r '.transactions[] | select(.contractName=="AIAgentLottery") | .contractAddress' \
        broadcast/DeployLottery.s.sol/*/run-latest.json 2>/dev/null | head -n1)"
if [ -z "${ADDR:-}" ] || [ "$ADDR" = "null" ]; then
    ADDR="$(grep -oE '0x[0-9a-fA-F]{40}' /tmp/deploy.log | tail -n1)"
fi
[ -n "${ADDR:-}" ] || { echo "deploy: FAILED to determine deployed address" >&2; exit 1; }

mkdir -p "$(dirname "$ADDR_FILE")"
printf '%s' "$ADDR" > "$ADDR_FILE"
chmod 0644 "$ADDR_FILE" || true
echo "deploy: ✅ AIAgentLottery @ $ADDR  →  $ADDR_FILE"
