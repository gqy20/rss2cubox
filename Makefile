# rss2cubox 本地开发入口
#
# 最常用:
#   make up     一次性把环境准备好（DB 容器 + 依赖 + 建表）
#   make dev    一次性启动前后端（DB + 后端跑一次 + 前端常驻）
#   make run    只跑一次后端 pipeline
#   make doctor 体检：DB / LLM 网关 / IC / RSS 源连通性
#
# 全部 target 见 `make help`

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── 可覆盖变量 ────────────────────────────────────────────────
PG_CONTAINER ?= rss2cubox-pg
PG_IMAGE     ?= postgres:17-alpine
PG_PORT      ?= 5434
PG_USER      ?= postgres
PG_PASSWORD  ?= postgres
PG_DB        ?= rss2cubox
LOCAL_DB_URL ?= postgresql://$(PG_USER):$(PG_PASSWORD)@localhost:$(PG_PORT)/$(PG_DB)

WEB_DIR      ?= web
WEB_PORT     ?= 3424
# make dev 时是否顺带跑一次后端 pipeline（0 = 只起前端）
RUN_ON_DEV   ?= 1
# make run 是否走 run_local_sync.sh（1 = 带 flock + prediction loop，0 = 裸跑 runner）
RUN_VIA_SH   ?= 0

UV   := uv
NPX  := npx

.PHONY: help up deps db db-init db-wait db-stop db-down db-logs db-psql db-reset \
        run loop web dev doctor test lint logs cron-install cron-uninstall cron-list clean \
        cost cost-pricing cost-refresh config config-help \
        policy policy-dry policy-status policy-init policy-triage policy-enrich \
        policy-cron-install policy-cron-uninstall

# ── 帮助 ──────────────────────────────────────────────────────
help: ## 显示所有可用命令
	@echo "rss2cubox — 本地开发命令"
	@echo
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "当前配置: 容器=$(PG_CONTAINER) 端口=$(PG_PORT) 库=$(PG_DB) 前端=$(WEB_PORT)"
	@echo "覆盖示例: make db PG_PORT=5435 / make dev RUN_ON_DEV=0"

# ── 环境准备 ──────────────────────────────────────────────────
up: db deps db-init ## 一次性准备环境：起 DB + 装依赖 + 建表
	@echo
	@echo "✓ 环境就绪。接下来："
	@echo "    make run    跑一次后端 pipeline"
	@echo "    make web    起前端 dev server (http://localhost:$(WEB_PORT))"
	@echo "    make dev    两者一起"

deps: ## 安装依赖（uv sync + web npm install）
	@echo "→ Python 依赖 (uv sync --extra dev)"
	@$(UV) sync --extra dev
	@if [ -d "$(WEB_DIR)" ] && [ -f "$(WEB_DIR)/package.json" ]; then \
	  if [ -d "$(WEB_DIR)/node_modules" ]; then \
	    echo "✓ 前端依赖已存在，跳过 npm install"; \
	  else \
	    echo "→ 前端依赖 (npm install)"; \
	    (cd $(WEB_DIR) && npm install); \
	  fi; \
	fi

# ── 数据库 ────────────────────────────────────────────────────
db: ## 启动本地 PostgreSQL 容器（幂等）并等待就绪
	@state=$$(docker ps -q -f name=^$(PG_CONTAINER)$$ 2>/dev/null); \
	if [ -n "$$state" ]; then \
	  echo "✓ 容器 $(PG_CONTAINER) 已在运行"; \
	else \
	  if [ -n "$$(docker ps -aq -f name=^$(PG_CONTAINER)$$ 2>/dev/null)" ]; then \
	    echo "→ 启动已停止的容器 $(PG_CONTAINER)"; \
	    docker start $(PG_CONTAINER) >/dev/null; \
	  else \
	    echo "→ 创建容器 $(PG_CONTAINER)  [$(PG_IMAGE)  宿主端口 $(PG_PORT)]"; \
	    docker run -d --name $(PG_CONTAINER) --restart unless-stopped \
	      -e POSTGRES_USER=$(PG_USER) \
	      -e POSTGRES_PASSWORD=$(PG_PASSWORD) \
	      -e POSTGRES_DB=$(PG_DB) \
	      -p $(PG_PORT):5432 \
	      --health-cmd "pg_isready -U $(PG_USER) -d $(PG_DB)" \
	      --health-interval 5s --health-timeout 3s --health-retries 12 \
	      $(PG_IMAGE) >/dev/null; \
	  fi; \
	fi
	@$(MAKE) --no-print-directory db-wait

