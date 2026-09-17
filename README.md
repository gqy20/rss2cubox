# rss2cubox

把散落在几百个信源里的 AI / 科技动态和中国政策文件，自动变成**可验证的信号判断**。

---

## 解决的问题

关注 AI 领域的人每天都在面对同样的困境：

- **看不完。** 237 个科技信源每天产出上万条内容，人工筛选不现实。
- **看完也提炼不出信号。** 单条新闻没有意义，趋势藏在几十条新闻的交集里。
- **判断无法验证。** 你说"这是趋势"，三个月后对不对？没人回头核对。
- **政策更抓不住。** 中国各级政府的政策文件散落在几十个网站上，而其中只有约 12% 与 AI 真正相关——剩下的是停水通知、月票办理、活动打卡。

这个项目把「采集 → 结构化 → 聚类 → 预测 → 复盘」整条链路自动化，并且**让判断可以被事后打分**。

## 它做什么

| 能力 | 说明 |
|---|---|
| **聚合** | 237 个科技信源（RSS/Atom + RSSHub 路由）+ 7 个政策信源（国家/省/市三级政府网站），自动抓取、去重、抓全文 |
| **结构化** | AI 逐篇抽取：重要性、信号类型、证据强度、新颖度、影响周期、关键实体、隐藏信号、可执行动作 |
| **聚类** | 把跨文章的同类信号聚成「信号簇」，而不是留下一堆孤立新闻 |
| **预测 + 复盘** | 对信号簇生成**可证伪**的预测（带验证窗口和证据门槛），到期自动复盘打分，并把复盘结论回喂给下一轮预测 |
| **政策监测** | 三级流水线：抓取 → 预筛（筛掉 88% 无关内容）→ 结构化抽取（管辖权/法规位阶/立法阶段/生效日期/适用主体/义务强度/原文引句） |
| **控制台** | Web 界面看信号流、趋势洞察、预测账本 |

最有价值的是第 4 项：大多数 RSS 工具止步于聚合，这里会**对自己的判断负责**——每条预测都有明确的验证窗口，到期由另一个 Agent 核对实际发生了什么并打分，低分预测的失败原因会作为 `improvement_advice` 影响下一轮生成。

## 你会得到什么

- **信号控制台** — `http://localhost:3424`，按日期/来源/标签浏览，支持全文搜索
- **每日报告** — 趋势、弱信号、行动建议
- **预测账本** — 历史预测、命中率、复盘评分与改进建议
- **政策库** — 结构化后的政策文件，可按地区/位阶/阶段/AI 相关度筛选
- **文章库** — 全部抓取内容含全文，存在本地 PostgreSQL

## 快速开始

```bash
cp .env.example .env      # 填 ANTHROPIC_AUTH_TOKEN / BASE_URL / MODEL 和 IC_API_URL
make up                   # 起 PostgreSQL 容器 + 装依赖 + 建表（幂等）
make doctor               # 体检：确认网关、数据库、信源都通
make run                  # 跑一次完整流水线
make dev                  # 起前端控制台
```

政策线是独立的：

```bash
make policy               # 抓取政策文件
make policy-triage        # 预筛出与 AI 相关的
make policy-enrich        # 结构化抽取（会调用 LLM）
make policy-status        # 看信源健康度
```

`make help` 列出全部命令。

## 日常使用

| 想做什么 | 命令 |
|---|---|
| 跑一次完整流水线 | `make run` |
| 跑流水线 + 预测闭环 | `make loop` |
| 起前端控制台 | `make web` |
| 前后端一起起 | `make dev` |
| 体检（网关/数据库/信源） | `make doctor` |
| 看这次运行花了多少钱 | `make cost` |
| 装定时任务 | `make cron-install` / `make policy-cron-install` |
| 看日志 | `make logs` |
| 跑测试 | `make test` |

首次使用建议先把 `.env` 里的 `MAX_ITEMS_PER_RUN` 调小（比如 50）试跑一次，确认耗时和产出符合预期再放大。

## 配置

三处配置，各管一件事：

**`feeds.txt`** — 科技信源清单

```txt
[rsshub]
5	/anthropic/news # Anthropic 新闻      ← 数字是优先级，tab 分隔
2	/sspai/index

[direct]
https://openai.com/news/rss.xml

[werss]
/feed/MP_WXS_xxx.rss
```

支持 `[rsshub]` / `[direct]` / `[werss]` 三个分段、`# 注释`、行首优先级数字、` # 标签` 行内备注。

**`policy_sources.toml`** — 政策信源清单（加站点只改这个文件，不用改代码）

**`.env`** — 运行参数（从 `.env.example` 复制）

`.env` 里**只放必填项和实际偏离默认值的调优结果**，等于默认值的不写。
全部 103 个配置项（名字、类型、默认值、说明）都在 `src/rss2cubox/config.py` 的
注册表里，用命令查看：

```bash
make config                 # 列出全部，● 标记被 .env 覆盖的
make config-help            # 同上，并显示每项说明
make doctor                 # 体检：顺带检查必填项是否缺失
```

> ⚠️ `.env` 的优先级**高于** shell 环境变量。临时改配置请直接改 `.env`，在终端 `export` 不会生效。
>
> 要改某个值的**默认行为**，改 `config.py` 而不是往 `.env` 里加一行——
> `tests/test_config_registry.py` 会强制注册表与代码默认值一致。

暂时不想抓某类源，用 `FEED_SECTIONS_DISABLE`（如 `twitter,bilibili,werss`）停用，不用删 `feeds.txt` 里的行。

## 部署

**定时运行**（本地）

```bash
make cron-install          # 主链路，默认每 6 小时
make policy-cron-install   # 政策线，默认每天 7:30 / 19:30
make cron-list             # 查看已装的条目
```

两条链路用独立的锁和日志目录，互不阻塞。

**前端**（Vercel）

前端在 `web/`，部署时把 Vercel 的 Root Directory 设为 `web`，配置 `IC_API_URL` 和 `NEON_DATABASE_URL`。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/operations.md](docs/operations.md) | **运维与调优**：完整环境变量参考、RSSHub 实例池调度、政策流水线细节、失效监测、成本核算、日志字段、故障排查 |
| [docs/prediction-loop.md](docs/prediction-loop.md) | 预测闭环的设计：实体模型、三个 Agent、可证伪性约束 |
| [docs/database.md](docs/database.md) | 数据库设计与表职责 |
| [docs/llms.txt](docs/llms.txt) | 给 LLM 看的项目摘要 |
| [.env.example](.env.example) | 带注释的完整配置模板 |

## 当前能力边界

**可用**：190 个 direct 科技源、47 个 RSSHub 路由、7 个政策源（中国国家/北京/上海/浙江/广东/苏州 + TC260）。

**暂不可用**（配置里已停用，不影响其余部分）：
- 60 个 Twitter 路由 —— 需要认证实例
- 36 个 Bilibili 路由 —— 依赖自建 RSSHub fork（当前 502）
- 35 个 werss 源 —— 服务未部署（502）
- 江苏 / 杭州 / 广东政策解读 —— 站点是 JS 渲染，待接入 playwright

修好对应服务后，从 `.env` 的 `FEED_SECTIONS_DISABLE` 里删掉相应 token 即可恢复，`feeds.txt` 不用改。

详细的信源状态和排查方法见 [docs/operations.md](docs/operations.md)。
