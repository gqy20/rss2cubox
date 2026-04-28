#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_SCRIPT="$ROOT_DIR/scripts/run_local_sync.sh"
CRON_SCHEDULE="${RSS2CUBOX_CRON_SCHEDULE:-0 */3 * * *}"
CRON_MARKER="# rss2cubox local sync"
CRON_LINE="$CRON_SCHEDULE $RUN_SCRIPT $CRON_MARKER"

if [ ! -x "$RUN_SCRIPT" ]; then
  chmod +x "$RUN_SCRIPT"
fi

tmp_file="$(mktemp)"
trap 'rm -f "$tmp_file"' EXIT

if crontab -l >"$tmp_file" 2>/dev/null; then
  :
else
  : >"$tmp_file"
fi

if grep -Fq "$CRON_MARKER" "$tmp_file"; then
  sed -i "\|$CRON_MARKER|c\\$CRON_LINE" "$tmp_file"
else
  {
    cat "$tmp_file"
    printf '%s\n' "$CRON_LINE"
  } >"$tmp_file.next"
  mv "$tmp_file.next" "$tmp_file"
fi

crontab "$tmp_file"

printf 'Installed rss2cubox cron:\n%s\n' "$CRON_LINE"
