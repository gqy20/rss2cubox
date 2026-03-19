# 数据库设计

本项目使用 **PostgreSQL**（推荐 [Neon](https://neon.tech) 云服务），通过 `psycopg` 驱动连接。

数据库连接通过环境变量 `NEON_DATABASE_URL` 配置。如果未配置，系统将使用内存状态（适合测试）。

## 表结构

### 1. sent_items - 已发送条目

记录已推送到 Cubox 的条目，用于防止重复推送。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 主键，条目标识（通常为 URL 的哈希） |
| `url` | TEXT | 条目原始 URL；这是“已发送条目”最明确、稳定的 URL 存储位置 |
| `ts` | TIMESTAMPTZ | 发送时间戳 |

### 2. ai_results - AI 处理结果

存储 AI 过滤器的分析结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 主键，条目标识 |
| `data` | JSONB | AI 分析结果（分数、理由等）；通常不单独保存 URL，需通过相同 `id` 与其他表关联 |

### 3. processed_items - 已处理条目

存储经过处理的条目元数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 主键，条目标识 |
| `data` | JSONB | 处理后的条目数据，通常包含 `url`、`title`、`source_feed`、AI 分析结果和推送状态等 |

### 4. feed_cursors - Feed 游标

记录每个 Feed 的增量抓取位置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `feed_key` | TEXT | 主键，Feed 标识 |
| `cursor_at` | TEXT | 游标位置（ISO 时间戳） |

### 5. feed_failures - Feed 失败记录

记录 Feed 抓取失败状态，用于熔断机制。

| 字段 | 类型 | 说明 |
|------|------|------|
| `feed_key` | TEXT | 主键，Feed 标识 |
| `data` | JSONB | 失败详情（计数、最后失败时间、熔断状态等） |

### 6. run_events - 运行事件日志

记录每次运行的处理结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_key` | TEXT | 主键（SHA256 哈希，基于 run_id、id、status、time、url 生成） |
| `data` | JSONB | 事件详情 |
| `event_time` | TIMESTAMPTZ | 事件发生时间，可为空 |

### 7. global_insights - 全局分析洞察

存储 AI Agent 对整体 RSS 内容的深度分析结果（保留历史）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | SERIAL | 自增主键 |
| `generated_at` | TIMESTAMPTZ | 生成时间 |
| `data` | JSONB | 分析结果 |

**索引**: `idx_global_insights_generated_at` (降序) - 用于快速查询最新分析

## ER 图

```
┌─────────────────┐     ┌─────────────────┐     ┌───────────────────┐
│   sent_items    │     │   ai_results    │     │  processed_items  │
├─────────────────┤     ├─────────────────┤     ├───────────────────┤
│ id (PK) TEXT    │     │ id (PK) TEXT    │     │ id (PK) TEXT      │
│ url TEXT        │     │ data JSONB      │     │ data JSONB        │
│ ts TIMESTAMPTZ  │     └─────────────────┘     └───────────────────┘
└─────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌───────────────────┐
│  feed_cursors   │     │ feed_failures   │     │    run_events     │
├─────────────────┤     ├─────────────────┤     ├───────────────────┤
│ feed_key (PK)   │     │ feed_key (PK)   │     │ event_key (PK)    │
│ cursor_at TEXT  │     │ data JSONB      │     │ data JSONB        │
└─────────────────┘     └─────────────────┘     │ event_time TZ     │
                                                └───────────────────┘

┌─────────────────────┐
│  global_insights    │
├─────────────────────┤
│ id (PK) SERIAL      │
│ generated_at TZ     │
│ data JSONB          │
└─────────────────────┘
```

## 设计特点

1. **无外键约束** - 表之间独立，无关联关系
2. **大量使用 JSONB** - 灵活存储复杂数据结构，便于扩展
3. **多数状态表使用 UPSERT** - `sent_items`、`ai_results`、`processed_items`、`feed_cursors`、`feed_failures`、`run_events` 使用 `ON CONFLICT DO UPDATE`，支持幂等写入；`global_insights` 为追加写入，保留历史
4. **支持无数据库模式** - `NEON_DATABASE_URL` 为空时使用内存状态，方便本地测试

## 接口函数

定义于 `src/rss2cubox/db.py`：

| 函数 | 说明 |
|------|------|
| `load_state(db_url)` | 加载完整状态（sent、ai、processed、feed_cursor、feed_failures） |
| `save_state(db_url, state)` | 保存完整状态 |
| `save_run_events(db_url, events)` | 写入运行事件 |
| `save_global_insights(db_url, payload)` | 保存全局分析（保留历史） |
| `load_global_insights(db_url)` | 读取最新全局分析 |
| `load_all_global_insights(db_url, limit)` | 读取历史全局分析列表 |

## 与 JSON 文件的对应关系

项目同时支持数据库和 JSON 文件存储：

| 数据库表 | JSON 字段/文件 | 说明 |
|----------|---------------|------|
| `sent_items` | `state.sent` | 已发送条目 |
| `ai_results` | `state.ai` | AI 结果 |
| `processed_items` | `state.processed` | 已处理条目 |
| `feed_cursors` | `state.feed_cursor` | Feed 游标 |
| `feed_failures` | `state.feed_failures` | 失败记录 |
| `run_events` | `run_events.jsonl` | 运行事件 |
| `global_insights` | *(无)* | 仅数据库 |

## URL 存储说明

- `sent_items.url` 是已推送到 Cubox 的条目的明确 URL 字段，适合直接按已发送记录查询。
- `processed_items.data.url` 通常也保留 URL，并且带有 `title`、`status`、`source_feed`、`score`、`reason` 等更完整的处理结果，适合前端展示或排查流水线行为。
- `ai_results.data` 主要存储 AI 分析结果，通常不包含 URL；如需定位原文，应通过相同的 `id` 去 `processed_items` 或 `sent_items` 查询。
- `run_events.data` 中也会包含事件对应的 `url`，但它是运行日志视角，不是主状态存储。

## 迁移说明（去 Cubox 化）

下面是基于当前项目演进方向的推荐目标模型。前提是：

- 不再把 RSS 条目推送到 Cubox。
- 不再保留“第一阶段批量 AI 粗筛结果表”，统一由 Agent SDK 产出分析结果。
- Web 前端继续需要查询最新信号和历史运行记录。

### 建议删除的表

#### 1. `sent_items`

这个表的职责是“已推送到 Cubox 的条目去重”。去掉 Cubox 之后，这个语义不再成立。

迁移后如仍需要防重复，应改为：

- 直接以 `processed_items.id` 作为条目级去重主键；
- 或在 `processed_items.data.status` 中表达条目当前状态，而不是单独维护一个“已发送表”。

#### 2. `ai_results`

这个表目前主要保存中间分析结果。若统一改为 Agent SDK 直接输出最终结构化结果，并把结果写入 `processed_items` / `run_events`，那么该表可以删除。

### 建议保留的核心表

#### 1. `processed_items` - 条目主状态表

迁移后建议把它作为**每个条目的唯一主状态表**。也就是说，单条 RSS 信息的最新处理结果只保留在这里。

建议 `data` 中至少保留这些字段：

- `id`: 条目标识，通常由规范化 URL + 标题等稳定生成
- `url`: 原文链接
- `title`: 标题
- `time`: 条目时间或抓取到的发布时间
- `source_feed`: 来源 feed
- `source_label`: 来源展示名
- `cover_url`: 封面图链接
- `status`: 当前状态，建议使用与业务解耦的值，例如 `kept` / `dropped` / `failed`
- `drop_reason`: 丢弃原因
- `keep`: Agent 是否判定应保留
- `score`: 综合评分
- `tags`: 标签
- `core_event`: 核心事件摘要
- `hidden_signal`: 隐含信号
- `actionable`: 行动建议
- `reason`: 解释或判定依据
- `model`: 产出该分析结果的模型或 Agent 标识
- `enriched`: 是否经过全文深化
- `updated_at`: 最近一次处理时间

这张表在迁移后承担三个职责：

- 条目去重
- 最新状态查询
- 前端主列表的数据源候选

建议按下面的语义理解 `processed_items.data`：

- `id`: 条目的稳定主键。建议继续作为 `processed_items` 的唯一标识；通常由规范化 URL 等信息计算得到。
- `url`: 原文链接。这是迁移后单条信息最重要的定位字段。
- `title`: 条目标题，用于列表展示和检索。
- `time`: 条目时间。当前数据里使用 ISO 8601 时间字符串。
- `source_feed`: 原始 feed 标识，便于回溯来源。
- `source_label`: 面向用户展示的来源名称。
- `cover_url`: 封面图地址；没有时可以为空字符串。
- `status`: 当前处理状态。当前线上数据里常见值为 `dropped`，迁移后建议继续收敛为与业务解耦的状态值。
- `drop_reason`: 当 `status` 不是保留态时，记录具体原因。
- `keep`: Agent 是否判定应保留。
- `score`: Agent 给出的综合评分，范围通常为 `0.0` 到 `1.0`。
- `tags`: 标签数组，用于聚类、筛选和展示。
- `core_event`: 对事实层事件的一句话概括。
- `hidden_signal`: 对更深层含义或趋势信号的提炼。
- `actionable`: 面向工程师或独立开发者的行动建议。
- `reason`: 判定依据。当前实现里常与 `hidden_signal` 接近，但迁移后可以保留为更明确的解释字段。
- `model`: 产出分析结果的模型或 Agent 标识。当前样本里不一定都有，迁移后建议补齐。
- `enriched`: 是否做过全文深化。
- `updated_at`: 最近一次处理时间。当前线上样本里还没有单独存这个字段，通常可由 `time` 近似替代；迁移后建议显式加入。

当前线上 `processed_items.data` 的真实样本如下：

```json
{
  "id": "cad505e6c9943d4c478e0a1cef4e9108f7befd8e528f9a9957aabf3790e694e6",
  "url": "https://mp.weixin.qq.com/s/3dW-RHT7M_5-sPyiUmDgWg",
  "keep": false,
  "tags": ["企业协作", "AI助手", "飞书生态"],
  "time": "2026-03-19T13:18:31.612345+00:00",
  "score": 0.35,
  "title": "同事群里催催催，龙虾自动回回回！刚发布的「飞书龙虾」把我解脱了",
  "pushed": false,
  "reason": "企业协作工具正在全面AI化，但\"群聊自动回复\"更多是效率工具而非深度智能化，低门槛复现性强，不构成技术护城河。",
  "status": "dropped",
  "enriched": false,
  "cover_url": "https://mmbiz.qpic.cn/sz_mmbiz_jpg/A6fTew8FFGH4ElhPeu2xWVmCWibPJTSVWQlEDaFeQePNZVzicwfwHg5stdH8IibzbbCjlSNfc5hSOn4Iibn7z4rN73g2FqaLbHyKjMz4QuBSjQo/0?wx_fmt=jpeg",
  "actionable": "评估企业内部是否存在重复性群聊沟通痛点，探索类似轻量级AI辅助的可行性；不过度投入资源自研，关注现成解决方案。",
  "core_event": "飞书平台发布\"飞书龙虾\"功能，实现群聊场景下的AI自动回复，支持无需部署直接使用。",
  "drop_reason": "ai_keep_false",
  "source_feed": "/feed/MP_WXS_3236757533.rss",
  "source_label": "量子位",
  "hidden_signal": "企业协作工具正在全面AI化，但\"群聊自动回复\"更多是效率工具而非深度智能化，低门槛复现性强，不构成技术护城河。"
}
```

说明：

- 这个样本来自当前线上数据库中的 `processed_items.data`，不是示意数据。
- `pushed` 是历史 Cubox 流程遗留字段；在迁移后的目标模型里可以删除。
- `model` 和 `updated_at` 目前不是每条样本都具备，但建议在新模型里补齐。

建议把迁移后的 `processed_items.data` 约定为下面这种结构：

```json
{
  "id": "string",
  "url": "string",
  "title": "string",
  "time": "2026-03-19T13:18:31.612345+00:00",
  "source_feed": "string",
  "source_label": "string",
  "cover_url": "string",
  "status": "kept | dropped | failed",
  "drop_reason": "string",
  "keep": true,
  "score": 0.92,
  "tags": ["标签A", "标签B"],
  "core_event": "string",
  "hidden_signal": "string",
  "actionable": "string",
  "reason": "string",
  "model": "string",
  "enriched": true,
  "updated_at": "2026-03-19T13:20:00+00:00"
}
```

字段约束建议如下：

- 必填字段：`id`、`url`、`title`、`time`、`status`、`keep`、`score`、`tags`、`core_event`、`hidden_signal`、`actionable`、`reason`、`updated_at`
- 推荐保留字段：`source_feed`、`source_label`、`cover_url`、`drop_reason`、`model`、`enriched`
- 可空但建议统一存在的字段：`cover_url`、`drop_reason`、`source_label`、`model`
- 废弃字段：`pushed`

状态字段建议收敛为：

- `kept`: 该条信息被保留，作为有效信号展示
- `dropped`: 该条信息被判定丢弃
- `failed`: 处理过程中发生错误，结果不可信或未完成

`drop_reason` 的使用建议：

- 当 `status = kept` 时，允许为空字符串
- 当 `status = dropped` 时，应尽量填写明确原因，例如 `agent_keep_false`、`score_below_threshold`
- 当 `status = failed` 时，可填写错误类别，例如 `agent_timeout`、`read_webpage_failed`

为了降低前端和导出逻辑复杂度，建议在迁移后遵守两个约束：

- `processed_items.data.id` 必须与表主键 `processed_items.id` 保持一致
- 即使字段为空，也优先保留固定键，而不是在不同记录间省略不同字段

#### 2. `global_insights` - 全局洞察表

这个表是否保留，取决于你是否还需要“按天/按次生成的全局趋势总结”。

- 如果保留日报、周报、趋势洞察，继续保留。
- 如果后续不做全局总结，可以删除。

### 明确不再进入数据库的状态

以下状态迁移后不再保存在数据库中：

#### 1. `feed_cursors`

feed 游标改由 GitHub 侧文件或工作流状态保存，数据库不再重复存储。

#### 2. `feed_failures`

抓取失败计数、冷却时间、熔断状态不再入库。如果后续仍需要，只保留在运行时内存或 GitHub 侧状态。

#### 3. `run_events`

逐次运行事件历史不再入库。迁移后数据库只保留“单条信息的最新状态”，不保留完整事件流。

### 推荐的最终表集

#### 最小可用表集

- `processed_items`

#### 可选扩展表集

- `processed_items`
- `global_insights`

在“去 Cubox 化、游标保留在 GitHub、运行事件不入库”的前提下，这是建议的最终结构。

### 迁移后的 URL 主存储位置

去掉 Cubox 相关表后，URL 的主存储位置应当明确为：

- `processed_items.data.url`：单条信息的最新状态

如果仍保留 `global_insights`，它只消费分析结果，不承担单条 URL 的主存储职责。

迁移完成后，不应再依赖 `sent_items.url`、`ai_results` 或 `run_events` 来定位原文链接。
