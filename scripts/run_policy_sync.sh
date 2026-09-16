#!/usr/bin/env bash
# 政策信源的定时抓取脚本 —— 与 run_local_sync.sh 分开，因为两者节奏不同：
# 主链路每 3 小时（科技媒体更新快），政策源每天 1~2 次就够（政府站点更新慢）。
#
# 三个阶段分开执行、分别记录退出码，方便从 cron 日志直接定位是哪一步挂了。
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

RUN_DATE="$(date '+%Y-%m-%d')"
RUN_STAMP="$(date '+%H-%M-%S')"
LOG_DIR="$ROOT_DIR/logs/policy/$RUN_DATE"
LOG_FILE="$LOG_DIR/$RUN_STAMP.log"
LOCK_FILE="$ROOT_DIR/.rss2cubox-policy.lock"
LOG_RETENTION_DAYS="${POLICY_LOG_RETENTION_DAYS:-30}"

# 是否在 cron 里跑 deep enrich（每篇约 $0.14，CLI 记账值）
POLICY_CRON_ENRICH="${POLICY_CRON_ENRICH:-true}"
POLICY_CRON_ENRICH_LIMIT="${POLICY_CRON_ENRICH_LIMIT:-10}"
POLICY_CRON_MIN_RELEVANCE="${POLICY_CRON_MIN_RELEVANCE:-3}"
POLICY_CRON_TRIAGE_LIMIT="${POLICY_CRON_TRIAGE_LIMIT:-300}"

mkdir -p "$LOG_DIR"

cleanup_logs() {
  find "$ROOT_DIR/logs/policy" -type f -name '*.log' -mtime +"$LOG_RETENTION_DAYS" -delete 2>/dev/null || true
}

# 独立锁：不与主链路的 .rss2cubox-local.lock 互相阻塞
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  printf '{"ts":"%s","level":"WARN","event":"policy_cron_skipped","reason":"another_policy_run_in_progress"}\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >>"$LOG_FILE"
  exit 0
fi

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export RSS2CUBOX_RUN_ID="${RSS2CUBOX_RUN_ID:-policy-cron-$(date -u '+%Y%m%dT%H%M%SZ')}"

run_status=0

run_policy() {
  if command -v uv >/dev/null 2>&1; then
    uv run python -m rss2cubox.policy_runner "$@"
  elif [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$ROOT_DIR/.venv/bin/python" -m rss2cubox.policy_runner "$@"
  else
    PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m rss2cubox.policy_runner "$@"
  fi
}

{
  printf '{"ts":"%s","level":"INFO","event":"policy_cron_start","run_id":"%s","root":"%s"}\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$RSS2CUBOX_RUN_ID" "$ROOT_DIR"

  set +e

  # 阶段 1：抓取列表页入库（便宜，不调 LLM）
  run_policy
  fetch_status=$?

  # 阶段 2：预筛（N 个标题一次调用，便宜）
  triage_status=0
  if [ "$fetch_status" -eq 0 ]; then
    run_policy --triage --triage-limit "$POLICY_CRON_TRIAGE_LIMIT"
    triage_status=$?
  else
    printf '{"ts":"%s","level":"WARN","event":"policy_cron_stage_skipped","stage":"triage","reason":"fetch_failed"}\n' \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  fi

  # 阶段 3：深度抽取（逐篇一次调用，花钱，所以有 limit 和阈值）
  enrich_status=0
  if [ "$POLICY_CRON_ENRICH" = "true" ] && [ "$triage_status" -eq 0 ]; then
    run_policy --enrich-only \
      --enrich-limit "$POLICY_CRON_ENRICH_LIMIT" \
      --enrich-min-relevance "$POLICY_CRON_MIN_RELEVANCE"
    enrich_status=$?
  else
    printf '{"ts":"%s","level":"INFO","event":"policy_cron_stage_skipped","stage":"enrich","enabled":"%s","triage_status":%s}\n' \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$POLICY_CRON_ENRICH" "$triage_status"
  fi

  set -e

  # 任一阶段失败即整体失败，但三个状态都记下来便于定位
  status=$fetch_status
  [ "$status" -eq 0 ] && status=$triage_status
  [ "$status" -eq 0 ] && status=$enrich_status

  printf '{"ts":"%s","level":"INFO","event":"policy_cron_complete","run_id":"%s","status":%s,"fetch_status":%s,"triage_status":%s,"enrich_status":%s}\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$RSS2CUBOX_RUN_ID" "$status" \
    "$fetch_status" "$triage_status" "$enrich_status"

  exit "$status"
} 2>&1 | tee -a "$LOG_FILE" || run_status=$?

cleanup_logs
exit "$run_status"
