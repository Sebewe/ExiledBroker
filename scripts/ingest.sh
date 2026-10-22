#!/usr/bin/env bash
# Run ExiledBroker's data ingest unattended.
#
#   scripts/ingest.sh                  # hourly exchange history, every challenge league since Settlers
#   scripts/ingest.sh exchange -l Mirage --days 14
#   scripts/ingest.sh dumps            # daily poe.ninja dumps: download, extract, load
#   scripts/ingest.sh all              # both
#
# Safe to stop at any time (Ctrl-C, closing the terminal, a crash) and re-run: finished
# work is never fetched or rewritten again. Logs go to data/logs/, newest at
# data/logs/latest.log. On macOS the machine is kept awake while it runs.
#
# To run it in the background and check on it later:
#   nohup scripts/ingest.sh >/dev/null 2>&1 &
#   tail -f data/logs/latest.log
set -uo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${EB_AWAKE:-}" ]] && command -v caffeinate >/dev/null; then
  export EB_AWAKE=1
  exec caffeinate -i "$0" "$@"
fi

EB=.venv/bin/eb
if [[ ! -x "$EB" ]]; then
  echo "No .venv found. Set it up first: python3 -m venv .venv && .venv/bin/pip install -e '.[dev,demo]'" >&2
  exit 1
fi

mode="${1:-exchange}"
[[ $# -gt 0 ]] && shift

mkdir -p data/logs
log="data/logs/ingest-$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$(basename "$log")" data/logs/latest.log
export PYTHONUNBUFFERED=1

run() {
  echo "==> $(date -u +%H:%M:%S) eb $*" | tee -a "$log"
  # tee ignores Ctrl-C so eb's own "interrupted, re-run to resume" message is logged.
  "$EB" "$@" 2>&1 | (trap '' INT; tee -a "$log")
  local status=${PIPESTATUS[0]}
  if [[ $status -ne 0 ]]; then
    echo "==> eb $* stopped (exit $status). Re-run the same command to resume." | tee -a "$log"
    exit "$status"
  fi
}

case "$mode" in
  exchange) run exchange sync "$@" ;;
  dumps)    run dumps sync "$@"; run dumps load ;;
  all)      run dumps sync; run dumps load; run exchange sync "$@" ;;
  *) echo "usage: scripts/ingest.sh [exchange|dumps|all] [eb options]" >&2; exit 2 ;;
esac
echo "==> $(date -u +%H:%M:%S) done" | tee -a "$log"
