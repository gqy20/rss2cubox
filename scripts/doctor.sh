#!/usr/bin/env bash
# 本地环境体检：逐项检查 rss2cubox 跑起来需要的外部依赖。
# 用法: make doctor   或   bash scripts/doctor.sh
# 退出码: 0 = 全部通过, 1 = 有 FAIL 项（WARN 不影响退出码）

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 读取 .env（.env 覆盖已有环境变量，与 runner.py 行为一致）
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

PASS=0; WARN=0; FAIL=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
sec()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

mask() {  # 隐去密钥中段
  local v="$1"
  if [ ${#v} -le 12 ]; then printf '%s***' "${v:0:4}"; else printf '%s…%s' "${v:0:8}" "${v: -4}"; fi
}

echo "════════════════════════════════════════════════"
echo "  rss2cubox 环境体检"
echo "════════════════════════════════════════════════"

# ── 1. 基础工具 ───────────────────────────────────────────────
sec "1. 基础工具"
for tool in uv docker node npm curl; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool  $(command -v "$tool")"
  else
    bad "$tool 未安装"
  fi
done
if [ -x .venv/bin/python ]; then
  ok ".venv  $(.venv/bin/python -V 2>&1)"
else
  bad ".venv 不存在 —— 执行 make deps"
fi

# ── 2. LLM 网关 ───────────────────────────────────────────────
sec "2. LLM 网关 (Claude Agent SDK)"
if [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  ok "ANTHROPIC_AUTH_TOKEN  $(mask "$ANTHROPIC_AUTH_TOKEN")"
else
  bad "ANTHROPIC_AUTH_TOKEN 未设置"
fi
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  warn "ANTHROPIC_API_KEY 仍然设置着 —— 会同时发送 X-Api-Key 和 Authorization 两个凭据头，建议只留 AUTH_TOKEN"
fi
BASE="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"
MODEL="${ANTHROPIC_MODEL:-}"
echo "     base_url = $BASE"
echo "     model    = ${MODEL:-(未设置)}"
if [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  resp=$(curl -s -m 15 -o /tmp/.doctor_models -w '%{http_code}' \
    -H "Authorization: Bearer $ANTHROPIC_AUTH_TOKEN" "$BASE/v1/models" 2>/dev/null)
  if [ "$resp" = "200" ]; then
    ok "GET /v1/models  HTTP 200"
    if [ -n "$MODEL" ]; then
      if grep -q "\"$MODEL\"" /tmp/.doctor_models 2>/dev/null; then
        ok "模型 '$MODEL' 在网关列表中"
      else
        bad "模型 '$MODEL' 不在网关返回的列表里 —— 确认拼写（网关 ID 大小写敏感）"
      fi
    fi
  else
    bad "GET /v1/models  HTTP $resp —— 密钥或 base_url 有问题"
  fi
  # 真实打一次 messages，验证 tool_use 链路
  if [ -n "$MODEL" ]; then
    ping=$(curl -s -m 40 "$BASE/v1/messages" \
      -H "Authorization: Bearer $ANTHROPIC_AUTH_TOKEN" \
      -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
      -d "{\"model\":\"$MODEL\",\"max_tokens\":16,\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}" 2>/dev/null)
    if echo "$ping" | grep -q '"type":"message"'; then
      ok "POST /v1/messages 可正常返回"
    else
      bad "POST /v1/messages 失败: $(echo "$ping" | head -c 160)"
    fi
  fi
fi
rm -f /tmp/.doctor_models

# ── 3. PostgreSQL ─────────────────────────────────────────────
sec "3. PostgreSQL (DATABASE_URL)"
if [ -z "${DATABASE_URL:-}" ]; then
  warn "DATABASE_URL 未设置 —— 文章/洞察/报告都不会落库（代码会 warning 后跳过）"
else
  # 解析端口与库名
  hostport=$(printf '%s' "$DATABASE_URL" | sed -E 's#.*@([^/]+)/.*#\1#')
  dbname=$(printf '%s' "$DATABASE_URL" | sed -E 's#.*/([^?]+).*#\1#')
  echo "     $hostport / $dbname"
  if docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -q "rss2cubox-pg"; then
    ok "容器 rss2cubox-pg 在运行"
  else
    warn "容器 rss2cubox-pg 未运行 —— 执行 make db"
  fi
  # 真实连接测试
  if [ -x .venv/bin/python ]; then
    conn=$(DATABASE_URL="$DATABASE_URL" .venv/bin/python - <<'PY' 2>&1
import os, psycopg
try:
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=8) as c:
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'")
        print(f"OK:{cur.fetchone()[0]}")
except Exception as e:
    print(f"ERR:{type(e).__name__}: {str(e).splitlines()[0][:120]}")
PY
)
    case "$conn" in
      OK:*)  n="${conn#OK:}"
             if [ "$n" -eq 0 ]; then
               warn "连接成功但 public schema 里 0 张表 —— 执行 make db-init"
             else
               ok "连接成功，已有 $n 张表"
             fi ;;
      ERR:*) bad "连接失败 ${conn#ERR:}" ;;
    esac
  fi
fi

# ── 4. IC 接口 ────────────────────────────────────────────────
sec "4. IC 文章库接口"
IC="${IC_API_URL:-}"
if [ -z "$IC" ]; then
  bad "IC_API_URL 未设置 —— 主链路无法导入"
else
  code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$IC" 2>/dev/null)
  # 该端点是 POST-only，GET 返回 405/422 都说明服务活着
  case "$code" in
    200|405|422) ok "IC_API_URL 可达 (GET → HTTP $code，POST-only 端点的正常表现)";;
    000)         bad "IC_API_URL 不可达（DNS/网络/超时）: $IC";;
    *)           warn "IC_API_URL 返回 HTTP $code，需人工确认: $IC";;
  esac
  echo "     IC_SOURCE_TYPE=${IC_SOURCE_TYPE:-(未设置)}  IC_PUSH_ENABLED=${IC_PUSH_ENABLED:-(未设置)}"
  if [ "${IC_PUSH_ENABLED:-}" = "false" ]; then
    warn "IC_PUSH_ENABLED=false —— 跑完不会真正推送到 IC（本地调试通常是有意的）"
  fi
