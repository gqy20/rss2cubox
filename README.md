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
```

## 4) 运行

```bash
python -m pip install -e ".[dev]"
rss2cubox
```

## 5) state.json 说明

- `sent`: 已推送条目（最终防重）
- `feed_cursor`: 每源时间游标（仅提速）
- `feed_failures`: 每源失败计数和熔断冷却状态

## 6) GitHub Actions

- 工作流：`.github/workflows/rss_to_cubox.yml`
- 每次运行会输出 `rss2cubox.log` artifact
- Step Summary 包含：阶段耗时、熔断跳过数、去重数、每源推送/丢弃统计
- 每次运行后会自动执行 `rss2cubox-export-web`，生成：
  - `web/public/data/updates.json`
  - `web/public/data/metrics.json`
- workflow 会把 `state.json` 和上述前端数据文件一起提交到 `main`

## 7) Vercel 前端（自动更新）

- 前端目录：`web/`
- 在 Vercel 创建项目时把 **Root Directory** 设为 `web`
- 每次 GitHub Action 推送新 commit 后，Vercel 会自动重新部署
- 页面读取 `web/public/data/*.json`，因此部署完成后就是最新数据

本地可单独导出前端数据：

```bash
rss2cubox-export-web
```

## 8) 测试

```bash
pytest -q
```
