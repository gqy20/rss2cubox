# AGENTS.md — rss2cubox 工作指南

供接手本仓库的智能体/工程师快速复用。聚焦“如何把改动安全部署到 HR2 生产环境”和“如何排错”。

## 0. 仓库与生产

| 角色 | 路径 / 主机 |
|---|---|
| 代码仓库 | 本仓库（GitHub `gqy20/rss2cubox`） |
| 本机工作 | `$(pwd)`（或 `cd /home/qy113/workspace/project/2609/rss2cubox`） |
| HR2 生产 | `ssh HR2` → `/root/project/rss2cubox`（`~/.ssh/config` 已配 Host 别名） |
| 数据库 | 本机/HR2 各起一个 `rss2cubox-pg` 容器，`localhost:5434` |
| Web 前端 | `http://localhost:3424`（Next.js production，HR2 跑 `systemd rss2cubox-web`） |

`.env` **不入库**（含凭据）。本机改完 `scp .env HR2:/root/project/rss2cubox/.env` 同步。

## 1. 标准改动流程

```bash
# a. 本机改代码
#    跑相关单测：
cd web && pnpm exec vitest run                  # 前端
cd .. && .venv/bin/python -m pytest tests/ -q    # 后端

# b. 提交推送
cd <repo>
git add -A
git commit -m "..."
git push origin main

# c. 同步代码到 HR2（保留 HR2 上的 .env / web/.env* / logs/）
rsync -az \
  --exclude .venv --exclude node_modules --exclude .next --exclude logs \
  --exclude __pycache__ --exclude .env --exclude 'web/.env*' \
  --exclude .pytest_cache --exclude .rss2cubox-prediction-loop \
  --delete --filter='P logs/' --filter='P .env*' --filter='P web/.env*' \
  ./ HR2:/root/project/rss2cubox/

# d. 依赖变更时 HR2 装包
ssh HR2 'cd /root/project/rss2cubox && uv sync --no-progress && cd web && pnpm install --registry=https://registry.npmmirror.com --silent'

# e. 前端重新构建+重启
ssh HR2 'cd /root/project/rss2cubox/web && pnpm build && sudo systemctl restart rss2cubox-web'
# 注意：1d 前端代码/样式类结构变更也只需 build+restart，不必动 cron
```

## 2. 故障排查（必背）

| 现象 | 排查命令 |
|---|---|
| 数据新鲜度 | `ssh HR2 "psql 'postgresql://postgres:postgres@localhost:5434/rss2cubox' -At -c 'SELECT max(first_seen_at), max(created_at) FROM articles; SELECT max(first_seen_at) FROM policy_documents;'"` |
| 今日 cron 收尾 | `ssh HR2 "ls -lt /root/project/rss2cubox/logs/cron/2026-10-22/ \| tail; grep cron_complete /root/project/rss2cubox/logs/cron/2026-10-22/19-30-01.log"` |
| Web 报错 | `ssh HR2 "journalctl -u rss2cubox-web --since '10 min ago' --no-pager \| grep -iE 'error\|timeout\|TypeError\|off'"` |
| 日报缺失/卡住 | `ssh HR2 "ls /root/project/rss2cubox/.rss2cubox-prediction-loop/*.last_run; grep daily_report /root/project/rss2cubox/logs/cron/2026-10-22/00-00-01.log \| tail -5"` |
| 抓取/全文失败 | `grep 'fetch_error\|fulltext_failed' /root/project/rss2cubox/logs/cron/2026-10-22/*.log \| head` |
| 批 1 跑完没动静 | `ls -t /tmp/backfill_*.log 2>/dev/null; tail -3 /tmp/watchdog.log 2>/dev/null` |
| 单跑一站 dry-run | `ssh HR2 'cd /root/project/rss2cubox && make policy-dry POLICY_ARGS="--only <site_key>" 2>&1 \| grep policy_source_scraped'` |

## 3. 关键路径与配置