db-wait: ## 等待 PostgreSQL 可连接（最多 60 秒）
	@printf "→ 等待 PostgreSQL 就绪 "
	@for i in $$(seq 1 60); do \
	  if docker exec $(PG_CONTAINER) pg_isready -U $(PG_USER) -d $(PG_DB) >/dev/null 2>&1; then \
	    echo; echo "✓ PostgreSQL 就绪  localhost:$(PG_PORT)/$(PG_DB)"; exit 0; \
	  fi; \
	  printf "."; sleep 1; \
	done; \
	echo; echo "✗ 等待超时，看看日志: make db-logs"; exit 1

db-init: db ## 建表（幂等，CREATE TABLE IF NOT EXISTS）
	@LOCAL_DB_URL='$(LOCAL_DB_URL)' $(UV) run python scripts/init_local_db.py

db-stop: ## 停止 DB 容器（保留数据）
	@docker stop $(PG_CONTAINER) >/dev/null 2>&1 && echo "✓ 已停止 $(PG_CONTAINER)（数据保留）" || echo "· 容器未在运行"

db-down: ## 删除 DB 容器（保留 volume，数据仍在容器层）
	@docker rm -f $(PG_CONTAINER) >/dev/null 2>&1 && echo "✓ 已删除容器 $(PG_CONTAINER)" || echo "· 容器不存在"

db-reset: ## 彻底重置：删容器 + 重建 + 建表（数据全丢）
	@echo "!! 这会删除 $(PG_DB) 的全部数据"
	@read -r -p "确认继续？[y/N] " ans; \
	if [ "$$ans" != "y" ] && [ "$$ans" != "Y" ]; then echo "已取消"; exit 1; fi
	@docker rm -f $(PG_CONTAINER) >/dev/null 2>&1 || true
	@$(MAKE) --no-print-directory db db-init
	@echo "✓ 已重置"

db-logs: ## 查看 DB 容器日志
	@docker logs --tail 100 -f $(PG_CONTAINER)

db-psql: ## 进入 psql 交互终端
	@docker exec -it $(PG_CONTAINER) psql -U $(PG_USER) -d $(PG_DB)

# ── 运行 ──────────────────────────────────────────────────────
run: db-wait ## 跑一次后端 pipeline（fetch → enrich → push → global_agent）
	@if [ "$(RUN_VIA_SH)" = "1" ]; then \
	  echo "→ scripts/run_local_sync.sh（含 flock + prediction loop）"; \
	  LOCAL_DB_URL='$(LOCAL_DB_URL)' scripts/run_local_sync.sh; \
	else \
	  echo "→ uv run rss2cubox"; \
	  LOCAL_DB_URL='$(LOCAL_DB_URL)' $(UV) run rss2cubox; \
	fi

loop: db-wait ## 跑 run_local_sync.sh（含 flock 防重入 + 预测闭环 + JSONL 日志）
	@LOCAL_DB_URL='$(LOCAL_DB_URL)' scripts/run_local_sync.sh

# ── 政策信源（独立于主 RSS 链路）────────────────────────────
policy-init: db ## 建政策相关的表（policy_documents / policy_source_state）
	@LOCAL_DB_URL='$(LOCAL_DB_URL)' $(UV) run python -c \
	  "from rss2cubox.policy import ensure_policy_schema; import sys; sys.exit(0 if ensure_policy_schema() else 1)" \
	  && echo "✓ 政策表已就绪"

policy: db-wait policy-init ## 抓取政策信源并入库（配置见 policy_sources.toml）
	@LOCAL_DB_URL='$(LOCAL_DB_URL)' $(UV) run python -m rss2cubox.policy_runner $(POLICY_ARGS)

policy-dry: ## 只抓取和解析，不写数据库（验证选择器用）
	@LOCAL_DB_URL='$(LOCAL_DB_URL)' $(UV) run python -m rss2cubox.policy_runner --dry-run $(POLICY_ARGS)

policy-triage: db-wait policy-init ## 预筛：标题批量打分，筛出 AI 相关的（便宜）
	@LOCAL_DB_URL='$(LOCAL_DB_URL)' $(UV) run python -m rss2cubox.policy_runner --triage $(POLICY_ARGS)

