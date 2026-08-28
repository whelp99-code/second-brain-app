#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--dry-run]" >&2
  exit 2
fi

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
UNIT_SOURCE="$ROOT_DIR/deploy/systemd"
UNIT_DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SB_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/second-brain"
SB_CONFIG="$SB_CONFIG_DIR/config.toml"
SB_BIN="${SB_BIN:-$HOME/.local/bin/sb}"

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

if [[ ! -x "$SB_BIN" ]]; then
  echo "second-brain executable not found or not executable: $SB_BIN" >&2
  exit 1
fi

run install -d -m 0700 "$UNIT_DEST" "$SB_CONFIG_DIR"
for unit in second-brain.service second-brain.timer second-brain-backup.service second-brain-backup.timer; do
  run install -m 0644 "$UNIT_SOURCE/$unit" "$UNIT_DEST/$unit"
done

if [[ ! -e "$SB_CONFIG" ]]; then
  run install -m 0600 "$ROOT_DIR/config.example.toml" "$SB_CONFIG"
else
  echo "keeping existing config: $SB_CONFIG"
fi

if [[ $DRY_RUN -eq 0 ]]; then
  systemctl --user daemon-reload
  systemctl --user enable --now second-brain.timer second-brain-backup.timer
  systemctl --user list-timers --all 'second-brain*'
fi