| 用途 | 路径 |
|---|---|
| 信源清单（科技 RSS） | `feeds.txt` |
| 信源清单（政策站） | `policy_sources.toml` |
| 凭据（不入库） | `.env`（本机）→ `scp` 到 HR2 同路径 |
| LLM 网关 | `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` / `ANTHROPIC_AUTH_TOKEN` |
| werss 容器（公众号聚合） | HR2 跑 `we-mp-rss` 容器，`127.0.0.1:8001`（HR2 内部）/ `115.191.39.2:8001`（外网） |
| Congress API key | `CONGRESS_API_KEY`（api.congress.gov 免费） |
| 公安数据站白名单 | `POLICY_ENRICH_ALWAYS_SITES=stats_zxfb` |

`.env` 默认配置常量值（**只在改动默认值时改**）看 `src/rss2cubox/config.py` 的 `_TABLE`，**不写进 `.env`**。

## 4. 关键注意

- **`feeds.txt` werss 段**：单账号订阅 `/feed/MP_WXS_<id>.rss`，单行格式 `2\t/feed/<id>.rss # <name>`。name 字段直接进 articles.source_feed_name → 前端显示；超 32 字符的 name 写库后会被替换为短名（如 `AIHOT 全量动态（...）` → `AIHOT`）。
- **`policy_sources.toml`**：每条目声明 `key/name/level/region/list_url`，以及 tier（`rss`/`requests`/`playwright`/`api`）、选择器等。加源时同步改 toml 与 feeds.txt 注释（不要删原有 note）。
- **HR2 不跑 `Jev`**：出口 IP 被 Typesafe 区域封锁 451（"not available in your region"），空转大量调用。**HR2 `.env` 的 `JEV_API_KEY` 必须注释掉**；本机保留。本机测过可用。
- **rsync 必须 `--delete`**：HR2 上有 10-19 前的旧文件，不删会双份混在一起。`--filter='P logs/'` 保留 HR2 的运行日志，幂等。
- **依赖变更时要装包**：`pyproject.toml` / `web/package.json` 改了必须 `uv sync` / `pnpm install`。
- **生产前端 = `systemd`**：别用 `pnpm dev` 启，`next start` 才是 systemd 跑的；前端改完必须 `pnpm build && systemctl restart rss2cubox-web`。
- **HR2 cron 防重叠**：用 `flock`（`.rss2cubox-local.lock`）。手动跑长批时注意：批 1 runner → watchdog 等它退出 → 才启批 2（自然串行）；批 1 期间不要去和 cron 抢。

## 5. 重要历史教训（避免重蹈覆辙）

- **`inspect.py` 事件（2026-10）**：项目根的游离 `.py` 遮蔽标准库，整整 8 天 cron 静默断流！`scripts/run_*.sh` 入口已有 `inspect.py / json.py / os.py / sys.py / logging.py / typing.py` 6 个遮蔽检查 → **永远不要把调试脚本留仓库根**，用 `tmp/` 或 `scripts/oneoff/`。
- **cron `congress` 阶段函数名错位**：在 `run_policy_sync.sh` 里把 `congress_fetcher` 错写成了 `run_python_module`（科技脚本专用），CLI exit 2 连锁跳过 triage/enrich。**任何 patch cron 脚本后必须 `make policy`/`make run` 实跑一遍验证**。
- **Jev 影子预筛 451 不退避**：早期版本硬性无限重试，1,794 次/7 分钟（IP 封锁下不阻塞但纯空转）。**重试必须有上限**。
- **网关额度耗尽（2026-10）**：充值后没到账 + 没告警，enrich/日报静默断 N 天。**任何“按节奏”运行的关键路径必须有数据新鲜度告警**（已实现 `scripts/check_data_health.py`，每天 08:10 跑）。
- **日报 marker 锁死 bug**：daily_report 阶段无脑 `_mark_stage_done` 导致 agent 失败也标记，24h 内不再重试 → 后续哪天都“看似做了实则空跑”。**修复：失败不写 marker，留待重试**（2026-10 已修）。

