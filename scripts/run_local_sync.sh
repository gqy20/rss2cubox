#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

RUN_DATE="$(date '+%Y-%m-%d')"
RUN_STAMP="$(date '+%H-%M-%S')"
LOG_DIR="$ROOT_DIR/logs/cron/$RUN_DATE"
LOG_FILE="$LOG_DIR/$RUN_STAMP.log"
LOCK_FILE="$ROOT_DIR/.rss2cubox-local.lock"
LOG_RETENTION_DAYS="${RSS2CUBOX_LOG_RETENTION_DAYS:-30}"

mkdir -p "$LOG_DIR"

cleanup_logs() {
  find "$ROOT_DIR/logs/cron" -type f -name '*.log' -mtime +"$LOG_RETENTION_DAYS" -delete 2>/dev/null || true
  find "$ROOT_DIR/logs/runs" -type f -name '*.jsonl' -mtime +"$LOG_RETENTION_DAYS" -delete 2>/dev/null || true
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  {
    printf '{"ts":"%s","level":"WARN","event":"cron_skipped","reason":"another_run_in_progress"}\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  } >> "$LOG_FILE"
  exit 0
fi

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export RSS2CUBOX_RUN_ID="${RSS2CUBOX_RUN_ID:-local-$(date -u '+%Y%m%dT%H%M%SZ')}"

run_status=0

run_python_module() {
  module="$1"
  if command -v uv >/dev/null 2>&1; then
    uv run python -m "$module"
  elif [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$ROOT_DIR/.venv/bin/python" -m "$module"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m "$module"
  else
    PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python -m "$module"
  fi
}

{
  printf '{"ts":"%s","level":"INFO","event":"cron_start","run_id":"%s","root":"%s"}\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$RSS2CUBOX_RUN_ID" "$ROOT_DIR"

  set +e
  run_python_module rss2cubox.runner
  sync_status=$?

  prediction_status=0
  if [ "$sync_status" -eq 0 ]; then
    run_python_module rss2cubox.prediction_loop_runner
    prediction_status=$?
  fi
  status=$sync_status
  if [ "$status" -eq 0 ] && [ "$prediction_status" -ne 0 ]; then
    status=$prediction_status
  fi
  set -e

  printf '{"ts":"%s","level":"INFO","event":"cron_complete","run_id":"%s","status":%s,"sync_status":%s,"prediction_status":%s}\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$RSS2CUBOX_RUN_ID" "$status" "$sync_status" "$prediction_status"
  exit "$status"
} 2>&1 | tee -a "$LOG_FILE" || run_status=$?

cleanup_logs
exit "$run_status"
