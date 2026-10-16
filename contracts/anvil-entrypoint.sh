#!/usr/bin/env bash
# ailottery-chain entrypoint. Anvil stays PID 1. A background loop deletes
# old anvil-state-* dumps every 60s (ANVIL_DUMP_PRUNE_INTERVAL_SEC) and keeps
# the newest 3 (ANVIL_DUMP_KEEP). A one-shot snapshot at
# /anvil-restore/state.json, when present, is passed as --load-state so a
# recreate does not drop the chain that was already running.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=anvil-dump-reaper.sh
. "$HERE/anvil-dump-reaper.sh"

if [ "${1:-}" = "--prune-once" ]; then
  shift
  prune_anvil_dumps "$@"
  exit $?
fi

interval="${ANVIL_DUMP_PRUNE_INTERVAL_SEC:-60}"
case "$interval" in
  ''|*[!0-9]*) interval=60 ;;
esac

(
  while true; do
    prune_anvil_dumps || true
    sleep "$interval" || exit 0
  done
) &

args=("$@")
restore="${ANVIL_RESTORE_STATE:-/anvil-restore/state.json}"
if [ -s "$restore" ]; then
  args+=(--load-state "$restore")
fi

exec anvil "${args[@]}"
