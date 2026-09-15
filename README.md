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

**Bilibili 路由说明**：本项目使用自定义 fork 的 RSSHub（[gqy20/RSSHub](https://github.com/gqy20/RSSHub)），包含以下改进：
- `video-browser` 路由：使用 Puppeteer 渲染页面提取视频数据，绕过 Bilibili API 的 WBI 签名反爬
- 修复标题提取逻辑：解决部分 UID 返回空结果的问题

feeds.txt 中的 Bilibili 路由使用 `/bilibili/user/video-browser/:uid` 格式。

## 3) 必要环境变量

```bash
export IC_API_URL="http://ic.nexus.tashan.ac.cn/api/v1/articles/batch"
```

可选常用：

```bash
export IC_SOURCE_TYPE="gqy"
export MAX_ITEMS_PER_RUN="500"           # 单次运行总上限
export FEED_FETCH_CONCURRENCY="4"
export FEED_CONNECT_TIMEOUT_SECONDS="3"
# ⚠️ 不要调小：/juejin/* 这类抓取型路由在健康实例上实测要 19~28s，
# 设成 10s 会直接杀掉它们。黑洞实例靠下面的启动预检治，不靠 read timeout。
export FEED_READ_TIMEOUT_SECONDS="30"
export FEED_FAILURE_COOLDOWN_SECONDS="60"
export FEED_FAILURE_COOLDOWN_MAX_SECONDS="1800"
export FEED_CURSOR_LOOKBACK_HOURS="24"

# RSSHub 实例池调度
export RSSHUB_FAILURE_COOLDOWN_SECONDS="900"      # 实例级基础冷却
export RSSHUB_FAILURE_COOLDOWN_MAX_SECONDS="3600" # 指数退避封顶
export RSSHUB_MAX_CANDIDATES="5"                  # 单条路由最多试几个实例（0=不限）
export RSSHUB_PREFLIGHT_ENABLED="true"            # 抓取前并发探活，消除冷启动惊群
export RSSHUB_PREFLIGHT_TIMEOUT_SECONDS="5"

# 停用结构性失效的源（token: twitter / bilibili / werss / default）
# 这些源不是“暂时挂了靠熔断发现”，而是配置上就拿不到数据，
# 每轮都轮一遍候选实例纯属烧时间。修好后删 token 即可恢复，feeds.txt 不用改。
export FEED_SECTIONS_DISABLE="twitter,bilibili,werss"

# Agent SDK 分析（基于 Claude Agent SDK）
export ANTHROPIC_AUTH_TOKEN="sk-..."     # 网关走 Authorization: Bearer
export ANTHROPIC_BASE_URL="https://your-gateway"
export ANTHROPIC_MODEL="your-model-id"
export ENRICH_AGENT_ENABLED="true"
export ENRICH_MAX_WORKERS="10"          # 并发工作数
export ENRICH_ITEM_TIMEOUT_SECONDS="90"  # 单条目超时
export ENRICH_MAX_BUDGET_USD="0.15"     # 单条目最大预算
```

### 实例熔断与失败分级

实例级冷却按**连续**失败次数指数退避（`RSSHUB_FAILURE_COOLDOWN_SECONDS × 2^(n-1)`，
封顶 `RSSHUB_FAILURE_COOLDOWN_MAX_SECONDS`），再乘上一个按失败原因分级的倍率
（见 `feed_sources.COOLDOWN_REASON_MULTIPLIER`）。分级的依据是“这次失败能不能说明实例坏了”：

| 原因 | 倍率 | 说明 |
|---|---|---|
| `route` (403/404) | **0**（不冷却） | 路由需认证或不存在，换实例也没用，冷却只会误伤好实例 |
| `timeout` | 0.2 | ambiguous：很可能只是路由慢（实测 juejin 要 19~28s），靠 streak 阶梯逐步升级 |
| `parse` | 0.5 | 200 但内容不可解析，通常是实例返回了错误页 |
| `connection` / `http5xx` / `preflight` | 1.0 | 主机不可达 / 网关故障 / 探活失败，实例确实坏了 |
| `ratelimit` (429) | 2.0 | 是我们自己打太狠，必须狠退避 |

一次成功会重置退避阶梯（`fail_streak`），但保留累计失败次数（`fail_count`），
所以实例排序用的 `_score = success - fail` 语义不变。

> 调优依据：2026-09-15 对同一组 14 条 rsshub 路由的对比实测。
> 改动前 131s / 56 次失败请求 / 13 条成功；改动后均值 34.2s / 12.7 次失败 / 12.7 条成功。
> 最大的单项收益不是缩短超时，而是**摘掉黑洞实例**（`hub.slarker.me` 35s 无响应，
> 单个实例占掉失败总耗时的 41.9%）+ **启动预检**消除冷启动惊群。
> 注意不要提高 `FEED_FETCH_CONCURRENCY` 来“提速”：部分超时是我们自己的并发
> 打在公共实例上造成的限流（`rsshub.rssforever.com` 单发探测 200/2.7s，跑批时却多次超时）。

根目录 `.env` 会在启动 `rss2cubox` 时自动加载。

> ⚠️ **`.env` 的优先级高于系统环境变量**，会覆盖你在 shell 里 `export` 的同名变量。
> `runner.py` 的 `_load_local_env_file()` 是无条件 `os.environ[key] = value`，
> `enrich_agent.py` / `daily_report_agent.py` / `prediction_loop_runner.py` 则用 `load_dotenv(override=True)`。
> 所以临时改配置请直接改 `.env`，`export` 不会生效。

## 4) 运行

### 用 Makefile（推荐）

```bash
make up       # 一次性准备环境：起 PostgreSQL 容器 + 装依赖 + 建表（幂等）
make dev      # 一次性启动前后端：DB + 后端跑一次 + 前端 dev server（Ctrl-C 全部退出）
make run      # 只跑一次后端 pipeline
make web      # 只起前端 dev server（http://localhost:3424）
make doctor   # 体检：DB / LLM 网关 / IC / RSS 源连通性
make help     # 全部命令
```

本地 PostgreSQL 跑在专用容器 `rss2cubox-pg`（`postgres:17-alpine`，宿主端口 **5434**），
不与其他项目的数据库实例混用。表结构由 `scripts/init_local_db.py` 幂等创建。

常用覆盖：

```bash
make dev RUN_ON_DEV=0     # 只起前端，不跑后端
make run RUN_VIA_SH=1     # 走 run_local_sync.sh（含 flock + 预测闭环）
make db PG_PORT=5435      # 换宿主端口
```

### 直接用 uv

```bash
uv sync
uv run rss2cubox
```

本地定时运行可使用脚本：

```bash
chmod +x scripts/run_local_sync.sh
scripts/run_local_sync.sh
```

安装到系统 crontab：

```bash
chmod +x scripts/install_local_cron.sh
scripts/install_local_cron.sh
```

默认会安装为每 3 小时运行一次：

```cron
0 */3 * * * /home/qy113/workspace/project/2604/rss2cubox/scripts/run_local_sync.sh
```

可通过环境变量调整频率：

```bash
RSS2CUBOX_CRON_SCHEDULE="0 8,20 * * *" scripts/install_local_cron.sh
```

脚本会使用 `flock` 防止并发重入，并写入：

```text
logs/cron/YYYY-MM-DD/HH-MM-SS.log
logs/runs/YYYY-MM-DD/HH-MM-SS.jsonl
```

每次 cron 触发会通过同一个执行脚本依次运行：

```text
RSS 同步 / enrich / global_agent：每次触发都运行
signal_cluster_agent：默认每 24 小时运行一次
trend_prediction_agent：默认每 168 小时运行一次
prediction_review_agent：默认每 24 小时运行一次
```

预测闭环仍在同一个 `run_local_sync.sh` 中执行，但内部用本地 marker 控制各阶段频率，避免 cron 每 3 小时触发时重复生成预测。可通过环境变量调整：

```bash
PREDICTION_CLUSTER_INTERVAL_HOURS=24
PREDICTION_GENERATE_INTERVAL_HOURS=168
PREDICTION_REVIEW_INTERVAL_HOURS=24
RSS2CUBOX_FORCE_PREDICTION_LOOP=true
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

## 10) 政策信源子系统

独立于主 RSS 链路的政策文件抓取，用于中国国家级 / 省级 / 市级政策监测。

**为什么和主链路分开**：两者的抓取语义不同（RSS/Atom feed vs HTML 列表页），
打分标尺也不同（主链路的 `enrich_agent` prompt 是围绕"AI 与智能体领域"硬编码的，
`signal_type` / `market_stage` 是科技产品视角，拿去量法规文件会失真）。
独立的配置文件、独立的表、独立的入口，删掉 `src/rss2cubox/policy/` 不会留下残留。

```bash
make policy           # 抓取并入库（配置见 policy_sources.toml）
make policy-triage    # 预筛：标题批量打分，筛出 AI 相关的
make policy-enrich    # 预筛 + 逐篇结构化抽取（会调 LLM，花钱）
make policy-dry       # 只抓不入库，验证选择器用
make policy-status    # 信源健康度 + 疑似失效站点
make policy-init      # 建表
```

也可直接调 runner 做更细的过滤：

```bash
uv run python -m rss2cubox.policy_runner --only beijing_zhengce,tc260_zqyj
uv run python -m rss2cubox.policy_runner --level province,city
uv run python -m rss2cubox.policy_runner --include-disabled   # 连 playwright 站点一起试
uv run python -m rss2cubox.policy_runner --status
uv run python -m rss2cubox.policy_runner --triage --triage-limit 200
uv run python -m rss2cubox.policy_runner --enrich-only --enrich-limit 20 --enrich-min-relevance 4
uv run python -m rss2cubox.policy_runner --enrich-only --no-fulltext   # 只用标题抽，便宜但质量低
```

### 三阶段流水线

```
fetch     列表页 → policy_documents（只有标题/链接/日期）
  ↓
triage    N 个标题打包一次 LLM 调用 → is_policy + ai_relevance(1-5)
  ↓        只对 triage_relevance ≥ POLICY_ENRICH_MIN_RELEVANCE 的放行
enrich    逐篇（带详情页正文）→ 完整政策本体字段
```

**为什么必须有 triage 这一层**：deep enrich 是逐篇一次 LLM 调用（实测 ~$0.14/篇，
~25s/篇）。而政策源里混着大量民生通知（停水、月票、招考、活动报道）——
实测 442 篇里**只有 12% 的 AI 相关度 ≥3**。

| | 篇数 | 成本（CLI 记账值） |
|---|---|---|
| 不做预筛直接 enrich | 442 | ~$62 |
| 先预筛再 enrich | 53 | ~$7.4 + 预筛 ~$3 |

triage 用标题批量判断，10 条一批（实测 20 条会偏激进、出现
`error_max_structured_output_retries`，50 条直接撞超时）。

注意 triage 和 enrich 的打分可能不一致，这是**正常的且有用的**：triage 只看标题，
enrich 看正文。实测有文档 triage 给 4 分、enrich 看完正文降到 2 分
（标题像 AI 专项、实际是泛数字经济规划）——以 enrich 的结果为准。

### 政策本体

enrich 输出的字段与主链路的科技媒体视角完全分开：

| 字段 | 说明 |
|---|---|
| `issuing_authority` / `document_number` | 发布机构 / 文号（如「网安秘字〔2026〕118号」）|
| `jurisdiction` | 管辖范围 |
| `instrument_type` | 按中国法律位阶：法律 > 行政法规 > 部门规章/地方性法规 > 地方政府规章 > 规范性文件 > 指导意见；另有征求意见稿/技术标准/规划/通知公告/司法解释 |
| `stage` | 征求意见 / 已发布 / 已生效 / 已修订 / 已废止 / 不明 |
| `effective_date` / `comment_deadline` | 生效日 / 征求意见截止日（**窗口期是预测价值最高的字段**）|
| `affected_parties` | 适用主体，如「生成式AI服务提供者」 |
| `obligation_level` | 强制 / 推荐 / 自愿 / 不适用 |
| `ai_relevance` + `ai_relevance_reason` | 1-5 分，评分标准写死在 prompt 里，triage 与 enrich 共用同一套 |
| `source_quote` | **schema required**，原文逐字引句。这是防幻觉的锚点，人工抽查时能立刻判断模型是不是在编 |
| `confidence` | 只有标题没正文时代码会强制压到 ≤2（prompt 说了模型不一定听）|

实测 24 篇的字段完整度：`source_quote` 24/24、`issuing_authority` 24/24、
`document_number` 11/24（合理，不是所有文件都有文号），平均 confidence 3.0~5.0。

### 加一个站点

只改 `policy_sources.toml`，不用改代码：

```toml
[[sites]]
key           = "suzhou_zcfg"        # 唯一标识
name          = "苏州市-政策文件"
level         = "city"               # national | province | city
region        = "苏州"
list_url      = "https://www.suzhou.gov.cn/szsrmzf/zfwj/zcfg.shtml"
item_selector = "ul.infolist > li"   # CSS，命中列表项容器
title_selector = "a"                 # 相对 item；广东站是 "span.name > a"
title_attr    = "title"              # 优先取该属性，取不到回退到文本
date_selector = "span"               # 留空则从 item 全文正则提取日期
tier          = "requests"           # requests | playwright（JS 空壳站用后者）
max_items     = 120
title_exclude = ["查看更多", "新闻发布会"]   # 标题命中任一子串即丢弃
```

选择器怎么找：抓一次页面，找"同时含 `<a href>` 和日期"的 `<li>`，看它的父容器。
`make policy-dry` 会报 `raw_items`（选择器命中数）和 `items`（过滤后），
两者对不上就是选择器或过滤条件的问题。

### 失效监测

爬虫最危险的不是抓不到，而是**静默失效**：政府网站改版 → 选择器命中 0 项 →
不报错 → 你以为"最近没有新政策"。所以 `policy_source_state` 记录每个站点的
`consecutive_empty_runs`，达到 `POLICY_STALE_EMPTY_RUNS`（默认 2）就告警，
并区分失效类型（修复动作不同）：

| status | 含义 | 怎么办 |
|---|---|---|
| `parse_error` + `selector_matched_nothing` | 选择器一项都没命中，站点改版了 | 重新找选择器，改 TOML |
| `empty` + `all_N_items_filtered` | 命中了列表项但全被过滤 | 检查 `min_title_length` / `title_exclude` |
| `http_error` + `http_403/412` | 被反爬拦了 | 换 UA、换栏目路径，或改走 playwright |
| `timeout` / `fetch_error` | 网络层问题 | 看是不是站点挂了或需要 playwright |

`make policy-status` 和 `make doctor`（第 8 节）都会报疑似失效的站点。

### 已知状态（2026-09-15 实测）

- **可用（7 个）**：中国政府网国务院信息（tier=rss，60 条）、TC260 征求意见、
  北京最新政策（300 条）、上海政府规章、浙江政策解读、广东全部文件、苏州政策文件。
  一次全量抓取约 2s，共 442 条。
- **苏州的坑**：`/szsrmzf/zfwj/zcfg.shtml` 页面上并列多个列表，`ul.infolist` 是时政要闻
  （实测仅 13/50 是政策），真正的政策列表是 `ul.index-jgfk-list`（征求意见反馈，7/9）
  和 `ul.index-tzgg-list`（通知公告，10/16）。改用组合选择器后噪音率从 67% 降到 29%。
  **cssselect 支持逗号组合选择器，所以一个站点可以取多个容器，不需改引擎。**
- **JS 空壳，需 playwright（配置里已 `enabled=false`）**：江苏政策解读（requests
  只拿到 1KB）、杭州信息公开、广东政策解读。
- **抓不到**：深圳 `sz.gov.cn` SSLError；国务院政策文件库 403；国家药监局 412（反爬）。
- **反直觉的一点**：中央部委站点（工信部 2KB、发改委 54B、司法部 119B、
  市场监管总局 3.5KB）几乎全是 JS 空壳，而**地方站点多为服务端渲染**，
  所以地方政策的抓取成本比中央部委低。
- **另一个反直觉的点**：本机出口是美国加州 IP，但能直连 gov.cn / cac / miit / pbc
  （200，<0.7s）。所以公共 RSSHub 实例对 `/gov/*` 路由返回 503 **不是因为境外 IP 被墙**，
  而是那些路由自己失效了。自建 RSSHub 不一定比公共实例好，除非去改路由实现。

### 还没做的部分

- **算法备案清单**（beian.cac.gov.cn）：我认为的最高价值源 —— 官方口径的行业名录，
  含算法名称/主体/应用场景/备案号，能直接回答“谁在做智能体”。527B 的 JS 空壳，
  需 playwright；很可能有后端 JSON 接口，用浏览器看 network 面板比解析 DOM 稳得多。
- **LLM 抽取降级**：`scrape_site(llm_extractor=...)` 扩展点已留好
  （CSS 解析出 0 条时调用），但还没接 agent。接上后站点改版不会直接变成零数据。
- **前端展示**：`store.get_policy_documents()` 已支持按 level/region/site_key/
  未 enrich 过滤，可以直接作为 API route 的数据源。
- **征求意见的闭环验证**：`comment_deadline` 已经在抽了，但还没做到期跟踪。
  这是与主链路 `trend_prediction_agent` + `prediction_review_agent` 结合最自然的点：
  “征求意见稿第 X 条 → 预测最终稿会怎么改”是有明确验证点的可证伪预测。
