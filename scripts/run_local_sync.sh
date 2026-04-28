#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUN_DATE="$(date '+%Y-%m-%d')"
RUN_STAMP="$(date '+%H-%M-%S')"
LOG_DIR="$ROOT_DIR/logs/cron/$RUN_DATE"
LOG_FILE="$LOG_DIR/$RUN_STAMP.log"
LOCK_FILE="$ROOT_DIR/.rss2cubox-local.lock"

mkdir -p "$LOG_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  {
    printf '{"ts":"%s","level":"WARN","event":"cron_skipped","reason":"another_run_in_progress"}\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  } >> "$LOG_FILE"
  exit 0
fi

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export RSS2CUBOX_RUN_ID="${RSS2CUBOX_RUN_ID:-local-$(date -u '+%Y%m%dT%H%M%SZ')}"

{
  printf '{"ts":"%s","level":"INFO","event":"cron_start","run_id":"%s","root":"%s"}\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$RSS2CUBOX_RUN_ID" "$ROOT_DIR"

  set +e
  if command -v uv >/dev/null 2>&1; then
    uv run rss2cubox
  else
    PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python -m rss2cubox.runner
  fi
  status=$?
  set -e

  printf '{"ts":"%s","level":"INFO","event":"cron_complete","run_id":"%s","status":%s}\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$RSS2CUBOX_RUN_ID" "$status"
  exit "$status"
} 2>&1 | tee -a "$LOG_FILE"

find "$ROOT_DIR/logs/cron" -type f -name '*.log' -mtime +30 -delete 2>/dev/null || true
find "$ROOT_DIR/logs/runs" -type f -name '*.jsonl' -mtime +30 -delete 2>/dev/null || true
