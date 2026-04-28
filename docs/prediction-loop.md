# AI 趋势预测闭环设计

本文档描述 RSS Signals 如何从“文章情报流”升级为“信号驱动的预测与复盘系统”。

目标不是让 Agent 生成更长的总结，而是建立一个可验证的预测账本：

```text
文章 -> 单篇 enrich 标注 -> 信号簇 -> 一周趋势预测 -> 一周后评分复盘 -> 调整下一轮预测策略
```

## 设计原则

### 1. 预测必须绑定历史信号

预测不应直接从最近文章生成，而应从长期存在的 `signal_cluster` 生成。

合理链路是：

```text
历史信号 -> 最近 7 天变化 -> 未来 7 天预测 -> 目标窗口内证据验证
```

这样可以避免只追逐最近一周的资讯热度。

### 2. Agent 做判断，系统做计量

Agent 适合做：

- 归纳信号主题
- 判断证据语义
- 生成可证伪预测
- 解释为什么命中或未命中

系统应负责：

- 计算频次、增速、来源数
- 检索支持/反证文章
- 维护预测状态
- 保存评分和历史表现

### 3. 预测必须可证伪

不要生成：

```text
AI Agent 会继续发展
```

要生成：

```text
未来 7 天内，至少 3 个不同来源会出现 AI coding agent 进入 CI/PR 流程的实质证据，其中至少 1 个是官方发布或开源仓库。
```

## 已有基础

当前 `enrich_agent` 已经为单篇文章增加结构化标注字段：

| 字段 | 用途 |
|------|------|
| `signal_type` | 信号大类 |
| `evidence_type` | 证据类型 |
| `evidence_strength` | 证据强度 |
| `novelty_score` | 新颖度 |
| `impact_horizon` | 影响时间尺度 |
| `audience` | 主要受众 |
| `market_stage` | 市场/工程化阶段 |
| `confidence` | 单篇判断置信度 |
| `entities` | 公司、模型、框架、数据集、Benchmark 等 |
| `cluster_hint` | 聚类语义锚点 |
| `watch_keywords` | 后续追踪关键词 |
| `prediction` | 单篇文章暗含的后续预期 |
| `disconfirming_evidence` | 反证条件 |
| `content_source` | `full_text` 或 `summary_only` |

这些字段是预测闭环的输入，不应直接等同于最终趋势判断。

## 核心实体

### 1. `signal_clusters`

长期信号簇。它是预测的主语。

示例：

- 异步软件工程代理
- 推理模型强化学习范式
- 端侧小模型部署
- AI 安全自动化漏洞发现
- 多模态视频生成商业化

建议字段：

```sql
CREATE TABLE IF NOT EXISTS signal_clusters (
    id                      SERIAL PRIMARY KEY,
    label                   TEXT NOT NULL,
    normalized_label        TEXT NOT NULL,
    signal_type             SMALLINT,
    status                  TEXT NOT NULL DEFAULT 'new',
    summary                 TEXT,
    entities                JSONB DEFAULT '[]',
    watch_keywords          JSONB DEFAULT '[]',
    first_seen_at           TIMESTAMPTZ,
    last_seen_at            TIMESTAMPTZ,
    article_count           INTEGER DEFAULT 0,
    source_count            INTEGER DEFAULT 0,
    avg_importance          NUMERIC,
    avg_evidence_strength   NUMERIC,
    avg_novelty             NUMERIC,
    avg_confidence          NUMERIC,
    prediction_score_avg    NUMERIC,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);
```

`status` 建议取值：

```text
new       新出现
warming   升温
bursting  爆发
cooling   降温
mature    稳定成熟
invalid   证伪/衰退
```

### 2. `signal_cluster_articles`

文章和信号簇的关系表。

```sql
CREATE TABLE IF NOT EXISTS signal_cluster_articles (
    cluster_id      INTEGER NOT NULL REFERENCES signal_clusters(id),
    article_id      VARCHAR(255) NOT NULL REFERENCES articles(id),
    relevance_score NUMERIC,
    linked_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cluster_id, article_id)
);
```

第一版可以用规则聚类：

```text
cluster_key = normalized(signal_type + cluster_hint)
```

后续再升级为：

```text
embedding(title + hidden_signal + cluster_hint) + pgvector 相似度
```

### 3. `trend_predictions`