fi

# ── 5. RSS 源 ─────────────────────────────────────────────────
sec "5. RSS 抓取源"
for var in WERSS_BASE_URL RSSHUB_PRIVATE_INSTANCES; do
  url="${!var:-}"
  if [ -z "$url" ]; then
    warn "$var 未设置"
    continue
  fi
  code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$url" 2>/dev/null)
  case "$code" in
    000)     bad  "$var 不可达: $url";;
    5*)      bad  "$var HTTP $code —— 服务端异常: $url";;
    200|301|302|404) ok "$var HTTP $code: $url";;
    *)       warn "$var HTTP $code: $url";;
  esac
done
if [ -f feeds.txt ]; then
  n=$(grep -cvE '^\s*(#|$|\[)' feeds.txt 2>/dev/null || echo 0)
  ok "feeds.txt 存在，约 $n 个订阅源"
else
  bad "feeds.txt 不存在"
fi

# ── 6. 前端 ───────────────────────────────────────────────────
sec "6. 前端 (web/)"
if [ -d web ]; then
  if [ -d web/node_modules ]; then ok "web/node_modules 已安装"; else warn "web 依赖未装 —— make deps"; fi
  if [ -f web/.env.local ]; then
    ok "web/.env.local 存在"
    web_db=$(grep -oP '^DATABASE_URL=\K.*' web/.env.local 2>/dev/null || true)
    if [ -n "$web_db" ] && [ -n "${DATABASE_URL:-}" ] && [ "$web_db" != "$DATABASE_URL" ]; then
      bad "web/.env.local 的 DATABASE_URL 与根 .env 不一致"
      echo "       web : $web_db"
      echo "       root: $DATABASE_URL"
    elif [ -n "$web_db" ]; then
      ok "web 与 root 的 DATABASE_URL 一致"
    fi
  else
    warn "web/.env.local 不存在（可从 web/.env.example 复制）"
  fi
  # 端口占用
  if ss -ltn 2>/dev/null | grep -q ":3424 "; then
    warn "端口 3424 已被占用 —— 可能已有 dev server 在跑"
  else
    ok "端口 3424 空闲"
  fi
else
  warn "web/ 目录不存在"
fi

