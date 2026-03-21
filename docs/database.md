# 数据库设计

本项目当前有两类数据存储：

- **Neon / PostgreSQL**
  - 当前主要保存全局洞察结果
  - 兼容保留少量旧运行态表接口
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

`processed_items` 是旧运行态文章表，当前不再是主流程依赖。

历史上它主要用于：

- 增量抓取去重
- 本地状态保留
- 导入 `ic` 前后的过程态跟踪
- 排障与回放

当前主流程的去重基线已经直接来自 `ic`，不是这张表。

### 3. `global_insights`

`global_insights` 专门保存全局洞察：

- 趋势
- 弱信号
- 行动建议

前端洞察卡片直接读取这张表的最新一条记录。

## Neon 表结构

定义位置：

- 当前洞察表入口：
  - [db.py](/home/qy113/workspace/project/2603/rss2cubox/src/rss2cubox/db.py)
- 旧运行态兼容表入口：
  - [db.py](/home/qy113/workspace/project/2603/rss2cubox/src/rss2cubox/legacy/db.py)

当前代码里仍保留 5 张表定义，但主流程稳定使用的是 `global_insights`。
其余 4 张表仅服务于历史迁移、兼容和排障脚本。

### 1. `processed_items`

旧运行态条目表，保留给兼容逻辑和历史脚本。
主键为 `id`，主要数据存放在 `data JSONB`。
历史数据里仍可能混有旧字段，例如 `pushed`。
当前文章正式展示与去重都不再依赖它。

### 2. `feed_cursors`

旧增量抓取游标表，保留给兼容逻辑。
主键为 `feed_key`，游标字段为 `cursor_at`。

### 3. `feed_failures`

旧失败计数和熔断状态表，保留给兼容逻辑。
主键为 `feed_key`，详情存放在 `data JSONB`。

### 4. `run_events`

旧运行事件表，保留给兼容逻辑。
主键为 `event_key`，详情存放在 `data JSONB`，时间字段为 `event_time`。
主要用于旧排障和一次性回放。

### 5. `global_insights`

当前仍在实际使用的 Neon 表。

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

定义位置：

- 全局洞察：
  - [db.py](/home/qy113/workspace/project/2603/rss2cubox/src/rss2cubox/db.py)
- 旧运行态兼容接口：
  - [db.py](/home/qy113/workspace/project/2603/rss2cubox/src/rss2cubox/legacy/db.py)

| 函数 | 说明 |
|------|------|
| `load_state(db_url)` | 读取旧运行态兼容表 |
| `save_state(db_url, state)` | 保存旧运行态兼容表 |
| `save_run_events(db_url, events)` | 写入旧运行事件兼容表 |
| `save_global_insights(db_url, payload)` | 追加保存全局洞察 |
| `load_global_insights(db_url)` | 读取最新洞察 |
| `load_all_global_insights(db_url, limit)` | 读取历史洞察 |

## 与 JSON 文件的关系

项目仍保留文件态兼容逻辑。

| Neon 表 | 对应 JSON 状态 |
|---------|----------------|
| `processed_items` | 旧 `state.processed` |
| `feed_cursors` | 旧 `state.feed_cursor` |
| `feed_failures` | 旧 `state.feed_failures` |
| `run_events` | 旧 `run_events.jsonl` |
| `global_insights` | 无直接 JSON 镜像 |

当 `NEON_DATABASE_URL` 未配置时，`global_insights` 不会持久化；旧兼容逻辑可退回文件态/内存态。

## 旧表结论

- **不要把 `processed_items` 当正式文章库**
- **不要把 `global_insights` 塞进 `processed_items`**
- 正式文章内容看 `ic`
- 全局洞察看 `global_insights`

## 当前前端的数据来源

前端职责已经是分层读取：

- **文章列表**
  - 直接从 `ic` 拉取
- **洞察卡片**
  - 直接从 Neon 的 `global_insights` 读取

这意味着：

- Vercel 需要 `IC_API_URL`
- Vercel 也需要 `NEON_DATABASE_URL`，但当前只为 `global_insights` 服务

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

- **RSS -> Agent SDK -> `ic`**
- **旧运行态兼容表：`processed_items` / `run_events` / `feed_*`**
- **全局洞察 -> `global_insights`**
