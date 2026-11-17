#!/usr/bin/env bash
# 06:30 calendar file, SB convert, life import, morning briefing. Does not send.
set -euo pipefail
umask 077

repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
day=${OUTLOOK_MORNING_DAY:-$(TZ=Asia/Seoul date +%F)}
state=${OUTLOOK_MORNING_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/second-brain/outlook-morning}
mkdir -p -- "$state"
chmod 700 "$state"
graph=$state/graph.json
converted=$state/life.json
py=${SB_PYTHON:-/usr/bin/python3}
source_name=${SB_LIFE_SOURCE:-outlook}
node=${NODE_BIN:-/home/jm/.nvm/versions/node/v24.19.0/bin/node}
if [[ ! -x $node ]]; then
  node=node
fi
export PYTHONPATH="$repo${PYTHONPATH:+:$PYTHONPATH}"

warn() {
  printf '%s\n' "$1" >&2
}

skip=0
socket=${MAIL_INTELLIGENCE_CALENDAR_SOCKET:-}
if [[ -z $socket || ! -S $socket ]]; then
  warn "소켓 없음"
  skip=1
else
  cli=${MAIL_CALENDAR_CLI:-}
  if [[ -z $cli ]]; then
    warn "소켓 없음"
    skip=1
  else
    set +e
    if [[ $cli == *.mjs ]]; then
      out=$("$node" "$cli" --out "$graph" --day "$day" 2>&1)
    else
      out=$("$cli" --out "$graph" --day "$day" 2>&1)
    fi
    code=$?
    set -e
    if [[ $code -eq 2 || $out == *동의\ 필요* ]]; then
      warn "동의 필요"
      skip=1
    elif [[ $code -ne 0 ]]; then
      warn "소켓 없음"
      skip=1
    fi
  fi
fi

if [[ $skip -eq 0 ]]; then
  "$py" "$repo/deploy/calendar_read.py" outlook-today --in "$graph" --out "$converted" --day "$day" >"$state/convert.log"
  "$py" -m sb.cli life import --source "$source_name" --format graph-calendar --raw-file "$converted" >"$state/import.json"
  chmod 600 "$state/import.json" "$converted"
fi

"$py" -m sb.cli life tick >"$state/tick.json"
chmod 600 "$state/tick.json"
"$py" -m sb.cli life briefing-generate --day "$day" --slot morning >"$state/briefing.json"
chmod 600 "$state/briefing.json"
