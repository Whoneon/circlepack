#!/usr/bin/env bash
# Launch / monitor / stop a circlepack campaign detached from the terminal.
#
#   scripts/run_campaign.sh start  <campaign.toml> [dir]   start (or resume) in the background
#   scripts/run_campaign.sh status <dir>                   summary (progress, throughput, candidates)
#   scripts/run_campaign.sh log    <dir>                   follow the log
#   scripts/run_campaign.sh stop   <dir>                   graceful stop (STOP file; waits for it)
#   scripts/run_campaign.sh kill   <dir>                   SIGTERM (graceful too, shorter)
#
# The driver runs under setsid+nohup (survives logout/terminal close), at nice 10
# with workers at nice 15 and ionice idle, wrapped in `systemd-inhibit
# --what=sleep:idle:handle-lid-switch` so the machine does not suspend (no sudo
# needed in a local session; skipped with a warning if not permitted). A lock
# file (<dir>/campaign.lock, held by the driver) prevents double launches.
# Environment: PYTHON (default: <repo>/.venv/bin/python if present, else python3 on PATH).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$REPO/.venv/bin/python" ]]; then PY="$REPO/.venv/bin/python"; else PY=python3; fi
fi
# Always import circlepack from this checkout (not whatever is pip-installed).
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
cmd="${1:-}"; shift || true

running() {  # dir -> 0 if a driver holds the lock
  [[ -e "$1/campaign.lock" ]] || return 1
  ! flock -n "$1/campaign.lock" true 2>/dev/null
}

case "$cmd" in
  start)
    [[ $# -ge 1 ]] || usage
    FILE="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
    DIR="${2:-$("$PY" -c 'import sys; from circlepack.campaign import load_config; d = load_config(sys.argv[1]).dir; print(d or "")' "$FILE")}"
    [[ -n "$DIR" ]] || { echo "no output dir: pass one or set [campaign] dir" >&2; exit 2; }
    mkdir -p "$DIR"; DIR="$(cd "$DIR" && pwd)"
    if running "$DIR"; then echo "already running in $DIR (pid $(cat "$DIR/campaign.pid" 2>/dev/null || echo '?'))" >&2; exit 1; fi
    rm -f "$DIR/STOP"
    INHIBIT=()
    if command -v systemd-inhibit >/dev/null; then
      if systemd-inhibit --what=sleep:idle:handle-lid-switch --who=circlepack --why=probe --mode=block true 2>/dev/null; then
        INHIBIT=(systemd-inhibit --what=sleep:idle:handle-lid-switch --who=circlepack
                 "--why=circlepack campaign $(basename "$FILE")" --mode=block)
      elif systemd-inhibit --what=sleep:idle --who=circlepack --why=probe --mode=block true 2>/dev/null; then
        INHIBIT=(systemd-inhibit --what=sleep:idle --who=circlepack "--why=circlepack campaign" --mode=block)
        echo "note: lid-switch inhibit not permitted; closing the lid may still suspend" >&2
      else
        echo "warning: systemd-inhibit not permitted; the machine may suspend" >&2
      fi
    fi
    IONICE=(); command -v ionice >/dev/null && IONICE=(ionice -c 3)
    {
      echo "==== $(date '+%F %T') start: $FILE (python $PY, repo $REPO)"
    } >> "$DIR/campaign.log"
    cd "$REPO"
    setsid nohup "${INHIBIT[@]}" nice -n 10 "${IONICE[@]}" "$PY" -m circlepack campaign run "$FILE" --dir "$DIR" \
      >> "$DIR/campaign.log" 2>&1 < /dev/null &
    for _ in $(seq 1 30); do [[ -s "$DIR/campaign.pid" ]] && running "$DIR" && break; sleep 1; done
    if running "$DIR"; then
      echo "started: pid $(cat "$DIR/campaign.pid")  dir $DIR"
      [[ ${#INHIBIT[@]} -gt 0 ]] && echo "sleep inhibited while running (check: systemd-inhibit --list)"
      echo "monitor: $0 status $DIR    (report: $DIR/REPORT.md, every 15 min)"
      echo "log:     $0 log $DIR"
      echo "stop:    $0 stop $DIR      (or: touch $DIR/STOP)"
    else
      echo "driver did not start; see $DIR/campaign.log:" >&2; tail -20 "$DIR/campaign.log" >&2; exit 1
    fi
    ;;
  status)
    [[ $# -ge 1 ]] || usage
    "$PY" -m circlepack campaign status "$1" "${@:2}"
    if running "$1"; then echo "driver: running (pid $(cat "$1/campaign.pid" 2>/dev/null))"; else echo "driver: not running"; fi
    ;;
  log)
    [[ $# -ge 1 ]] || usage
    exec tail -n 40 -f "$1/campaign.log"
    ;;
  stop|kill)
    [[ $# -ge 1 ]] || usage
    DIR="$1"
    running "$DIR" || { echo "not running"; exit 0; }
    if [[ "$cmd" == stop ]]; then touch "$DIR/STOP"; else kill -TERM "$(cat "$DIR/campaign.pid")"; fi
    echo -n "waiting for the driver to finish its current starts"
    for _ in $(seq 1 400); do running "$DIR" || { echo; echo "stopped."; exit 0; }; echo -n .; sleep 1; done
    echo; echo "still running after 400 s; force: kill -INT twice or kill -KILL $(cat "$DIR/campaign.pid")" >&2; exit 1
    ;;
  *) usage ;;
esac