预测账本。每条预测必须绑定一个信号簇。

```sql
CREATE TABLE IF NOT EXISTS trend_predictions (
    id                      SERIAL PRIMARY KEY,
    signal_cluster_id        INTEGER REFERENCES signal_clusters(id),
    prediction_type          SMALLINT NOT NULL,
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    target_start_at          TIMESTAMPTZ NOT NULL,
    target_end_at            TIMESTAMPTZ NOT NULL,
    horizon_days             INTEGER NOT NULL DEFAULT 7,
    prediction_title         TEXT NOT NULL,
    prediction_body          TEXT NOT NULL,
    watch_keywords           JSONB DEFAULT '[]',
    expected_evidence        JSONB DEFAULT '{}',
    disconfirming_evidence   TEXT,
    baseline_metrics         JSONB DEFAULT '{}',
    confidence               SMALLINT,
    status                   TEXT NOT NULL DEFAULT 'pending',
    created_from_insight_id  INTEGER
);
```

`prediction_type` 建议取值：

```text
1 = 延续预测：已有趋势继续升温
2 = 转阶段预测：论文 -> 开源 / 开源 -> 产品 / 产品 -> 商业化
3 = 扩散预测：从单一来源扩散到多源
4 = 反转预测：热度下降或被证伪
5 = 迟到验证：之前预测未命中，但窗口后出现证据
```

`expected_evidence` 示例：

```json
{
  "minimum_support_count": 3,
  "required_source_count": 2,
  "required_evidence_types": [1, 4, 5, 9],
  "required_keywords": ["coding agent", "PR automation", "CI agent"]
}
```

### 4. `prediction_reviews`

一周后对预测进行评分和复盘。

```sql
CREATE TABLE IF NOT EXISTS prediction_reviews (
    id                      SERIAL PRIMARY KEY,
    prediction_id            INTEGER NOT NULL REFERENCES trend_predictions(id),
    reviewed_at              TIMESTAMPTZ DEFAULT NOW(),
    score                   SMALLINT NOT NULL,
    hit_level                TEXT NOT NULL,
    supporting_articles      JSONB DEFAULT '[]',
    contradicting_articles   JSONB DEFAULT '[]',
    actual_observation       TEXT,
    why_score                TEXT,
    improvement_advice       TEXT,
    review_metrics           JSONB DEFAULT '{}'
);
```

评分标准：

```text
1 = 未命中：没有相关证据，或方向相反
2 = 弱命中：有讨论但无实质证据
3 = 部分命中：方向对，但强度/时间/主体不准确
4 = 强命中：主要判断成立，有多源证据
5 = 精确命中：方向、时间窗口、证据类型和影响判断都准确
```

## 三个新增 Agent

### 1. Signal Cluster Agent

职责：把文章流转成长期信号簇。

输入：

- 最近 7/30 天文章
- 每篇文章的 `signal_type / cluster_hint / entities / watch_keywords / hidden_signal`
- 已有 `signal_clusters`

输出：

- 新建哪些 cluster
- 哪些文章归入已有 cluster
- cluster 摘要更新
- cluster 状态更新：`new / warming / bursting / cooling / mature / invalid`

第一版可以让系统先基于 `signal_type + cluster_hint` 粗聚类，再让 Agent 审核合并/拆分建议。

### 2. Trend Prediction Agent

职责：基于历史信号簇和最近一周变化，生成未来一周预测。

输入：

- 每个 cluster 的历史曲线
- 最近 7 天新增证据
- 最近 30/90 天基线
- 该 cluster 的历史预测评分
- 支持/反证证据摘要

输出：

- 3-7 条可验证预测
- 每条绑定 `signal_cluster_id`
- `prediction_type`
- `expected_evidence`
- `watch_keywords`
- `disconfirming_evidence`
- `confidence`

选择候选 cluster 的优先级：

```text
1. 历史存在，最近 7 天明显升温
2. 历史弱信号，最近出现更强证据
3. 历史预测未命中，但本周出现迟到证据
4. 过去停留在论文，现在出现代码/产品/官方发布
5. 多个来源同时提到同一 cluster_hint
```

### 3. Prediction Review Agent

职责：在预测窗口结束后，对预测打分并复盘。

输入：

- 原预测
- 目标窗口内该 cluster 的新增文章
- 自动计算指标
- 支持候选文章
- 反证候选文章