## 6. 一次性脚本与测试

- `scripts/oneoff/`（推荐）：放一次性脚本（如旧 `query_pred39.py` 改造后位置）。**不要放在仓库根**——根目录是 import 解析边界。
- `tmp/` 目录：调试阶段临时脚本的合适位置。
- 改完测试：`cd web && pnpm exec vitest run`；`cd .. && .venv/bin/python -m pytest tests/ -q`。前端改动同步改 `.env.example` 是无的（应改 `src/rss2cubox/config.py`）。

## 7. 新源接入流程（参考多轮已验证模式）

```bash
# a. 探测（用 dry-run 验选择器与可达性）
ssh HR2 'cd /root/project/rss2cubox && make policy-dry POLICY_ARGS="--only <key>" 2>&1 | tail'

# b. 三种源处理路径
#  RSS：加 feeds.txt
#  政策 HTML：加 policy_sources.toml（tier=playwright 时用反无头请求头）
#  API：公开数据平台用 tier="api" + 固定 adapter，enabled=true，自动进入 policy_runner/cron/监控。
#       Congress 沿用独立 fetcher；不要以为任意 model="api" 或 disabled 配置会自动被调度。

# c. 启用 + 入库
ssh HR2 "cd /root/project/rss2cubox && make policy --only <key> --enrich" 2>&1 | grep run_summary
# 看 enriched_at/rel2 比例
ssh HR2 'psql "postgresql://postgres:postgres@localhost:5434/rss2cubox" -At -c \
  "SELECT count(*), count(*) FILTER (WHERE enriched_at IS NOT NULL), count(*) FILTER (WHERE triage_relevance >= 2) FROM policy_documents WHERE site_key='"'"'<key>'"'"';"'

# d. 提交推送 + rsync 同步 + 重启前端
git add -A && git commit -m "..." && git push origin main
rsync -az --exclude .venv --exclude node_modules --exclude .next --exclude logs --exclude __pycache__ --exclude .env --exclude 'web/.env*' --exclude .pytest_cache --exclude .rss2cubox-prediction-loop --delete --filter='P logs/' --filter='P .env*' --filter='P web/.env*' ./ HR2:/root/project/rss2cubox/
ssh HR2 'cd /root/project/rss2cubox/web && pnpm build && sudo systemctl restart rss2cubox-web'
```

## 8. UI 改动工作流

Next.js 应用，`web/app/...` 是 RSC/客户端组件；`web/lib/...` 是纯 TS 服务工具。改动流程：

```bash
# 1) 改 web/app/<route>/page.tsx
# 2) 写/改测试 web/__tests__/...
cd web && pnpm exec vitest run

# 3) 改样式 web/app/styles/<name>.css（项目所有样式表由此目录加载）
#    .env.example 更新（仅当新增配置项时）

# 4) 提交推送
git add -A && git commit -m "feat(web): ..." && git push origin main

# 5) 同步代码 + 重启（前端改动才需 build+restart）
rsync -az ...   # 同上
ssh HR2 'cd /root/project/rss2cubox/web && pnpm build && sudo systemctl restart rss2cubox-web'

# 6) 验证
ssh HR2 'curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3424/<route>'
```

`/daily`、`/policies`、`/signals` 等页面是 `[kind]` 路由（dynamic param）；`/monitor` 是固定路由。

## 9. “本机 vs HR2” 双环境协作的 4 个反模式

1. ❌ 在 HR2 改完代码不 commit 本机 → 第二天没意识到 diff 丢了
2. ❌ 在本机测过直接 rsync 不重启 → service 还在跑旧 build
3. ❌ 跳过单测直接 commit → 下次 fault 周期变成几天
4. ❌ 给 `feeds.txt` 写一长串接入说明当 name → 污染前端显示（用短名 + note 写注释）

## 10. 维护备忘