policy-enrich: db-wait policy-init ## 预筛 + 逐篇结构化抽取（会调 LLM，~$0.14/篇）
	@LOCAL_DB_URL='$(LOCAL_DB_URL)' $(UV) run python -m rss2cubox.policy_runner --enrich-only $(POLICY_ARGS)

policy-status: db-wait ## 查看政策信源健康度与疑似失效站点
	@LOCAL_DB_URL='$(LOCAL_DB_URL)' $(UV) run python -m rss2cubox.policy_runner --status

web: db-wait ## 起前端 dev server（http://localhost:3424）
	@echo "→ http://localhost:$(WEB_PORT)"
	@cd $(WEB_DIR) && npm run dev

dev: db db-init ## 一次性启动前后端：DB + 后端跑一次 + 前端常驻（Ctrl-C 全部退出）
	@echo "════════════════════════════════════════════"
	@echo "  后端 pipeline : $$([ "$(RUN_ON_DEV)" = "1" ] && echo "跑一次（后台）" || echo "跳过 (RUN_ON_DEV=0)")"
	@echo "  前端 dev      : http://localhost:$(WEB_PORT)"
	@echo "  Ctrl-C 退出全部"
	@echo "════════════════════════════════════════════"
	@trap 'kill 0' INT TERM EXIT; \
	if [ "$(RUN_ON_DEV)" = "1" ]; then \
	  ( LOCAL_DB_URL='$(LOCAL_DB_URL)' $(UV) run rss2cubox 2>&1 | sed 's/^/[backend]  /' ) & \
	fi; \
	( cd $(WEB_DIR) && npm run dev 2>&1 | sed 's/^/[web]      /' ) & \
	wait

# ── 体检 / 测试 / 日志 ────────────────────────────────────────
doctor: ## 体检：DB / LLM 网关 / IC / RSS 源连通性
	@bash scripts/doctor.sh

test: ## 跑全量 pytest
	@$(UV) run pytest -q

lint: ## 类型检查（mypy，若已安装）
	@$(UV) run mypy src/ 2>/dev/null || echo "· mypy 未安装或无配置，跳过"

logs: ## tail 最新一次 cron 日志
	@latest=$$(ls -1t logs/cron/*/*.log 2>/dev/null | head -1); \
	if [ -n "$$latest" ]; then echo "→ $$latest"; tail -f "$$latest"; \
	else echo "· 还没有日志，先 make run 或 make loop"; fi

cost: ## 核算最新一次运行的真实成本（按本地 model_pricing.json，不联网）
	@$(UV) run python scripts/agent_cost.py $(COST_ARGS)

cost-pricing: ## 查看本地模型单价表
	@$(UV) run python scripts/agent_cost.py --show-pricing

cost-refresh: ## 从网关重拉单价并覆写 model_pricing.json（唯一联网的成本命令）
	@$(UV) run python scripts/agent_cost.py --refresh-pricing

config: ## 列出全部配置项（标出哪些被 .env 覆盖、哪些必填项缺失）
	@$(UV) run python -m rss2cubox.config $(CONFIG_ARGS)

config-help: ## 列出全部配置项并带上每项的说明
	@$(UV) run python -m rss2cubox.config --help-text

# ── 定时任务 ──────────────────────────────────────────────────
cron-install: ## 安装主链路 crontab（默认每 6 小时，可用 RSS2CUBOX_CRON_SCHEDULE 覆盖）
	@scripts/install_local_cron.sh

cron-uninstall: ## 从 crontab 移除主链路条目（不影响政策信源条目）
	@crontab -l 2>/dev/null | grep -Fv '# rss2cubox local sync' | crontab - \
	  && echo "✓ 已移除主链路条目" || echo "· crontab 里没有主链路条目"

policy-cron-install: ## 安装政策信源 crontab（默认每天 7:30/19:30，可用 POLICY_CRON_SCHEDULE 覆盖）
	@scripts/install_policy_cron.sh

policy-cron-uninstall: ## 从 crontab 移除政策信源条目（不影响主链路）
	@scripts/install_policy_cron.sh --uninstall

cron-list: ## 列出 crontab 里与本项目相关的条目
	@crontab -l 2>/dev/null | grep -F 'rss2cubox' || echo "· 没有安装任何本项目 cron"

clean: ## 清理缓存（不动 .venv / 容器 / 数据）
	@find . -name "__pycache__" -type d -not -path "./.venv/*" -not -path "*/node_modules/*" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .pytest_cache .mypy_cache
	@echo "✓ 已清理 __pycache__ / .pytest_cache / .mypy_cache"
