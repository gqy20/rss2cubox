# 运维与调优

面向维护者的技术细节。用户视角的说明见 [README](../README.md)。

- [架构职责](#架构职责)
- [环境变量完整参考](#环境变量完整参考)
- [RSSHub 实例池调度](#rsshub-实例池调度)
- [政策信源子系统](#政策信源子系统)
- [成本核算](#成本核算)
- [运行与定时](#运行与定时)
- [日志](#日志)
- [部署](#部署)
- [历史迁移与审计脚本](#历史迁移与审计脚本)
- [排查手册](#排查手册)

---

## 架构职责

- 当前主链路：RSS → Agent SDK → `ic`（正式文章库，通过 `IC_API_URL` 批量导入）
- 全局洞察 → `global_insights`（`global_agent` 生成的趋势、弱信号、行动建议）
- 政策链路独立：`policy_sources.toml` → `policy_documents` / `policy_source_state`
- Legacy：旧 `processed_items` / `run_events` 仅保留给历史迁移、兼容和排障

去重基线：**本地 PostgreSQL 优先，`ic` 是回退**。`load_ic_state()` 的第一行是
`load_local_state()`，本地库非空就直接返回，不会请求 IC。所以 `IC_PUSH_ENABLED=false`
时跨轮去重依然有效。

---

## 环境变量完整参考

`.env` 是带注释的模板见 [.env.example](../.env.example)。这里只记**调优时容易踩的坑**。

### `.env` 的优先级高于 shell

`runner.py` 的 `_load_local_env_file()` 是无条件 `os.environ[key] = value`，
`enrich_agent.py` / `daily_report_agent.py` / `prediction_loop_runner.py` 用
`load_dotenv(override=True)`。

所以在终端 `export FOO=bar` **不会生效**，临时改配置必须改 `.env`。
自己写脚本读环境变量时也要注意：用 `setdefault` 会被 shell 里的旧值污染
（本机 shell profile 里就导出着一套已废弃的 bigmodel 凭据）。

### 抓取超时：read 不能调小

```bash
FEED_CONNECT_TIMEOUT_SECONDS=3    # connect 可以短，死主机快速失败
FEED_READ_TIMEOUT_SECONDS=30      # ⚠️ 不要调小
```

`/juejin/*` 这类抓取型路由在**健康**实例上实测要 19~28s：

```
/juejin/posts/2858385963484488   19402ms  ktachibana.party
/juejin/posts/2250051536050763   26377ms  ktachibana.party
/juejin/posts/3782764966460398   27779ms  ktachibana.party
```

曾试图 30 → 10 来压缩慢失败，结果成功路由从 13/14 掉到 8/14——**提速是靠丢数据换的**。
黑洞实例（连上了但永不响应）要靠启动预检治，不是靠 read timeout。

### 不要靠提高并发来提速

```bash
FEED_FETCH_CONCURRENCY=10    # 不要调大
```

`rsshub.rssforever.com` 单发探测 200 / 2.7s 完全健康，但跑批时多次 31s 超时——
**部分超时是我们自己的并发打在公共实例上造成的限流**。加并发只会更糟。

### 预算参数是单条上限，不是总量上限

`ENRICH_MAX_BUDGET_USD` / `GLOBAL_AGENT_MAX_BUDGET_USD` 等是按**单次 Agent 调用**
传给 SDK 的，拦不住整轮总花费。控总量要靠 `MAX_ITEMS_PER_RUN`。

---

## RSSHub 实例池调度

### 实例清单

`rsshub_instances.txt` 每行一个实例，**顺序即优先级**，按实测成功率排。
`RSSHUB_PRIVATE_INSTANCES` 里的私有实例会被插到最前面。

**Bilibili 路由**：使用自定义 fork 的 RSSHub（[gqy20/RSSHub](https://github.com/gqy20/RSSHub)）：
- `video-browser` 路由用 Puppeteer 渲染页面提取视频数据，绕过 B 站 WBI 签名反爬
- 修复标题提取逻辑，解决部分 UID 返回空结果

所以 `feeds.txt` 里的 B 站路由用 `/bilibili/user/video-browser/:uid` 格式，
且**只有私有实例和 `rss.spriple.org` 能服务**。两者都挂时这批路由无实例可用。

### 熔断与失败分级

实例级冷却按**连续**失败次数指数退避：

```
cooldown = RSSHUB_FAILURE_COOLDOWN_SECONDS × 2^(连续失败次数-1) × reason倍率
           封顶 RSSHUB_FAILURE_COOLDOWN_MAX_SECONDS
```

`reason` 倍率的依据是「这次失败能不能说明实例坏了」（见 `COOLDOWN_REASON_MULTIPLIER`）：

| reason | 倍率 | 判定依据 |
|---|---|---|
| `route` (403/404) | **0（不冷却）** | 路由需认证或不存在，换实例也没用，冷却只会误伤好实例 |
| `timeout` | 0.2 | ambiguous——很可能只是路由慢（见上面 juejin 的数据），靠 streak 阶梯逐步升级 |
| `parse` | 0.5 | 200 但内容不可解析，通常是实例返回了错误页 |
| `connection` / `http5xx` / `preflight` | 1.0 | 主机不可达 / 网关故障 / 探活失败，实例确实坏了 |
| `ratelimit` (429) | 2.0 | 是我们自己打太狠，必须狠退避 |

一次成功会重置退避阶梯（`fail_streak`），但保留累计失败次数（`fail_count`），
所以排序用的 `_score = success - fail` 语义不变。

### 启动预检

`RSSHUB_PREFLIGHT_ENABLED=true` 时，抓取前先并发探活所有实例，死的预先打上冷却。

这是为了消除**冷启动惊群**：N 个并发路由同时启动时冷却表还是空的，会一起撞向
同一个坏实例。实测每个坏实例的失败次数 ≈ `FEED_FETCH_CONCURRENCY`。预检本身只花 1.5s。

探活判据是「拿到任意非 5xx 响应就算活」——探的是实例在不在，不是路由能不能用，
所以 404/403 也算活。

### 候选实例上限

`RSSHUB_MAX_CANDIDATES=5`。单条路由最多试几个实例，0 = 不限制。
bilibili/twitter 的专用实例**不受此上限挤压**，否则这些路由会直接无实例可用。

### 调优效果（实测）

同一组 14 条 rsshub 路由，改动后跑 3 次取均值：

| | 耗时 | 成功路由 | 失败请求 | timeout 类 |
|---|---|---|---|---|
| 改动前 | 131.0s | 13/14 | 56 | 23 |
| 改动后 | **34.2s（3.8×）** | 12.7/14 | **12.7（-77%）** | 0.7 |

且没有任何一条改动前成功的路由在三次运行中全部失败。

最大的单项收益**不是缩短超时**，而是摘掉黑洞实例（`hub.slarker.me` 35s 无响应，
单个实例占掉失败总耗时的 41.9%）+ 启动预检消除惊群。

调优后主要失败原因变成 `ratelimit`(429)——把最好的实例排到最前，负载就集中到
头部两个实例上了。如果 429 继续增多，下一步应该给实例选择加轮转/抖动，而不是继续调冷却。

---

## 政策信源子系统

独立于主 RSS 链路。独立的配置文件、独立的数据表、独立的入口，
删掉 `src/rss2cubox/policy/` 不会在主链路留下残留。

**为什么分开**：抓取语义不同（RSS/Atom vs HTML 列表页），打分标尺也不同——
主链路 `enrich_agent` 的 prompt 围绕「AI 与智能体领域」硬编码，`signal_type` /
`market_stage` 是科技产品视角，拿去量法规文件会失真。

### 三阶段流水线

```
fetch     列表页/RSS → policy_documents（标题、链接、日期）
  ↓
triage    N 个标题打包一次 LLM 调用 → is_policy + ai_relevance(1-5)
  ↓        只对 triage_relevance ≥ POLICY_ENRICH_MIN_RELEVANCE 的放行
enrich    逐篇（带详情页正文）→ 完整政策本体字段
```

**为什么必须有 triage**：deep enrich 是逐篇一次调用（实测 ~25s/篇）。
而政策源里混着大量民生通知。实测 442 篇预筛后的分布：

```
相关度 1: 307 (69.5%)   2: 82 (18.6%)   3: 30   4: 10   5: 13
→ 只有 53 篇 (12%) 达到 ≥3
```

| | 篇数 | 成本 |
|---|---|---|
| 不做预筛直接 enrich | 442 | ~¥60 |
| 先预筛再 enrich | 53 | ~¥7 + 预筛 ~¥3 |

triage 的 batch size 实测边界：**10 条稳定；20 条偏激进**（会出现
`error_max_structured_output_retries`）；**50 条直接撞满超时**。

triage 与 enrich 打分不一致是正常且有用的：triage 只看标题，enrich 看正文。
实测有文档 triage 给 4、enrich 看完正文降到 2（标题像 AI 专项、实为泛数字经济规划）。
**以 enrich 为准**，这是两阶段设计在自我纠错。

### 政策本体

| 字段 | 说明 |
|---|---|
| `issuing_authority` / `document_number` | 发布机构 / 文号（如「网安秘字〔2026〕118号」）|
| `jurisdiction` | 管辖范围 |
| `instrument_type` | 按中国法律位阶：法律 > 行政法规 > 部门规章/地方性法规 > 地方政府规章 > 规范性文件 > 指导意见；另有 征求意见稿/技术标准/规划/通知公告/司法解释 |
| `stage` | 征求意见 / 已发布 / 已生效 / 已修订 / 已废止 / 不明 |
| `effective_date` / `comment_deadline` | 生效日 / 征求意见截止日（**窗口期是预测价值最高的字段**）|
| `affected_parties` | 适用主体，如「生成式AI服务提供者」|
| `obligation_level` | 强制 / 推荐 / 自愿 / 不适用 |
| `ai_relevance` + `ai_relevance_reason` | 1-5 分，评分标准写死在 prompt 里，triage 与 enrich 共用同一套 |
| `source_quote` | **schema required**，原文逐字引句 |
| `confidence` | 只有标题没正文时代码强制压到 ≤2 |

防幻觉设计：`source_quote` 是 required，必须逐字复制原文，人工抽查时能立刻判断
模型是不是在编。实测 24 篇：`source_quote` 24/24、`issuing_authority` 24/24、
`document_number` 11/24（合理，不是所有文件都有文号）、平均 confidence 3.0~5.0。

有一篇因「正文仅说明编制主体与背景，未给出框架具体条款」自动把 confidence 压到 2、
`key_provisions` 给空数组——保守性按设计生效。

### 加一个站点

只改 `policy_sources.toml`：

```toml
[[sites]]
key            = "suzhou_zcfg"
name           = "苏州市-政策文件"
level          = "city"                # national | province | city
region         = "苏州"
list_url       = "https://www.suzhou.gov.cn/szsrmzf/zfwj/zcfg.shtml"
item_selector  = "ul.index-jgfk-list > li, ul.index-tzgg-list > li"
title_selector = "a"                   # 相对 item；广东站是 "span.name > a"
title_attr     = "title"               # 优先取该属性，取不到回退到文本
date_selector  = "span"                # 留空则从 item 全文正则提取
tier           = "requests"            # requests | playwright | rss
max_items      = 120
title_exclude  = ["查看更多", "年度报表"]
```

**选择器怎么找**：抓一次页面，找「同时含 `<a href>` 和日期」的 `<li>`，看它的父容器。
`make policy-dry` 会报 `raw_items`（选择器命中数）和 `items`（过滤后），
两者对不上就是选择器或过滤条件的问题。

**cssselect 支持逗号组合选择器**，所以一个站点可以取多个容器，不需要改引擎。

**tier=rss** 用于站点自带的原生 feed（走 feedparser，不需要 `item_selector`）。

### 失效监测

爬虫最危险的不是抓不到，而是**静默失效**：政府网站改版 → 选择器命中 0 项 →
不报错 → 误以为「最近没有新政策」。所以 `policy_source_state` 记录每个站点的
`consecutive_empty_runs`，达到 `POLICY_STALE_EMPTY_RUNS`（默认 2）就告警。

status 严格区分四类，因为修复动作完全不同：

| status | 含义 | 怎么办 |
|---|---|---|
| `parse_error` + `selector_matched_nothing` | 一项都没命中，站点改版了 | 重新找选择器，改 TOML |
| `empty` + `all_N_items_filtered` | 命中了列表项但全被过滤 | 检查 `min_title_length` / `title_exclude` |
| `http_error` + `http_403/412` | 被反爬拦了 | 换 UA、换栏目路径，或改走 playwright |
| `timeout` / `fetch_error` | 网络层问题 | 看是不是站点挂了或需要 playwright |

`make policy-status` 和 `make doctor`（第 8 节）都会报疑似失效的站点。

### 已知站点状态（2026-09-15 实测）

**可用（7 个）**：中国政府网国务院信息（tier=rss，60 条）、TC260 征求意见、
北京最新政策（300 条）、上海政府规章、浙江政策解读、广东全部文件、苏州政策文件。
一次全量抓取约 2s，共 442 条。

**苏州的坑**：`/szsrmzf/zfwj/zcfg.shtml` 页面上并列多个列表，`ul.infolist` 是时政要闻
（实测仅 13/50 是政策），真正的政策列表是 `ul.index-jgfk-list`（征求意见反馈 7/9）
和 `ul.index-tzgg-list`（通知公告 10/16）。改用组合选择器后噪音率 67% → 29%。

**JS 空壳，需 playwright（已 `enabled=false`）**：江苏政策解读（requests 只拿到 1KB）、
杭州信息公开、广东政策解读。

**抓不到**：深圳 `sz.gov.cn` SSLError；国务院政策文件库 403；国家药监局 412（反爬）。

**两个反直觉的实测发现**：

1. 中央部委站点（工信部 2KB、发改委 **54B**、司法部 119B、市场监管总局 3.5KB）
   几乎全是 JS 空壳，而**地方站点多为服务端渲染**（苏州 152KB/234 链接、
   北京 230KB、广东 51KB）。所以地方政策的抓取成本比中央部委低。
2. 本机出口是美国加州 IP，但能直连 gov.cn / cac / miit / pbc（200，<0.7s）。
   所以公共 RSSHub 实例对 `/gov/*` 路由返回 503 **不是境外 IP 被墙**，
   而是那些路由自己失效了（选择器过时 / 被反爬 / 需要 puppeteer 而公共实例没开）。
   **这意味着「自建 RSSHub 就能解决」不成立**，除非去改路由实现。

### 还没做的部分

- **算法备案系统**（beian.cac.gov.cn）：最高价值源——官方口径的行业名录，
  含算法名称/主体/应用场景/备案号，能直接回答「谁在做智能体」。527B 的 JS 空壳，
  需 playwright；很可能有后端 JSON 接口，用浏览器看 network 面板比解析 DOM 稳。
- **LLM 抽取降级**：`scrape_site(llm_extractor=...)` 扩展点已留好
  （CSS 解析出 0 条时调用），agent 未接。接上后站点改版不会直接变成零数据。
- **详情页全文抓取**：enrich 阶段已接 `fulltext_fetcher.fetch_full_text()`
  （三级降级 trafilatura → playwright → 微信）。
- **前端展示**：`store.get_policy_documents()` 已支持按 level/region/site_key/
  未 enrich 过滤，可直接作为 API route 的数据源。
- **征求意见的闭环验证**：`comment_deadline` 已在抽取，但没做到期跟踪。
  这是与主链路 `trend_prediction_agent` + `prediction_review_agent` 结合最自然的点：
  「征求意见稿第 X 条 → 预测最终稿会怎么改」是有明确验证点的可证伪预测。

### 一个特意没做的设计

没有加「全局标题正则白名单」来过滤噪音。数据表明那会**误杀 TC260**——
《人工智能安全治理框架3.0》这类标准标题本来就不含「通知/办法」等词，
该站点关键词命中率只有 50% 却全是最高价值内容。正确做法是修选择器，
而不是加一个会误伤的过滤器。

### 全文抓取的预算陷阱

三级降级 trafilatura(L1) → playwright(L2) → 微信(L3)，各级预算由
`FULLTEXT_ITEM_TIMEOUT_S`（下称 T）推导：

```
L1 = min(10, T//3)     L2 = min(20, T//2)     L3 = min(15, T//2)
```

**两个反直觉的点：**

1. **L2 硬封顶 20s**，把 T 调到 60、90、120 都不会给 L2 更多时间。
2. **playwright 的内部耗时必须显著小于 L2 的外层预算**。内部是
   `launch(~2s) + page.goto(PLAYWRIGHT_NAVIGATION_TIMEOUT_S) + RENDER_EXTRA_WAIT_S`，
   而默认 `nav=15`、`wait=2` → 内部≈19s vs 外层 20s，**余量为零**。
   只要有一点并发争抢，`_fetch_with_timeout` 就会在 playwright 完成前砍掉它，
   而且被丢弃的子线程会继续持有浏览器。

实测后果：一次完整运行里 22 次全文尝试 **0 成功**，而同样的 URL 在隔离测试里
有 60% 成功率。修法是代码层把 `PLAYWRIGHT_NAVIGATION_TIMEOUT_S` 自动钳制到
`_L2_TIMEOUT_S * 0.5`、`RENDER_EXTRA_WAIT_S` 钳制到 `* 0.1`，让错误配置无法成立。
钳制后实测 **39/40 = 98% 成功，吞吐 38 篇/分钟**（修前真实运行是 2 篇/分钟），
且前半段 95% / 后半段 100%，**无时间退化**。

> 排查这段时先怀疑过两个错误方向，都被数据否定：
> - “资源耗尽”——机器 314GB 内存（289GB 可用）、72 核、负载 9.7，不成立
> - “chromium 进程泄漏自我放大”——停止运行后 chrome 进程 33→15，
>   而 4~5 个并发浏览器本来就有 ~24 个子进程，量级对得上，不是泄漏
>
> 能这么快定位到真因，靠的是把 `all_levels_failed` 拆成
> `l1=timeout>10s | l2=no_content` 这种分级错误——**超时和“跑完但抽不到正文”
> 是两个完全不同的问题**，混在一个笼统错误里时根本分不出来。

另外：`FULLTEXT_MAX_WORKERS` 不要调大。每个 URL 都会 `chromium.launch()` 一次，
10 并发 = 10 个浏览器同时起，争抢会把 L2 推过预算。

### 单源限流

`MAX_ITEMS_PER_SOURCE`（默认 60）。候选按 feed priority 降序排后截取，
而各 feed 候选量差异极大（实测 vercel 1578、openai 1193、clickhouse 881），
不限流时一个 priority=5 的高产源就能吃光整轮预算：实测一次 1500 篇的运行里
**93% 的全文抓取都打在 openai.com 上，只有 3 个域名参与**。

限流后同样 1500 篇覆盖 **74 个源、44 个域名**，单源最多 60 条。
高优先级源仍然优先入选（保持排序遍历），只是不再能独占。

`run_summary` 里的 `sources_selected` 可以直接看多样性。

---

## 中断与恢复（durability）

一轮完整运行要几小时，中断是常态而不是异常。这里有三个已经踩过的坑。

### 两阶段写入

```
phase 1  fetch → 抓全文 → save_articles(_raw_articles)     ← 原文 + 全文先落盘
phase 2  enrich → 结果攒在内存 analyses → 整轮结束再 save_articles
```

phase 1 先写是为了**先保住全文**（抓全文很贵，而 enrich 可能失败）。
副作用是：中断后库里会有一批只有原文、没有分析结果的行。

### 坑 1：去重基线曾把裸文章也算成已处理

`get_all_article_ids()` 原本是 `SELECT id FROM articles`，不区分是否已 enrich。
配合 phase 1 先写库，后果是：**运行只要在 phase 1 之后被中断（约第 10 分钟），
这一整批文章就永久进入去重集、再也不会被 enrich**。实测三次中断留下了
1501 篇这样的文章。

现在 `get_all_article_ids(enriched_only=True)` 只算 `reason` / `actionable` /
`hidden_signal` 任一非空的行（对齐 `sync_pipeline.has_signal_analysis`，
`core_event` 不是表字段），`load_local_state()` 在 `ENRICH_AGENT_ENABLED` 为真时启用它。

**这个修复是自愁的**：之前被错误占位的行因为没 enrich 字段，会自动重新变成候选，
不需要手工清理。enrich 关闭时沿用旧语义，避免每轮重复处理同一批。

### 坑 2：enrich 结果曾全程只在内存

`enrich_agent.py` 对数据库零引用，`analyze_candidates_with_agent` 只 `return analyses`。
一轮 1500 篇要跑 5~6 小时，在第 1499 篇时被杀就全丢。

现在支持**增量落库**：`analyze_candidates_with_agent(on_item_done=...)` 在每篇成功后
回调，runner 侧缓冲到 `ENRICH_FLUSH_EVERY`（默认 25）篇就写一次库，收尾再 flush 一次。

- 回调用 `anyio.to_thread.run_sync` 执行，不堵事件循环
- 回调异常被吞掉并记 `enrich_flush_failed` + 计入 `flush_failed`，
  **落库失败不能让分析结果丢失**
- 写入用的是与 phase 2 完全相同的 `build_processed_article` + `save_articles`，
  后者是 upsert，所以 phase 2 重跑幂等
- `ENRICH_FLUSH_EVERY=0` 可关闭增量落库

配合坑 1 的修复，中断后重跑会自动跳过已 enrich 的、只补未完成的。

### 坑 3：全文回补曾是“全有或全无”

```python
if not _pre_ft and _db_url:        # 旧：只要本轮抓到了一篇，剩下缺的就不回补
```

实测一次运行抓到 1473/1500，剩下 27 篇即使库里有历史全文也被跳过
（日志 `fulltext_recovered_from_db=0` 印证）。现在改成**只查缺失的 eid 并合并**，
事件里会报 `missing` 和 `recovered` 两个数。

### phase 2 会不会把全文覆盖掉？

不会，但值得记下为什么：`build_processed_article`（phase 2 用）**不产出 `full_text` 字段**，
而 `ON CONFLICT DO UPDATE` 里三个全文列用的是 `COALESCE(EXCLUDED.x, articles.x)`。
**COALESCE 只防 NULL、不防空串**，而 phase 1 写的是 `... or ""` —— 看似会被覆盖。
实际安全是因为 `save_articles` 用 `_optional_text()` 把空串归一化成了 `None`：

```python
"full_text": _optional_text(article.get("full_text")),
# _optional_text: text = str(value or "").strip(); return text or None
```

三种场景实测均安全：phase2 不带该键 / 显式传 `''` / 传 `None`，全文都保住。
但这个安全性**依赖于 `_optional_text` 的行为**，改它时要连带看 COALESCE。

---

## 成本核算

### 为什么不能信 SDK 报的金额

`claude_agent_sdk` 的 `total_cost_usd` 是 CLI 按**它自己的 Claude 定价表**算的。
走第三方网关时那个金额与真实账单毫无关系：

```
实测一次调用：input 38071 tok / output 51 tok
  CLI 报      $0.114978
  网关真实    ¥0.00534 ≈ $0.00073
  → 高估 164 倍
```

### 单价表是本地文件

`model_pricing.json`，**默认路径不联网**。价格很少变动，本地维护比每次去拉网关
更简单可靠（不受网关鉴权方式变化影响，且可进版本库 review）。

```bash
make cost                                      # 核算最新一次运行
make cost COST_ARGS="logs/runs/2026-09-16/*.jsonl"
make cost-pricing                              # 查看单价表
make cost-refresh                              # 唯一联网的命令：重拉并覆写 JSON
```

计费公式（new-api 约定）：

```
quota = input_tokens × model_ratio + output_tokens × model_ratio × completion_ratio
金额  = quota / quota_per_unit       # 500000，单位见 currency（本部署是 CNY）
美元  = 金额 / usd_exchange_rate     # 7.3
```

当前生产模型 `deepseek-v4-flash-aistar`：`model_ratio=0.07`、`completion_ratio=2`
→ **输入 ¥0.14/M tok，输出 ¥0.28/M tok**。

`agent_sdk_runner` 现在会把 `usage` 和 `model_usage` 一起记进 JSONL——
没有 token 数就无法换算真实成本，只记 `total_cost_usd` 等于把唯一有用的数据丢了。

### 基线实测（2026-09-16，`MAX_ITEMS_PER_RUN=50`）

```
运行时间      18 分钟（完整链路：fetch → enrich → push → global_agent）
agent 调用    51 次（50 enrich + 1 global_agent）
输入 token    5,318,485    平均 104,284 / 次
输出 token    85,154       平均 1,670 / 次
真实成本      ¥0.7684 ≈ $0.105
CLI 报的      $17.23       （高估 164×）
```

线性外推 `MAX_ITEMS_PER_RUN=1500`：**约 ¥23（$3.2）、约 6.5~7 小时**。

**结论：成本不是瓶颈，时间才是。** 单轮 6.5h 已大于 6h 的 cron 间隔，`flock`
会跳过重叠触发，实际变成背靠背连续跑。首轮之后 `feed_cursor`（每源记
`MAX(publish_time)`）+ 24h lookback + 本地 `articles` 去重会大幅减少候选量，
稳态远比首轮便宜——但清空 12,539 条积压需要约 9 轮。

### 不要用网关账单接口测成本

`/dashboard/billing/usage` 是**账号级累计值**，共享网关上背景噪音极大：
实测 18 分钟涨了 12730 单位，而本次运行只花约 385 单位——**噪音是信号的 33 倍**。
只能用 token × 单价算。

### 输入 token 是主要开销

平均 **10.4 万 input tok/次**，因为 Claude Code 每次调用都会带上完整 system prompt
+ 工具 schema。真要优化，方向是**纯抽取类任务不走 Agent SDK 而直接调 messages 接口**，
而不是调 batch size 或并发。

---

## 运行与定时

### 手动运行

```bash
uv run rss2cubox                              # 主链路单次
scripts/run_local_sync.sh                     # 含 flock + 预测闭环 + JSONL 日志
uv run python -m rss2cubox.policy_runner      # 政策链路
```

`policy_runner` 的参数：

```bash
--only beijing_zhengce,tc260_zqyj    # 只跑指定站点
--level province,city                # 只跑指定级别
--include-disabled                   # 连 enabled=false 的站点一起试
--dry-run                            # 只抓不入库
--status                             # 只看信源健康度
--triage --triage-limit 200          # 只跑预筛
--enrich-only --enrich-limit 20      # 只跑深度抽取
--enrich-min-relevance 4             # 提高抽取门槛
--no-fulltext                        # 不抓详情页正文（便宜但质量低）
```

### 定时任务

两条链路**分开两个 cron**，因为节奏不同：主链路每 6 小时（科技媒体更新快），
政策线每天 2 次（政府站点更新慢，但征求意见窗口期短，不能太久不看）。

| | 脚本 | 默认 | 锁 | 日志 |
|---|---|---|---|---|
| 主链路 | `scripts/run_local_sync.sh` | `0 */6 * * *` | `.rss2cubox-local.lock` | `logs/cron/YYYY-MM-DD/` |
| 政策 | `scripts/run_policy_sync.sh` | `30 7,19 * * *` | `.rss2cubox-policy.lock` | `logs/policy/YYYY-MM-DD/` |

两把锁独立，互不阻塞。日志保留 30 天。

主链路间隔为什么是 6 小时而不是 3：单轮可能跑数小时，间隔小于单轮时长时
`flock` 会跳过重叠触发，实际变成背靠背连续跑。

政策 cron 的成本控制：每次默认只 enrich `POLICY_CRON_ENRICH_LIMIT=10` 篇且要求
相关度 ≥3，单次上限约 ¥1.5。`POLICY_CRON_ENRICH=false` 可只跑抓取+预筛。

`run_policy_sync.sh` 把三个阶段分开执行并分别记录退出码，汇总成
`policy_cron_complete`，从日志能直接看出是哪一步挂了。

### Makefile 与脚本级开关

这些不是应用环境变量（不进 `.env`），而是 `make` 和脚本的调用参数：

| 变量 | 默认 | 作用于 |
|---|---|---|
| `PG_CONTAINER` | `rss2cubox-pg` | 本地 PostgreSQL 容器名 |
| `PG_PORT` | `5434` | 孿主端口。例：`make db PG_PORT=5435` |
| `PG_IMAGE` | `postgres:17-alpine` | 镜像 |
| `PG_USER` / `PG_PASSWORD` / `PG_DB` | `postgres` / `postgres` / `rss2cubox` | 容器初始化凭据 |
| `LOCAL_DB_URL` | 由上面四项拼成 | make 会把它显式传给子进程，绕过 `.env` 里的值。指向别的库时用这个，不用改 `.env` |
| `WEB_PORT` | `3424` | 前端端口（仅展示用，实际由 `web/package.json` 的 `next dev --port` 决定）|
| `RUN_ON_DEV` | `1` | `make dev` 是否顺带跑一次后端。`make dev RUN_ON_DEV=0` = 只起前端 |
| `RUN_VIA_SH` | `0` | `make run` 是否走 `run_local_sync.sh`（1 = 含 flock + 预测闭环）|
| `POLICY_ARGS` | 空 | 透传给 `policy_runner` 的参数。例：`make policy POLICY_ARGS="--only tc260_zqyj"` |
| `COST_ARGS` | 空 | 透传给 `agent_cost.py`。例：`make cost COST_ARGS="logs/runs/2026-09-16/*.jsonl"` |
| `RSS2CUBOX_CRON_SCHEDULE` | `0 */6 * * *` | 主链路 cron 表达式 |
| `POLICY_CRON_SCHEDULE` | `30 7,19 * * *` | 政策线 cron 表达式 |
| `POLICY_CRON_ENRICH` | `true` | 政策 cron 是否跑 deep enrich（`false` = 只抓取+预筛，不花钱）|
| `POLICY_CRON_ENRICH_LIMIT` | `10` | 政策 cron 单次最多 enrich 多少篇 |
| `POLICY_CRON_MIN_RELEVANCE` | `3` | 政策 cron 的 enrich 相关度门槛 |
| `POLICY_CRON_TRIAGE_LIMIT` | `300` | 政策 cron 单次最多预筛多少篇 |
| `RSS2CUBOX_LOG_RETENTION_DAYS` | `30` | 主链路日志保留天数 |
| `POLICY_LOG_RETENTION_DAYS` | `30` | 政策日志保留天数 |

改 cron 频率不用改脚本：

```bash
RSS2CUBOX_CRON_SCHEDULE="0 8,20 * * *" scripts/install_local_cron.sh
POLICY_CRON_SCHEDULE="0 9 * * *"       scripts/install_policy_cron.sh
```

两个 install 脚本都是幂等的（重复执行是 update 而非追加），且各自支持精确卸载：

```bash
scripts/install_policy_cron.sh --uninstall   # 只删政策条目，主链路幸存
make cron-uninstall                          # 只删主链路条目
```

### 预测闭环的频率控制

预测闭环在 `run_local_sync.sh` 内执行，用本地 marker（`.rss2cubox-prediction-loop/`）
控制各阶段频率，避免每次 cron 触发都重复生成预测：

```bash
PREDICTION_CLUSTER_INTERVAL_HOURS=24
PREDICTION_GENERATE_INTERVAL_HOURS=168
PREDICTION_REVIEW_INTERVAL_HOURS=24
RSS2CUBOX_FORCE_PREDICTION_LOOP=true    # 强制全部阶段立即执行
```

cluster 产出新结果会级联触发 generate（删 marker 使其立即 due）。

---

## 日志

本地和 CI 都输出 JSONL 结构化事件。

关键字段：

- `run_id`：一次运行的稳定 ID，本地形如 `local-YYYYMMDDTHHMMSSZ`，政策线是 `policy-cron-...`
- `stage`：`fetch` / `enrich` / `push` / `global_agent` / `policy_fetch` / `policy_triage` / `policy_enrich`
- `event`：`run_start` / `enrich_done` / `run_summary` / `policy_source_scraped` / ...
- `eid`：文章稳定 ID（政策线用 `doc_id`）

`enrich_done` 额外记录：`duration_ms`、`content_source`、`importance_score`、
`signal_type`、`evidence_type`、`evidence_strength`、`novelty_score`、
`impact_horizon`、`market_stage`、`confidence`、`cluster_hint`。

`agent_sdk_result` 记录：`total_cost_usd`（**Claude 价，不代表真实账单**）、
`usage`、`model_usage`（含各模型 token 数，`make cost` 靠这个算真实成本）、
`num_turns`、`subtype`、`is_error`、`stop_reason`。

⚠️ `run_summary` 里的 `pushed` / `push_attempted` 统计的是**写入本地库的文章数**，
与是否推送到 IC 无关（赋值在 `if IC_PUSH_ENABLED` 之外）。判断有没有真推 IC
要看有没有 `ic_push_skipped` 事件。

---

## 部署

### GitHub Actions

- `ci.yml` —— push / PR 触发，只跑测试
- `rss_to_ic.yml` —— schedule（`0 */3 * * *`）+ workflow_dispatch，**不在 push 时触发**
- `rss_to_ic_test.yml` —— 仅 workflow_dispatch

⚠️ **本仓库的 Actions 当前是整体禁用状态**（`gh api repos/.../actions/permissions`
返回 `{"enabled": false}`）。最后一次运行是 2026-06-10，且此前连续多次 failure。
所以云端定时不会跑，**本地 cron 是唯一路径**。

另外 CI 装依赖用的是 `pip install .[dev]`，只解析 `[project.optional-dependencies]`。
**PEP 735 的 `[dependency-groups]` 只有 uv 认、pip 不装**，所以测试依赖必须在
`pyproject.toml` 的两处都声明。

CI 的 `ANTHROPIC_AUTH_TOKEN` / `BASE_URL` / `MODEL` 全部来自 GitHub Secrets。
换网关后必须去 repo Settings → Secrets 更新，否则 CI 仍走旧供应商。
两个 workflow 里都还有 `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}`
这行（等于 CI 也是两个凭据头都发），可以删掉与本地保持一致。

### Vercel 前端

- 前端目录 `web/`，Vercel 的 **Root Directory** 设为 `web`
- 页面服务端读取：`ic`（文章列表）、`global_insights`（洞察卡片）
- 聚合入口：`web/lib/signalStore.ts`
- 必要环境变量：`IC_API_URL`、`NEON_DATABASE_URL`（仅用于读 `global_insights`）
- 本地开发：`make web`，端口 3424

`API_SOURCE` 只有前端读（`ic` 或 `local`），放在根 `.env` 里无效，
应配在 `web/.env.local`。

### 凭据：只设 ANTHROPIC_AUTH_TOKEN

网关走 `Authorization: Bearer`。**不要再同时设 `ANTHROPIC_API_KEY`**：

```js
// claude_agent_sdk 内置 CLI 的实际行为
async authHeaders(H){ return merge([await this.apiKeyAuth(H), await this.bearerAuth(H)]) }
async apiKeyAuth(H) { if (this.apiKey    == null) return; return [{"X-Api-Key": this.apiKey}] }
async bearerAuth(H) { if (this.authToken == null) return; return [{Authorization:`Bearer ${this.authToken}`}] }
```

两个都设 = **每个请求同时发两个凭据头**，不是二选一。

另外 `ANTHROPIC_API_KEY` 在**交互模式**下要过「自定义 key 人工批准」
（`customApiKeyResponses.approved` 里得有该 key 的哈希），而 `ANTHROPIC_AUTH_TOKEN`
无条件生效。headless/SDK 子进程是非交互模式，两者都直接生效，但手动跑 `claude`
时会被要求批准。所以网关场景统一用 `AUTH_TOKEN`。

> 注意 SDK 用的是它**自带的** CLI（`claude_agent_sdk/_bundled/claude`，2.1.121），
> 不是 PATH 里的 `~/.local/bin/claude`（2.1.195）。排查 CLI 行为时要看前者。

---

## 历史迁移与审计脚本

```bash
# 迁移旧 Neon processed_items 到 ic
uv run python scripts/legacy/migrate_processed_items_to_ic.py --dry-run
uv run python scripts/legacy/migrate_processed_items_to_ic.py

# 基于 run_events 回填 Bilibili 封面
uv run python scripts/legacy/backfill_bili_covers.py --dry-run --limit 20

# 审计 ic 中 gqy 数据质量
uv run python scripts/audit_ic_gqy_quality.py
```

数据文件职责：主流程去重基线来自本地 PG（回退到 `ic`），不再依赖 Neon
`processed_items`。旧 `state.json` / `run_events.jsonl` 仅保留给兼容逻辑和历史脚本。

---

## 排查手册

**先跑 `make doctor`**，它检查 8 组：基础工具、LLM 网关（含真实打一次
`/v1/messages`）、PostgreSQL、IC 接口、RSS 源、前端、配置卫生、政策子系统。

| 症状 | 排查 |
|---|---|
| Agent 调用 401/403 | `ANTHROPIC_AUTH_TOKEN` 与 `BASE_URL` 是否匹配同一网关；模型名是否与 `/v1/models` 返回的 id 完全一致（大小写敏感） |
| 模型报 not found | 网关返回的 `model` 字段可能是内部名（请求 `deepseek-v4-flash-aistar`、回包 `ds-v4-flash`），这是正常的；`model_pricing.json` 的 `aliases` 已处理 |
| `ModuleNotFoundError: rss2cubox` | `.venv` 是从别的目录拷来的，`__editable__*.pth` 指向已不存在的路径。`rm -rf .venv && uv sync --extra dev` |
| 大量 async 测试失败 | 缺 `pytest-asyncio`。测试依赖必须在 `pyproject.toml` 两处都声明 |
| 政策站点返回 0 条 | `make policy-status` 看 status：`parse_error` 是改版要换选择器，`http_403` 是被拦 |
| 政策 enrich 成功但没入库 | 看有没有 `policy_enrich_save_failed` 事件。常见原因是 DATE 列收到中文日期（已在 `_coerce_enriched` 里归一化） |
| 前端 3424 端口被占 | `npm run dev` 不会把 SIGINT 转发给 `next-server` 子进程。真实终端 Ctrl-C 没问题，但用 `timeout`/脚本包一层会残留。`make dev` 用 `trap 'kill 0'` 杀整个进程组，没这个问题 |
| shell 里 export 的变量不生效 | `.env` 优先级更高，见上文 |