输出：

- `score: 1-5`
- `hit_level`
- `supporting_articles`
- `contradicting_articles`
- `actual_observation`
- `why_score`
- `improvement_advice`

## 自动指标

预测生成和评分前，系统应计算客观指标。

### Cluster 指标

```text
volume_7d
volume_prev_7d
volume_30d_avg
burst_ratio = volume_7d / volume_30d_avg
source_count_7d
evidence_strength_avg
novelty_avg
confidence_avg
stage_shift
evidence_shift
prediction_score_avg
```

### Review 指标

```text
keyword_hits
support_count
source_count
avg_evidence_strength
high_confidence_count
contradiction_count
burst_delta
```

## 运行流程

### 每日或每周：更新信号簇

```text
1. 读取最近 7/30 天已 enrich 文章
2. 按 signal_type + cluster_hint 粗聚类
3. 写入或更新 signal_clusters
4. 写入 signal_cluster_articles
5. 计算 cluster 指标和状态
```

### 每周：生成预测

```text
1. 读取活跃 cluster
2. 读取最近 7 天变化和 30/90 天基线
3. 读取该 cluster 历史预测评分
4. 选择 top clusters
5. Trend Prediction Agent 生成预测
6. 写入 trend_predictions
```

### 每日：检查待评分预测

```text
1. 找到 target_end_at <= now 且 status != reviewed 的预测
2. 拉取目标窗口内该 cluster 新文章
3. 计算 review metrics
4. Prediction Review Agent 打分
5. 写入 prediction_reviews
6. 更新 trend_predictions.status
7. 更新 signal_clusters.prediction_score_avg
```

## 与现有全局洞察的关系

`global_insights` 仍可保留，但职责应调整。

原职责：

```text
直接生成趋势、弱信号、行动建议
```

建议职责：

```text
读取 signal_clusters / trend_predictions / prediction_reviews 后生成前端展示文案
```

也就是说，`global_insights` 应成为展示层，不再作为核心判断源。

## 第一阶段最小实现

不引入 embedding，不引入复杂向量库。

第一阶段只做：

```text
1. signal_clusters 表
2. signal_cluster_articles 表
3. trend_predictions 表
4. prediction_reviews 表
5. 基于 signal_type + cluster_hint 的规则聚类
6. 生成 3-5 条一周预测
7. 一周后基于关键词和 cluster 文章评分
```

等闭环跑通后，再升级：

- pgvector 相似聚类
- 更细的 source reliability
- Prediction Strategy Agent
- 前端预测看板

## 当前实现状态

第一版实现为规则 Agent，先保证闭环数据结构和可测试行为稳定。

代码入口：

| Agent | 文件 | 当前职责 |
|------|------|----------|
| Signal Cluster Agent | `src/rss2cubox/signal_cluster_agent.py` | 基于 `signal_type + cluster_hint` 聚类文章，输出 clusters 和 article links |
| Trend Prediction Agent | `src/rss2cubox/prediction_agent.py` | 基于活跃 cluster 生成未来 7 天可验证预测 |
| Prediction Review Agent | `src/rss2cubox/prediction_review_agent.py` | 基于目标窗口文章、关键词和证据类型给预测评分 |

本地数据库 schema 和保存函数位于：

```text
src/rss2cubox/db_client.py
```

包括：

```text
PREDICTION_LOOP_SCHEMA
ensure_prediction_loop_schema()
save_signal_clusters()
save_trend_predictions()
save_prediction_review()
```

当前版本还没有引入 Agent SDK 审核，也没有使用 embedding。后续可以在保持函数输入输出契约不变的前提下，将规则判断替换为 LLM 审核或 pgvector 相似度聚类。

## 未来前端模块

建议新增一个“趋势预测”模块：

```text
趋势预测
- 本周预测
- 待验证
- 已验证
- 最近命中率
- 失败原因
```

每条预测展示：

- 绑定信号簇
- 预测内容
- 验证窗口
- 当前支持证据数
- 最终评分
- 支持/反证文章
- 改进建议

## 结论

合理闭环不是：

```text
文章 -> 预测 -> 评分
```

而是：

```text
文章 -> 信号簇 -> 信号生命周期 -> 预测 -> 验证 -> 调整信号簇权重
```

这样系统才能逐渐知道哪些 AI 信号是真趋势，哪些只是噪音。
