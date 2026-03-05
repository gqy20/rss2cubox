# rss2cubox

将 RSS 订阅同步到 Cubox，支持 RSSHub 路由、并发抓取、AI 过滤和去重。

## 1) feeds.txt

```txt
[rsshub]
/sspai/index
/anthropic/news

[direct]
https://openai.com/news/rss.xml
https://status.anthropic.com/history.rss
```

- `[rsshub]` 写路由（`/x/y` 或 `rsshub://x/y`）
- `[direct]` 写完整 URL
- 支持空行和 `#` 注释

## 2) rsshub_instances.txt

每行一个实例 URL，例如：

```txt
https://hub.slarker.me
https://rsshub.pseudoyu.com
```

## 3) 必要环境变量

```bash
export CUBOX_API_URL="https://cubox.pro/c/api/save/..."
```

可选常用：

```bash
export CUBOX_FOLDER="RSS Inbox"
export MAX_ITEMS_PER_RUN="20"            # 单次运行总上限
export FEED_FETCH_CONCURRENCY="4"
export FEED_CONNECT_TIMEOUT_SECONDS="5"
export FEED_READ_TIMEOUT_SECONDS="10"
export FEED_FAILURE_COOLDOWN_SECONDS="60"
export FEED_FAILURE_COOLDOWN_MAX_SECONDS="1800"
export RSSHUB_FAILURE_COOLDOWN_SECONDS="300"
export FEED_CURSOR_LOOKBACK_HOURS="24"

# AI 过滤（不需要可留空）
export ANTHROPIC_AUTH_TOKEN=""
export ANTHROPIC_BASE_URL="https://api.anthropic.com"
export ANTHROPIC_MODEL=""
export AI_MIN_SCORE="0.6"
export AI_TIMEOUT_SECONDS="90"
export AI_RETRY_ATTEMPTS="3"
export AI_RETRY_BACKOFF_SECONDS="1.5"
export AI_BATCH_SIZE="5"
export AI_MAX_CANDIDATES="40"

# AI 深化分析（可选，基于 Claude Agent SDK）
export ENRICH_AGENT_ENABLED="true"      # 启用深化分析
export ENRICH_MIN_SCORE="0.85"          # 深化分析最低分数
export ENRICH_MAX_ITEMS="200"           # 每批次最大条目数
export ENRICH_MAX_WORKERS="10"          # 并发工作数
export ENRICH_ITEM_TIMEOUT_SECONDS="90"  # 单条目超时
export ENRICH_MAX_BUDGET_USD="0.15"     # 单条目最大预算
export ENRICH_ALLOW_WEBFETCH_FALLBACK="false"

# 全局洞察分析（可选）
export GLOBAL_AGENT_ENABLED="true"
export GLOBAL_AGENT_MIN_SCORE="0.85"
export GLOBAL_AGENT_MIN_ITEMS="5"
export GLOBAL_AGENT_MAX_TURNS="100"
export GLOBAL_AGENT_TIMEOUT_SECONDS="600"
export GLOBAL_AGENT_MAX_BUDGET_USD="5.0"
export GLOBAL_AGENT_ENABLE_SKILLS="true"

# Web（Vercel）导出到 Cubox：用于加密 HttpOnly cookie
export CUBOX_COOKIE_SECRET="replace-with-a-long-random-secret"
```

## 4) 运行

```bash
python -m pip install -e ".[dev]"
rss2cubox
```

## 5) 数据文件职责

- `state.json`
  - `sent`: 已推送条目（防重复推送到 Cubox）
  - `feed_cursor`: 每源时间游标（增量抓取）
  - `feed_failures`: 每源失败计数与熔断状态
- `run_events.jsonl`
  - 本次运行的逐条处理结果（pushed/dropped/failed）
- `web/public/data/updates_history.jsonl`
  - 前端历史数据池（由 `run_events.jsonl` 增量合并）

## 6) GitHub Actions

- 工作流：`.github/workflows/rss_to_cubox.yml`
- 每次运行会输出 `rss2cubox.log` artifact
- Step Summary 包含：阶段耗时、熔断跳过数、去重数、每源推送/丢弃统计
- 每次运行后会自动执行 `rss2cubox-export-web`，生成：
  - `run_events.jsonl`
  - `web/public/data/updates_history.jsonl`
  - `web/public/data/updates.json`
  - `web/public/data/metrics.json`
- workflow 会把上述数据文件提交到 `main`

## 7) Vercel 前端（自动更新）

- 前端目录：`web/`
- 在 Vercel 创建项目时把 **Root Directory** 设为 `web`
- 每次 GitHub Action 推送新 commit 后，Vercel 会自动重新部署
- 页面读取 `web/public/data/*.json`，因此部署完成后就是最新数据

本地可单独导出前端数据：

```bash
rss2cubox-export-web
```

## 8) Cubox Key 保存位置（本地 / 云端）

当前 Web 端不会把 Cubox Key 写入数据库或服务器文件。

- 保存介质：浏览器 `HttpOnly` Cookie
  - Cookie 名：`cubox_key_v1`
  - 过期时间：7 天
  - 属性：`HttpOnly`、`SameSite=Lax`、`Path=/`
  - 生产环境（HTTPS）自动带 `Secure`
- Cookie 内不是明文，使用服务端密钥加密（AES-256-GCM）
  - 服务端环境变量：`CUBOX_COOKIE_SECRET`（必需）

云端（Vercel）行为：

- Key 仍在用户浏览器 Cookie 中，不在 Vercel 数据库中持久化
- API 请求时，Vercel 函数读取并解密 Cookie，再调用 Cubox API
- 必须在 Vercel 项目配置 `CUBOX_COOKIE_SECRET`
- 不同域名（如 preview/production）Cookie 不共享，需分别配置

本地开发：

- 在 `web/.env.local` 配置 `CUBOX_COOKIE_SECRET`
- 修改后需重启 `npm run dev`
