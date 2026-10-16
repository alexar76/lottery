#!/usr/bin/env bash
# Delete old Foundry Anvil dump caches under ~/.foundry/anvil/tmp.
#
# Anvil writes a full snapshot into anvil-state-* (a directory of JSON files,
# about one file every few seconds) and never removes them. Those files are a
# cache: the chain's live state is the file anvil currently has open, which
# this script will not unlink.
#
# Keeps the newest ANVIL_DUMP_KEEP (default 3) anvil-state-* directories, and
# the newest 3 regular files inside each directory that is kept. Anything
# anvil has open is kept as well, even if that is more than 3.

anvil_dump_mtime() {
  stat -c '%Y' "$1" 2>/dev/null || stat -f '%m' "$1" 2>/dev/null
}

anvil_dump_dev() {
  stat -c '%d' "$1" 2>/dev/null || stat -f '%d' "$1" 2>/dev/null
}

anvil_dump_ino() {
  stat -c '%i' "$1" 2>/dev/null || stat -f '%i' "$1" 2>/dev/null
}

# Print paths (and INODE:dev:ino markers) that the anvil process has open.
_anvil_open_paths() {
  local pid_dir comm fd link dev ino
  [ -d /proc ] || return 0
  for pid_dir in /proc/[0-9]*; do
    [ -d "$pid_dir" ] || continue
    comm=$(cat "$pid_dir/comm" 2>/dev/null) || continue
    comm=${comm%$'\n'}
    [ "$comm" = "anvil" ] || continue
    for fd in "$pid_dir"/fd/*; do
      link=$(readlink "$fd" 2>/dev/null) || continue
      printf '%s\n' "$link"
      if [ -e "$link" ]; then
        dev=$(anvil_dump_dev "$link" 2>/dev/null) || continue
        ino=$(anvil_dump_ino "$link" 2>/dev/null) || continue
        printf 'INODE:%s:%s\n' "$dev" "$ino"
      fi
    done
  done
}

_load_anvil_open_set() {
  ANVIL_OPEN_SET=""
  # Tests set this (possibly empty) so the pass stays hermetic and does not
  # scan the machine's /proc. Unset means "ask the running anvil".
  if [ -n "${ANVIL_DUMP_OPEN_PATHS+x}" ]; then
    ANVIL_OPEN_SET=$ANVIL_DUMP_OPEN_PATHS
    return 0
  fi
  ANVIL_OPEN_SET=$(_anvil_open_paths 2>/dev/null || true)
}

anvil_dump_is_open() {
  local path="$1" dev ino
  printf '%s\n' "$ANVIL_OPEN_SET" | grep -Fxq -- "$path" && return 0
  [ -e "$path" ] || return 1
  dev=$(anvil_dump_dev "$path" 2>/dev/null) || return 1
  ino=$(anvil_dump_ino "$path" 2>/dev/null) || return 1
  printf '%s\n' "$ANVIL_OPEN_SET" | grep -Fxq -- "INODE:${dev}:${ino}"
}

# Newest `keep` regular files stay. Open files stay even when older.
# Prints one "removed" line per deleted file.
_prune_files_in_dump() {
  local dir="$1" keep="$2" list mtime path n=0
  list=$(
    for f in "$dir"/*; do
      [ -e "$f" ] || continue
      [ -L "$f" ] && continue
      [ -f "$f" ] || continue
      mtime=$(anvil_dump_mtime "$f") || mtime=0
      printf '%s\t%s\n' "$mtime" "$f"
    done | sort -t "$(printf '\t')" -k1,1nr
  )
  [ -n "$list" ] || return 0
  printf '%s\n' "$list" | while IFS="$(printf '\t')" read -r mtime path; do
    [ -n "$path" ] || continue
    n=$((n + 1))
    if [ "$n" -le "$keep" ]; then
      continue
    fi
    if anvil_dump_is_open "$path"; then
      continue
    fi
    rm -f -- "$path" || true
    printf 'removed\n'
  done
}

_dump_has_open() {
  local dir="$1" f
  anvil_dump_is_open "$dir" && return 0
  for f in "$dir"/*; do
    [ -e "$f" ] || continue
    anvil_dump_is_open "$f" && return 0
  done
  return 1
}

# List direct anvil-state-* children, newest first. A function (not an inline
# case inside $()) so bash 3.2 does not treat the pattern's ")" as the end of
# the substitution.
_list_anvil_dumps() {
  local tmp="$1" p base mtime
  for p in "$tmp"/anvil-state-*; do
    [ -e "$p" ] || continue
    [ -L "$p" ] && continue
    base=$(basename "$p")
    case "$base" in
      anvil-state-*) ;;
      *) continue ;;
    esac
    [ "$(dirname "$p")" = "$tmp" ] || continue
    mtime=$(anvil_dump_mtime "$p") || mtime=0
    printf '%s\t%s\n' "$mtime" "$p"
  done | sort -t "$(printf '\t')" -k1,1nr
}

# Walk the newest-first list. Prints one "removed" line per deleted entry.
_apply_anvil_dump_prune() {
  local tmp="$1" keep="$2" list="$3" mtime path n=0 base
  printf '%s\n' "$list" | while IFS="$(printf '\t')" read -r mtime path; do
    [ -n "${path:-}" ] || continue
    base=$(basename "$path")
    case "$base" in
      anvil-state-*) ;;
      *) continue ;;
    esac
    [ "$(dirname "$path")" = "$tmp" ] || continue
    n=$((n + 1))
    if [ -d "$path" ]; then
      if [ "$n" -le "$keep" ] || _dump_has_open "$path"; then
        _prune_files_in_dump "$path" "$keep"
      else
        rm -rf -- "$path" || true
        printf 'removed\n'
      fi
    elif [ -f "$path" ]; then
      if [ "$n" -le "$keep" ] || anvil_dump_is_open "$path"; then
        continue
      fi
      rm -f -- "$path" || true
      printf 'removed\n'
    fi
  done
}

# tmp defaults to $HOME/.foundry/anvil/tmp (inside ailottery-chain-1 that is
# /root/.foundry/anvil/tmp). keep defaults to 3.
prune_anvil_dumps() {
  local tmp="${1:-${ANVIL_DUMP_TMP:-${HOME:-/root}/.foundry/anvil/tmp}}"
  local keep="${2:-${ANVIL_DUMP_KEEP:-3}}"
  local list removed

  case "$keep" in
    ''|*[!0-9]*) keep=3 ;;
  esac
  [ "$keep" -ge 1 ] || keep=1
  [ -d "$tmp" ] || return 0

  _load_anvil_open_set
  list=$(_list_anvil_dumps "$tmp")
  [ -n "$list" ] || return 0

  removed=$(_apply_anvil_dump_prune "$tmp" "$keep" "$list" | grep -c '^removed$' || true)
  if [ "${removed:-0}" -gt 0 ]; then
    echo "anvil-dump-reaper: removed ${removed} under ${tmp} (keep ${keep})" >&2
  fi
  return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  prune_anvil_dumps "$@"
fi
