#!/usr/bin/env bash
# 安装/卸载政策信源的 crontab 条目。
#
# 与 install_local_cron.sh 分开，因为两者节奏不同：
#   主链路    每 3 小时（科技媒体更新快）
#   政策信源  每天 2 次（政府站点更新慢，但征求意见窗口期短，不能太久不看）
#
# 用法:
#   scripts/install_policy_cron.sh                 # 安装（默认 30 7,19 * * *）
#   POLICY_CRON_SCHEDULE="0 8 * * *" scripts/install_policy_cron.sh
#   scripts/install_policy_cron.sh --uninstall     # 只卸载本条目，不动主链路
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_SCRIPT="$ROOT_DIR/scripts/run_policy_sync.sh"
CRON_SCHEDULE="${POLICY_CRON_SCHEDULE:-30 7,19 * * *}"
CRON_MARKER="# rss2cubox policy sync"
CRON_LINE="$CRON_SCHEDULE $RUN_SCRIPT $CRON_MARKER"

ACTION="install"
if [ "${1:-}" = "--uninstall" ] || [ "${1:-}" = "-u" ]; then
  ACTION="uninstall"
fi

tmp_file="$(mktemp)"
trap 'rm -f "$tmp_file" "$tmp_file.next"' EXIT

if crontab -l >"$tmp_file" 2>/dev/null; then
  :
else
  : >"$tmp_file"
fi

if [ "$ACTION" = "uninstall" ]; then
  if ! grep -Fq "$CRON_MARKER" "$tmp_file"; then
    printf 'crontab 里没有政策信源条目，无需卸载\n'
    exit 0
  fi
  # 只删带本 marker 的行，主链路条目（# rss2cubox local sync）保持不动
  grep -Fv "$CRON_MARKER" "$tmp_file" >"$tmp_file.next" || true
  crontab "$tmp_file.next"
  printf '已卸载政策信源 cron（marker: %s）\n' "$CRON_MARKER"
  exit 0
fi

if [ ! -x "$RUN_SCRIPT" ]; then
  chmod +x "$RUN_SCRIPT"
fi

if grep -Fq "$CRON_MARKER" "$tmp_file"; then
  sed -i "\|$CRON_MARKER|c\\$CRON_LINE" "$tmp_file"
  printf 'Updated '
else
  {
    cat "$tmp_file"
    printf '%s\n' "$CRON_LINE"
  } >"$tmp_file.next"
  mv "$tmp_file.next" "$tmp_file"
  printf 'Installed '
fi

crontab "$tmp_file"

printf 'rss2cubox policy cron:\n%s\n\n' "$CRON_LINE"
printf '当前 crontab 里与本项目的条目：\n'
crontab -l 2>/dev/null | grep -F 'rss2cubox' || printf '  （无）\n'
printf '\n提示：\n'
printf '  日志      logs/policy/YYYY-MM-DD/HH-MM-SS.log\n'
printf '  锁文件    .rss2cubox-policy.lock（与主链路互不阻塞）\n'
printf '  关掉 enrich（省钱，只抓取+预筛）：在 crontab 行前加 POLICY_CRON_ENRICH=false\n'