# ── 7. 配置卫生 ───────────────────────────────────────────────
sec "7. 配置卫生"
if [ -f .env ]; then
  if grep -qE '^channel_binding=' .env; then
    warn ".env 里有孤立的 channel_binding= —— 这是 Neon 连接串的碎片，代码 0 引用，建议删"
  fi
  if grep -qE '^API_SOURCE=' .env; then
    warn ".env 里有 API_SOURCE= —— 只有 web 前端读它，放在根 .env 无效"
  fi
fi
if [ ! -f .tashan ]; then
  ok ".tashan 不存在（密钥只在 .env 里，符合预期）"
elif git check-ignore -q .tashan 2>/dev/null; then
  ok ".tashan 已被 .gitignore 覆盖"
else
  bad ".tashan 含明文密钥但没被 .gitignore 覆盖 —— 有被 git add 的风险"
fi
if [ -f .env ] && ! git check-ignore -q .env 2>/dev/null; then
  bad ".env 没被 .gitignore 覆盖 —— 含明文密钥"
else
  ok ".env 已被 .gitignore 覆盖"
fi
if crontab -l 2>/dev/null | grep -q rss2cubox; then
  ok "crontab 已安装定时任务"
else
  echo "  · crontab 未安装（可选：make cron-install）"
fi

# ── 8. 政策信源 ─────────────────────────────────
sec "8. 政策信源子系统"
if [ ! -f policy_sources.toml ]; then
  warn "policy_sources.toml 不存在"
elif [ -x .venv/bin/python ] || command -v uv >/dev/null 2>&1; then
  polinfo=$(DATABASE_URL="${DATABASE_URL:-}" uv run python - <<'PY' 2>&1
from rss2cubox.policy import config as cfg, store
try:
    all_sites = cfg.load_sources("policy_sources.toml", include_disabled=True)
    on = [s for s in all_sites if s.enabled]
    print(f"SITES {len(on)}/{len(all_sites)}")
    for lvl in ("national", "province", "city"):
        n = sum(1 for s in on if s.level == lvl)
        if n:
            print(f"LEVEL {lvl} {n}")
    pw = [s.key for s in on if s.tier == "playwright"]
    if pw:
        print("PW " + ",".join(pw))
except Exception as e:
    print(f"CFGERR {type(e).__name__}: {e}")
    raise SystemExit
states = store.get_source_states()
if not states:
    print("NORUN")
else:
    docs = store.get_policy_documents(limit=1)
    stale = store.get_stale_sources(min_empty_runs=2)
    okc = sum(1 for s in states if s.get("last_status") == "ok")
    print(f"STATE {okc}/{len(states)}")
    if stale:
        print("STALE " + ",".join(f"{s['site_key']}({s['consecutive_empty_runs']})" for s in stale))
PY
)
  case "$polinfo" in
    *CFGERR*) bad "policy_sources.toml 解析失败: $(echo "$polinfo" | grep CFGERR | sed 's/^CFGERR //')" ;;
    *)
      sites_line=$(echo "$polinfo" | grep '^SITES' | head -1)
      if [ -n "$sites_line" ]; then
        ok "配置合法，启用 ${sites_line#SITES }（启用/总数）"
        echo "     分级: $(echo "$polinfo" | grep '^LEVEL' | awk '{printf "%s=%s ", $2, $3}')"
      fi
      echo "$polinfo" | grep -q '^NORUN' && warn "还没有抓取记录 —— 执行 make policy"
      st=$(echo "$polinfo" | grep '^STATE' | head -1)
      [ -n "$st" ] && ok "上次抓取: ${st#STATE } 个站点状态 ok"
      sl=$(echo "$polinfo" | grep '^STALE' | head -1)
      if [ -n "$sl" ]; then
        bad "疑似失效站点（连续空跑≥2次）: ${sl#STALE } —— 极可能是改版，需更新选择器"
      fi
      pw=$(echo "$polinfo" | grep '^PW' | head -1)
      [ -n "$pw" ] && warn "已启用的 playwright 站点（慢）: ${pw#PW }"
      ;;
  esac
fi

# ── 汇总 ──────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════"
printf "  \033[32m通过 %d\033[0m   \033[33m警告 %d\033[0m   \033[31m失败 %d\033[0m\n" "$PASS" "$WARN" "$FAIL"
echo "════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ] || exit 1