- AGENTS.md 是“由智能体迭代”文档，**每发现一个坑就补一节**，免下个接手者重蹈。
- `.env.example` 与 `config.py` 注册表必须保持**严格同步**（`tests/test_config_registry.py` 强制校验）。
- docs/ 目录：用户视角用 README.md，技术视角用 docs/operations.md、docs/frontend-journal.md、DESIGN.md。



## 11. TED 引用补齐与 SDK 错误诊断

- TED 报告生成后自动核对引用的入库记录、正文和逐篇分析，缺失项存入 `ted_source_jobs`。手动检查/补齐统一用 `make ted-sources TED_SOURCE_ARGS="--issue <UUID> [--repair]"`；HR2 可指定 `TED_PYTHON=.venv/bin/python`。只处理当前报告的引用，保留已有成功分析和正文；未知发布日期保持为空。
- SDK 的 `ResultMessage.errors` 为空，不代表没有具体错误。网关的 403/额度不足等详情可能在 `result` 或错误 AssistantMessage 内；CLI 随后抛退出码1时必须保留已收到的错误正文，并脱敏记录。不要只按退出码猜原因。
- 每条补齐任务最多3次、失败后间隔15分钟，中断任务30分钟后可重新领取；遇到额度或鉴权错误停止本批。报告的引用说明不能充当逐篇分析，实际结果须通过 enrich JSON Schema 校验。
- 部署使用 `make web-deploy`；依赖同步、构建、重启与检查保留在统一入口。服务器已有无关未提交文件时，用 `DEPLOY_RSYNC_ARGS` 明确排除并核对内容未变，示例见 `docs/operations.md`。


## 12. 信源建议入口的 SSRF 防护

- `/api/suggest-source` 提交及审核须通过独立的 `SOURCE_SUGGEST_TOKEN` 维护者 Bearer 校验，未配置时拒绝访问；只在服务端配置，不能加入 `NEXT_PUBLIC_` 或前端密钥界面。
- 外部传入的 URL 使用 `web/lib/public-source-fetch.ts`：校验规范化 URL、全部 DNS 答案和每个跳转，再把连接固定到已验证 IP。只检查域名字符串或“先解析检查、随后普通 fetch 再解析”仍有绕过风险。
- 计时必须覆盖响应体读取，大小限制必须在流式读取时执行，不能在 `res.text()` 完整下载后再 slice。抓取不转发调用者的 Cookie/Authorization。
- 用模拟 DNS/HTTP 测试内网、云元数据地址、编码 IP、重绑定与跳转阻断，不通过生产漏洞发起真实内网探测。部署仍走 `make web-deploy`，更新 llms.txt 中对应的鉴权与调用约定。


## 13. 公开数据平台进入政策库

- `policy/data_channels.py` 只读 NDSMS/SJD 固定公开接口；不要绕过登录/验证码，不采数据文件与联系人表。业务 success/schema 校验失败进入源监控，不能当作无更新。
- 目录/需求/授权运营披露使用明确的非规范性类型，`triage_is_policy=false` 仍可按相关度进入分析。预筛使用快照上下文，短但有效的资源标题不被 8 字门槛挡掉。
- 新 API 记录按 site_key + 原站ID稳定去重；SJD SPA 没有独立详情链接，多条记录保留真实同一入口 URL，不能编造深链。普通源保留 URL 部分唯一索引。
- 公开快照/实质字段变化清空旧分析等待重算；浏览/下载数、抓取时间与单纯 updatedTime 变化不重跑分析。未知发布日期保持 null，年度披露不能伪造为某年1月1日发布。
- `--only` 的多源范围同时约束抓取、预筛、深度分析，不能意外处理全库积压。新列由 `make web-deploy` 在构建前幂等迁移，部署仍用统一入口。

- 资源类引用只写“逐字引用”提示仍可能被模型改写。分析输入提供原文候选片段，单次 JSON Schema 用枚举约束 source_quote；不能把改写后的引句当原文入库，也不能用相似文本替换来掩盖失败。全局 schema 不得原地修改，以免并发文档串用候选。
