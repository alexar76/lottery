#!/usr/bin/env bash
# Unit test for anvil-dump-reaper.sh. The contracts package tests Solidity
# with forge; this helper is shell, so the test is shell too.
set -u

ROOT=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=anvil-dump-reaper.sh
. "$ROOT/anvil-dump-reaper.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export ANVIL_DUMP_OPEN_PATHS=""

stamp() {
  # touch -t is CCYYMMDDhhmm.SS and is the same on macOS and Linux.
  touch -t "$2" "$1"
}

make_dump() {
  local name="$1" when="$2" n="$3" i
  local dir="$TMP/$name"
  mkdir -p "$dir"
  i=0
  while [ "$i" -lt "$n" ]; do
    printf 'x' > "$dir/f$i.json"
    # One second apart so mtime order is obvious. Base minute is $when (hhmm).
    stamp "$dir/f$i.json" "2020010100${when}.$(printf '%02d' "$i")"
    i=$((i + 1))
  done
  stamp "$dir" "2020010100${when}.00"
}

make_dump anvil-state-old 01 6
make_dump anvil-state-mid 02 6
make_dump anvil-state-new 03 6
make_dump anvil-state-newer 04 6
make_dump anvil-state-newest 05 6
printf 'live-chain' > "$TMP/state.json"
printf 'outside' > "$TMP/not-a-dump"
# A symlink must not be followed or removed.
ln -s "$TMP/state.json" "$TMP/anvil-state-link"

# The oldest file in the newest dump is "open" — anvil is writing it.
OPEN="$TMP/anvil-state-newest/f0.json"
export ANVIL_DUMP_OPEN_PATHS="$OPEN"

prune_anvil_dumps "$TMP" 3

[ -d "$TMP/anvil-state-newest" ] || fail "newest dir deleted"
[ -d "$TMP/anvil-state-newer" ] || fail "second dir deleted"
[ -d "$TMP/anvil-state-new" ] || fail "third dir deleted"
[ ! -d "$TMP/anvil-state-mid" ] || fail "fourth dir kept"
[ ! -d "$TMP/anvil-state-old" ] || fail "oldest dir kept"
[ -f "$TMP/state.json" ] || fail "state.json outside the dumps was deleted"
[ "$(cat "$TMP/state.json")" = "live-chain" ] || fail "state.json contents changed"
[ -f "$TMP/not-a-dump" ] || fail "unrelated file deleted"
[ -L "$TMP/anvil-state-link" ] || fail "symlink dump was removed"

kept=$(ls -1 "$TMP/anvil-state-newest" | sort)
# f0 is open, plus the three newest (f3 f4 f5). f1 and f2 go.
printf '%s\n' "$kept" | grep -qx 'f0.json' || fail "open file was deleted: $kept"
printf '%s\n' "$kept" | grep -qx 'f5.json' || fail "newest file missing: $kept"
printf '%s\n' "$kept" | grep -qx 'f4.json' || fail "second newest missing: $kept"
printf '%s\n' "$kept" | grep -qx 'f3.json' || fail "third newest missing: $kept"
printf '%s\n' "$kept" | grep -qx 'f1.json' && fail "old file kept: $kept"
printf '%s\n' "$kept" | grep -qx 'f2.json' && fail "old file kept: $kept"

# A directory that holds an open file is not removed, even if it is past keep.
# The open file is the oldest; the three newest stay; the ones in between go.
export ANVIL_DUMP_OPEN_PATHS="$TMP/anvil-state-ancient/old.json"
mkdir -p "$TMP/anvil-state-ancient"
printf 'o' > "$TMP/anvil-state-ancient/old.json"
stamp "$TMP/anvil-state-ancient" "202001010000.00"
stamp "$TMP/anvil-state-ancient/old.json" "202001010000.00"
i=1
while [ "$i" -le 5 ]; do
  printf 'g' > "$TMP/anvil-state-ancient/g$i.json"
  stamp "$TMP/anvil-state-ancient/g$i.json" "202001010000.$(printf '%02d' "$i")"
  i=$((i + 1))
done
prune_anvil_dumps "$TMP" 3
[ -d "$TMP/anvil-state-ancient" ] || fail "dir holding an open file was removed"
[ -f "$TMP/anvil-state-ancient/old.json" ] || fail "open file inside an old dir was deleted"
[ -f "$TMP/anvil-state-ancient/g5.json" ] || fail "newest file in an old dir was deleted"
[ ! -f "$TMP/anvil-state-ancient/g1.json" ] || fail "unopened old file was kept"
[ ! -f "$TMP/anvil-state-ancient/g2.json" ] || fail "unopened old file was kept"

# Missing directory is a no-op.
prune_anvil_dumps "$TMP/does-not-exist" 3 || fail "missing tmp should succeed"

echo "ok"
