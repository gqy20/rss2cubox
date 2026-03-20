# 数据库设计

本项目当前有两类数据存储：

- **Neon / PostgreSQL**
  - 保存本地运行态和洞察结果
  - 通过 `NEON_DATABASE_URL` 连接
- **ic 信息库**
  - 保存正式文章内容
  - 通过 `IC_API_URL` 批量写入

这两个边界要分清：

- **Neon 不是正式文章库**
- **ic 才是正式文章库**

## 当前职责划分

### 1. `ic`

`ic` 是文章正式入库目标。

主程序会把 Agent SDK 分析后的文章对象批量 POST 到：

```text
POST /api/v1/articles/batch
```

前端文章列表也直接读取 `ic` 的文章接口，不再从 Neon 的 `processed_items` 渲染正式内容。

### 2. `processed_items`

`processed_items` 是本地运行态文章表，主要用于：

- 增量抓取去重
- 本地状态保留
- 导入 `ic` 前后的过程态跟踪
- 排障与回放

它不是正式内容库。

### 3. `global_insights`

`global_insights` 专门保存全局洞察：

- 趋势
- 弱信号
- 行动建议

前端洞察卡片直接读取这张表的最新一条记录。

## Neon 表结构

定义位置：

- [db.py](/home/qy113/workspace/project/2603/rss2cubox/src/rss2cubox/db.py)

当前实际创建的表只有 5 张。

### 1. `processed_items`

保存本地处理后的条目状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `TEXT` | 主键，条目标识 |
| `data` | `JSONB` | 条目完整状态 |

`data` 中通常包含这些字段：

- `id`
- `url`
- `title`
- `time`
- `source_feed`
- `source_label`
- `cover_url`
- `tags`
- `reason`
- `actionable`
- `hidden_signal`
- `core_event`
- `status`
- `drop_reason`
- `publish_time`
- `source_article_id`
- `source_type`
- `exported`

说明：

- 历史数据里仍可能混有旧字段，例如 `pushed`
- 这张表允许保留运行态信息，但不再承担正式展示库职责

### 2. `feed_cursors`

保存每个 Feed 的增量抓取游标。

| 字段 | 类型 | 说明 |
|------|------|------|
| `feed_key` | `TEXT` | 主键，Feed 标识 |
| `cursor_at` | `TEXT` | 上次抓取时间游标 |

### 3. `feed_failures`

保存每个 Feed 的失败计数和熔断状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| `feed_key` | `TEXT` | 主键，Feed 标识 |
| `data` | `JSONB` | 失败详情、冷却时间等 |

### 4. `run_events`

保存一次运行中的逐条事件日志。

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_key` | `TEXT` | 主键，事件唯一标识 |
| `data` | `JSONB` | 事件详情 |
| `event_time` | `TIMESTAMPTZ` | 事件时间 |

这张表用于：

- 排查为什么被 dropped
- 排查某次运行里哪个源失败
- 回看 Agent 分析结果

### 5. `global_insights`

保存全局洞察结果，保留历史。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `SERIAL` | 自增主键 |
| `generated_at` | `TIMESTAMPTZ` | 生成时间 |
| `data` | `JSONB` | 洞察结果 |

索引：

- `idx_global_insights_generated_at`

用途：

- 首页趋势卡片
- 最近一次全局总结
- 后续按时间回看历史洞察

## 已移除的旧表语义

下面这些属于旧架构，当前不再是主模型：

### `sent_items`

这是旧 Cubox 推送链路的去重表，当前已经移除。

### `ai_results`

这是旧“第一阶段批量 AI 分析”的中间结果表，当前已经移除。

## 读写接口

定义于 [db.py](/home/qy113/workspace/project/2603/rss2cubox/src/rss2cubox/db.py)：

| 函数 | 说明 |
|------|------|
| `load_state(db_url)` | 读取 `processed/feed_cursor/feed_failures` |
| `save_state(db_url, state)` | 保存本地运行态 |
| `save_run_events(db_url, events)` | 写入运行事件 |
| `save_global_insights(db_url, payload)` | 追加保存全局洞察 |
| `load_global_insights(db_url)` | 读取最新洞察 |
| `load_all_global_insights(db_url, limit)` | 读取历史洞察 |

## 与 JSON 文件的关系

项目仍保留文件态兼容逻辑。

| Neon 表 | 对应 JSON 状态 |
|---------|----------------|
| `processed_items` | `state.processed` |
| `feed_cursors` | `state.feed_cursor` |
| `feed_failures` | `state.feed_failures` |
| `run_events` | `run_events.jsonl` |
| `global_insights` | 无直接 JSON 镜像 |

当 `NEON_DATABASE_URL` 未配置时，会退回文件态/内存态。

## `processed_items` 与 `ic` 的区别

这是当前最容易混淆的地方。

### `processed_items`

是本地运行态，关注：

- 这条文章是否抓到
- 是否分析成功
- 是否被判定保留
- 是否已经导出
- 导出前后的状态细节

### `ic`

是正式文章库，关注：

- 文章最终展示字段
- 面向前端和外部系统的正式查询
- URL 去重后的最终内容沉淀

因此：

- **不要把 `processed_items` 当正式文章库**
- **不要把 `global_insights` 塞进 `processed_items`**

## 当前前端的数据来源

前端职责已经是分层读取：

- **文章列表**
  - 直接从 `ic` 拉取
- **洞察卡片**
  - 直接从 Neon 的 `global_insights` 读取

这意味着：

- Vercel 需要 `IC_API_URL`
- Vercel 也需要 `NEON_DATABASE_URL`

## 时间字段说明

当前系统至少存在 3 类时间：

### 1. 文章发布时间

来源文章自身的发布时间。

- 在 `ic` 中对应 `publish_time`
- 首页分组、趋势、今日/昨天判断应优先基于它

### 2. Action 运行时间

定时任务或手动运行工作流的时间。

- 用于排查同步何时发生
- 不能当作文章发布时间

### 3. 导入时间

文章写入 `ic` 的时间，通常对应 `created_at`。

- 用于排查导入延迟
- 不应用作首页内容时间轴

## 推荐理解方式

一句话总结当前架构：

- **RSS -> Agent SDK -> `processed_items` / `run_events` -> `ic`**
- **全局洞察 -> `global_insights`**
