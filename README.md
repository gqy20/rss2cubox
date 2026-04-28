# rss2cubox

抓取 RSS，使用 Agent SDK 做文章分析，并批量导入信息库。

## 架构职责

- 当前主链路：
  - RSS -> Agent SDK -> `ic`
  - 全局洞察 -> Neon `global_insights`
- Legacy compatibility：
  - 旧 `processed_items` / `run_events` 仅保留给历史迁移、兼容和排障
- `ic`
  - 正式文章内容库
  - 通过 `IC_API_URL` 批量导入
- `global_insights`
  - 全局洞察结果表
  - 仅保存 `global_agent` 生成的趋势、弱信号、行动建议
  - 暂时仍保存在 Neon 中，不写入 `processed_items`

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
export IC_API_URL="http://ic.nexus.tashan.ac.cn/api/v1/articles/batch"
```

可选常用：

```bash
export IC_SOURCE_TYPE="gqy"
export MAX_ITEMS_PER_RUN="500"           # 单次运行总上限
export FEED_FETCH_CONCURRENCY="4"
export FEED_CONNECT_TIMEOUT_SECONDS="5"
export FEED_READ_TIMEOUT_SECONDS="10"
export FEED_FAILURE_COOLDOWN_SECONDS="60"
export FEED_FAILURE_COOLDOWN_MAX_SECONDS="1800"
export RSSHUB_FAILURE_COOLDOWN_SECONDS="300"
export FEED_CURSOR_LOOKBACK_HOURS="24"

# Agent SDK 分析（基于 Claude Agent SDK）
export ENRICH_AGENT_ENABLED="true"
export ENRICH_MAX_WORKERS="10"          # 并发工作数
export ENRICH_ITEM_TIMEOUT_SECONDS="90"  # 单条目超时
export ENRICH_MAX_BUDGET_USD="0.15"     # 单条目最大预算
```

根目录 `.env` 会在启动 `rss2cubox` 时自动加载；已存在的系统环境变量优先，不会被 `.env` 覆盖。

## 4) 运行

```bash
uv sync
uv run rss2cubox
```

本地定时运行可使用脚本：

```bash
chmod +x scripts/run_local_sync.sh
scripts/run_local_sync.sh
```

crontab 示例：

```cron
0 */3 * * * /home/qy113/workspace/project/2604/rss2cubox/scripts/run_local_sync.sh
```

脚本会使用 `flock` 防止并发重入，并写入：

```text
logs/cron/YYYY-MM-DD/HH-MM-SS.log
logs/runs/YYYY-MM-DD/HH-MM-SS.jsonl
```

## 5) 数据文件职责

- 当前主流程的去重基线来自 `ic`，不再依赖 Neon `processed_items`
- 旧 `state.json` / `run_events.jsonl` 说明主要保留给兼容逻辑和历史脚本参考

## 6) GitHub Actions

- 主工作流：`.github/workflows/rss_to_ic.yml`
- 快速测试：`.github/workflows/rss_to_ic_test.yml`
- 每次运行会输出 `rss2cubox.log` artifact
- Step Summary 包含：阶段耗时、熔断跳过数、去重数、每源处理统计

## 7) 日志

本地和 GitHub Actions 均会输出 JSONL 结构化事件。

关键字段：

- `run_id`：一次运行的稳定 ID，本地默认形如 `local-YYYYMMDDTHHMMSSZ`
- `stage`：运行阶段，例如 `fetch`、`enrich`、`push`、`global_agent`
- `event`：事件名，例如 `run_start`、`enrich_done`、`run_summary`
- `eid`：文章稳定 ID

`enrich_done` 会额外记录：

- `duration_ms`
- `content_source`
- `importance_score`
- `signal_type`
- `evidence_type`
- `evidence_strength`
- `novelty_score`
- `impact_horizon`
- `market_stage`
- `confidence`
- `cluster_hint`

## 8) Vercel 前端（自动更新）

- 前端目录：`web/`
- 在 Vercel 创建项目时把 **Root Directory** 设为 `web`
- 页面服务端直接读取：
  - `ic`：文章列表
  - Neon `global_insights`：洞察卡片
- 前端聚合入口：`web/lib/signalStore.ts`
- Vercel 需要至少配置：
  - `IC_API_URL`
  - `NEON_DATABASE_URL`（仅用于读取 `global_insights`）

## 9) 历史迁移与审计脚本

历史回填：迁移旧 Neon `processed_items` 到 `ic`：

```bash
uv run python scripts/legacy/migrate_processed_items_to_ic.py --dry-run
uv run python scripts/legacy/migrate_processed_items_to_ic.py
```

旧表排障：基于 `run_events` 回填 Bilibili 封面：

```bash
uv run python scripts/legacy/backfill_bili_covers.py --dry-run --limit 20
```

审计 `ic` 中 `gqy` 数据质量：

```bash
uv run python scripts/audit_ic_gqy_quality.py
```
