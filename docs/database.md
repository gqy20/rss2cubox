# 数据库设计

本项目使用 **PostgreSQL**（推荐 [Neon](https://neon.tech) 云服务），通过 `psycopg` 驱动连接。

数据库连接通过环境变量 `DATABASE_URL` 配置。如果未配置，系统将使用内存状态（适合测试）。

## 表结构

### 1. sent_items - 已发送条目

记录已推送到 Cubox 的条目，用于防止重复推送。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 主键，条目标识（通常为 URL 的哈希） |
| `url` | TEXT | 条目原始 URL |
| `ts` | TIMESTAMPTZ | 发送时间戳 |

### 2. ai_results - AI 处理结果

存储 AI 过滤器的分析结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 主键，条目标识 |
| `data` | JSONB | AI 分析结果（分数、理由等） |

### 3. processed_items - 已处理条目

存储经过处理的条目元数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 主键，条目标识 |
| `data` | JSONB | 处理后的条目数据 |

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
| `event_time` | TIMESTAMPTZ | 事件发生时间 |

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
3. **UPSERT 模式** - 所有写操作使用 `ON CONFLICT DO UPDATE`，支持幂等写入
4. **支持无数据库模式** - `DATABASE_URL` 为空时使用内存状态，方便本地测试

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
