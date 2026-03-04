# rss2cubox

将多个 RSS 源按计划同步到 Cubox Open API，并通过 `state.json` 去重，避免重复推送。

## 工作方式

1. 从 `feeds.txt` 读取 feed 定义（自动忽略空行和 `#` 注释行）。
   - 使用 `[rsshub]` 区块管理 RSSHub 路由（如 `/sspai/index` 或 `rsshub://sspai/index`）。
   - 使用 `[direct]` 区块管理完整 URL（`https://...`）。
   - RSSHub 路由会从 `rsshub_instances.txt` 实例池按顺序尝试，自动切换可用实例。
2. 拉取 feed 条目并按关键词进行包含/排除过滤。
3. 使用条目 `id/guid`（或 `link+title`）生成稳定 ID，基于 `state.json` 去重。
4. 将新条目推送到 Cubox。
5. 更新 `state.json`（GitHub Actions 会自动提交该文件）。
6. 若配置 Anthropic 变量，会对本轮候选 URL+描述先做一轮 AI 分析，再决定是否推送。

## 快速开始（本地）

```bash
python -m pip install -e ".[dev]"
cp feeds.txt feeds.local.txt   # 可选：保留示例 feeds.txt
```

设置环境变量并执行：

```bash
export CUBOX_API_URL="https://cubox.pro/c/api/save/..."
export CUBOX_FOLDER="RSS Inbox"
export KEYWORDS_INCLUDE=""
export KEYWORDS_EXCLUDE=""
export MAX_ITEMS_PER_RUN="20"
export ANTHROPIC_AUTH_TOKEN=""
export ANTHROPIC_BASE_URL="https://api.anthropic.com"
export ANTHROPIC_MODEL=""
export AI_MIN_SCORE="0.6"
export AI_TIMEOUT_SECONDS="90"
export AI_RETRY_ATTEMPTS="3"
export AI_RETRY_BACKOFF_SECONDS="1.5"
export AI_BATCH_SIZE="5"
export AI_MAX_CANDIDATES="40"
export RSSHUB_INSTANCES_FILE="rsshub_instances.txt"
export FEED_CONNECT_TIMEOUT_SECONDS="5"
export FEED_READ_TIMEOUT_SECONDS="10"
export RSSHUB_FAILURE_COOLDOWN_SECONDS="300"

rss2cubox
```

## 环境变量

- `CUBOX_API_URL`（必填）：你的 Cubox Open API 地址。
- `CUBOX_FOLDER`（可选，默认 `RSS Inbox`）：保存到 Cubox 的目标文件夹名。
- `KEYWORDS_INCLUDE`（可选）：包含关键词，逗号分隔，例如 `ai,openai,llm`。
- `KEYWORDS_EXCLUDE`（可选）：排除关键词，逗号分隔。
- `MAX_ITEMS_PER_RUN`（可选，默认 `20`）：单次最多推送条目数。
- `FEEDS_FILE`（可选，默认 `feeds.txt`）：feed 列表文件路径。
- `STATE_FILE`（可选，默认 `state.json`）：状态文件路径。
- `RSSHUB_INSTANCES_FILE`（可选，默认 `rsshub_instances.txt`）：
  RSSHub 公共实例池文件路径，每行一个实例 URL。
- `RSSHUB_INSTANCES`（可选）：当实例池文件缺失或为空时，回退使用该环境变量（逗号分隔）。
- `FEED_CONNECT_TIMEOUT_SECONDS`（可选，默认 `5`）：拉取 feed 的连接超时（秒）。
- `FEED_READ_TIMEOUT_SECONDS`（可选，默认 `10`）：拉取 feed 的读取超时（秒）。
- `RSSHUB_FAILURE_COOLDOWN_SECONDS`（可选，默认 `300`）：RSSHub 实例失败后冷却时间（秒），冷却期间会被跳过。
- `ANTHROPIC_AUTH_TOKEN`（可选）：Anthropic 认证令牌；有值且配置了模型时启用 AI 分析。
- `ANTHROPIC_BASE_URL`（可选，默认 `https://api.anthropic.com`）：Anthropic/兼容网关地址。
- `ANTHROPIC_MODEL`（可选）：模型名，如你的本地值 `MiniMax-M2.5`。
- `AI_MIN_SCORE`（可选，默认 `0.6`）：AI 保留阈值，低于阈值不推送。
- `AI_TIMEOUT_SECONDS`（可选，默认 `90`）：AI 请求超时时间（秒）。
- `AI_RETRY_ATTEMPTS`（可选，默认 `3`）：AI 请求失败重试次数。
- `AI_RETRY_BACKOFF_SECONDS`（可选，默认 `1.5`）：AI 重试退避基数，按指数退避。
- `AI_BATCH_SIZE`（可选，默认 `5`）：AI 分析批大小，建议 5~8。
- `AI_MAX_CANDIDATES`（可选，默认 `MAX_ITEMS_PER_RUN*2`）：单次运行参与 AI 分析和后续推送的候选上限。

## 文件说明

- `feeds.txt`：feed 列表，分 `[rsshub]` 和 `[direct]` 两个区块。
- `rsshub_instances.txt`：RSSHub 公共实例池，每行一个 URL。
- `state.json`：已推送条目的去重状态（由程序维护）。
- `.github/workflows/rss_to_cubox.yml`：定时任务与状态自动提交。

## GitHub Actions 部署

1. Fork 或创建仓库并推送代码。
2. 在仓库 `Settings > Secrets and variables > Actions` 添加：
   - `CUBOX_API_URL`
   - `ANTHROPIC_AUTH_TOKEN`（如果启用 AI 分析）
   - `ANTHROPIC_BASE_URL`
   - `ANTHROPIC_MODEL`
3. 在仓库 `Variables`（或 workflow `env`）中设置：
   - `AI_MIN_SCORE`（可选）
   - `AI_TIMEOUT_SECONDS`（可选）
   - `AI_RETRY_ATTEMPTS`（可选）
   - `AI_RETRY_BACKOFF_SECONDS`（可选）
   - `AI_BATCH_SIZE`（可选）
   - `AI_MAX_CANDIDATES`（可选）
4. 修改 `feeds.txt`（按 `[rsshub]` / `[direct]` 分区）和 `rsshub_instances.txt`（维护实例池）。
5. 启用 workflow `RSS to Cubox`（支持手动触发和定时触发）。

默认定时是每天 `06:00`（北京时间，UTC+8）执行一次，等价于 `22:00 UTC`（前一天）。
可在 `.github/workflows/rss_to_cubox.yml` 调整 `cron`。

每次 workflow 运行会上传 `rss2cubox.log` 到 GitHub Actions artifacts，便于排查 AI 分析与推送日志。
同时会在 `Step Summary` 输出阶段耗时（fetch/ai/push total + p95）、每源推送数、每源丢弃原因、运行上下文和配置快照。

## 测试

```bash
python -m pip install -e ".[dev]"
pytest -q
```
