"""全部配置项的唯一声明处。

设计原则
--------
1. **单一事实来源**：每个配置项的名字、类型、默认值、分组、说明只在这里声明一次。
   代码里各模块仍可以用 os.getenv 直接读，但 `tests/test_config_registry.py`
   会扫描全仓，强制要求每个被读取的变量都已在此登记且默认值一致 —— 这样不必
   一次性重写 10 个模块，也能保证注册表不会和代码漂移。
2. **.env 只放两类东西**：必填项（凭据/DB/IC），以及当前**实际偏离默认值**的调优结果。
   等于默认值的一律不写进 .env —— 那是噪音。默认值应该改在这里。
3. `python -m rss2cubox.config` 可以打印全部配置、标出哪些被环境覆盖、哪些必填项缺失。

用法
----
    from rss2cubox.config import cfg
    cfg.int("MAX_ITEMS_PER_RUN")
    cfg.bool("ENRICH_AGENT_ENABLED")
    cfg.str("IC_API_URL")
    cfg.is_overridden("MAX_ITEMS_PER_RUN")
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

# ── 分组定义（顺序即输出顺序）──────────────────────────────
GROUPS: list[tuple[str, str]] = [
    ("gateway", "LLM 网关"),
    ("storage", "存储"),
    ("ic", "IC 文章库"),
    ("schedule", "调度与上限"),
    ("fetch", "RSS 抓取"),
    ("fulltext", "全文抓取"),
    ("enrich", "enrich（逐篇结构化）"),
    ("global", "global_agent（全局洞察）"),
    ("prediction", "预测闭环"),
    ("policy", "政策信源"),
    ("agentsdk", "Claude Agent SDK"),
    ("runtime", "运行时"),
    ("legacy", "历史迁移脚本"),
]

# 必填项：缺失时 `python -m rss2cubox.config` 会报警
REQUIRED: frozenset[str] = frozenset({
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
})


@dataclass(frozen=True)
class Setting:
    name: str
    kind: str            # bool | int | float | str | csv
    default: Any
    group: str
    help: str


# ── 注册表 ────────────────────────────────────────────────
# (name, kind, default, group, help)
_TABLE: list[tuple[str, str, Any, str, str]] = [
    # gateway
    ("ANTHROPIC_AUTH_TOKEN", "str", None, "gateway", "网关 token，走 Authorization: Bearer。不要再同时设 ANTHROPIC_API_KEY，否则每个请求会发两个凭据头"),
    ("ANTHROPIC_BASE_URL", "str", "https://api.anthropic.com", "gateway", "网关地址"),
    ("ANTHROPIC_MODEL", "str", "", "gateway", "模型 ID，必须与网关 /v1/models 返回的 id 完全一致（大小写敏感）"),
    ("ANTHROPIC_API_KEY", "str", None, "gateway", "仅 scripts/agent_cost.py 作为 AUTH_TOKEN 的回退读取；主链路不使用"),

    # storage
    ("LOCAL_DB_URL", "str", "", "storage", "本地 PostgreSQL 连接串。make db 起的专用容器默认 postgresql://postgres:postgres@localhost:5434/rss2cubox"),
    ("NEON_DATABASE_URL", "str", "", "storage", "仅 global_insights 历史链路需要，留空则相关功能跳过"),
    ("NEON_PUSH_ENABLED", "bool", "false", "storage", "是否推送 global_insights 到 Neon"),

    # ic
    ("IC_API_URL", "str", "", "ic", "IC 批量导入端点，也是本地库为空时的去重基线回退来源"),
    ("IC_SOURCE_TYPE", "str", "gqy", "ic", "写入 IC 的 source_type"),
    ("IC_PUSH_ENABLED", "bool", "true", "ic", "false 时完全不调用 IC（推送和读取都不调）"),

    # schedule
    ("MAX_ITEMS_PER_RUN", "int", "300", "schedule", "单轮最多 enrich + 入库多少篇。直接决定耗时与花费：实测 ~5.8 篇/分、~¥0.01/篇"),
    ("MAX_ITEMS_PER_SOURCE", "int", "60", "schedule", "单个源每轮最多贡献多少候选，0=不限流。不限流时一个高产源（实测 openai 单 feed 1193 条）会吃光整轮预算"),
    ("KEYWORDS_INCLUDE", "csv", "", "schedule", "标题/摘要必须命中的关键词，留空=不过滤"),
    ("KEYWORDS_EXCLUDE", "csv", "", "schedule", "标题/摘要命中即丢弃的关键词"),
    ("FEEDS_FILE", "str", "feeds.txt", "schedule", "科技信源清单路径"),
    ("RSSHUB_INSTANCES_FILE", "str", "rsshub_instances.txt", "schedule", "RSSHub 实例池路径，顺序即优先级"),
    ("FEED_CURSOR_LOOKBACK_HOURS", "int", "24", "schedule", "有游标时额外回看多少小时，避免边界漏抓"),

    # fetch
    ("FEED_CONNECT_TIMEOUT_SECONDS", "float", "5.0", "fetch", "connect 超时。可以短，死主机快速失败"),
    ("FEED_READ_TIMEOUT_SECONDS", "float", "30.0", "fetch", "read 超时。⚠️ 不要调小：/juejin/* 这类抓取型路由在健康实例上实测要 19~28s"),
    ("FEED_FETCH_CONCURRENCY", "int", "10", "fetch", "⚠️ 不要调大：部分超时是我们自己的并发打在公共实例上造成的限流"),
    ("WERSS_FETCH_CONCURRENCY", "int", "50", "fetch", "werss 源的并发数"),
    ("WERSS_BASE_URL", "str", "", "fetch", "werss 服务地址，留空则 [werss] 段全部无法解析"),
    ("FEED_FAILURE_COOLDOWN_SECONDS", "int", "60", "fetch", "feed 级熔断基础冷却"),
    ("FEED_FAILURE_COOLDOWN_MAX_SECONDS", "int", "1800", "fetch", "feed 级熔断指数退避封顶"),
    ("RSSHUB_FAILURE_COOLDOWN_SECONDS", "int", "300", "fetch", "RSSHub 实例级基础冷却"),
    ("RSSHUB_FAILURE_COOLDOWN_MAX_SECONDS", "int", "3600", "fetch", "实例级指数退避封顶"),
    ("RSSHUB_MAX_CANDIDATES", "int", "4", "fetch", "单条路由最多试几个实例，0=不限。bilibili/twitter 专用实例不受此限挤压"),
    ("RSSHUB_PREFLIGHT_ENABLED", "bool", "true", "fetch", "抓取前并发探活所有实例，消除冷启动惊群（实测每个坏实例的失败次数 ≈ 并发数）"),
    ("RSSHUB_PREFLIGHT_TIMEOUT_SECONDS", "float", "5.0", "fetch", "预检单实例的 read 超时"),
    ("RSSHUB_PRIVATE_INSTANCES", "csv", "", "fetch", "私有 RSSHub 实例，会被插到实例池最前面"),
    ("RSSHUB_BILIBILI_RETRY_ATTEMPTS", "int", "3", "fetch", "bilibili 专用实例的单候选重试次数"),
    ("RSSHUB_TWITTER_RETRY_ATTEMPTS", "int", "2", "fetch", "twitter 专用实例的单候选重试次数"),
    ("FEED_SECTIONS_DISABLE", "csv", "", "fetch", "停用整类源，token: twitter / bilibili / werss / default。修好服务后删 token 即可恢复，feeds.txt 不用改"),

    # fulltext
    ("FULLTEXT_ENABLED", "bool", "true", "fulltext", "总开关"),
    ("FULLTEXT_ENABLE_PLAYWRIGHT", "bool", "true", "fulltext", "L2 开关。关掉后只用 trafilatura，抓不到就退回摘要"),
    ("FULLTEXT_ITEM_TIMEOUT_S", "int", "30", "fulltext", "单篇总预算，各级由此推导：L1=min(10,T//3) L2=min(20,T//2) L3=min(15,T//2)。⚠️ L2 硬封顶 20s，调大 T 不会给 L2 更多时间"),
    ("FULLTEXT_MAX_WORKERS", "int", "10", "fulltext", "⚠️ 每个 URL 都会 chromium.launch() 一次。实测 10→5 后成功率与吞吐都显著上升"),
    ("FULLTEXT_FLUSH_EVERY", "int", "50", "fulltext", "全文增量落库批大小，0=关闭。一轮抓取 10~20 分钟，不增量写则中断全部重抓"),
    ("PLAYWRIGHT_NAVIGATION_TIMEOUT_S", "int", "15", "fulltext", "page.goto 超时。代码会自动钳制到 L2 预算的一半，避免内部耗时≈外层预算"),
    ("RENDER_EXTRA_WAIT_S", "int", "2", "fulltext", "渲染后额外等待 JS 的时间，同样会被自动钳制"),
    ("WECHAT_FETCH_TIMEOUT_SECONDS", "int", "30", "fulltext", "L3 微信专用抓取的超时"),
    ("JINA_READER_BASE", "str", "https://r.jina.ai/", "fulltext", "Jina Reader 地址，作为 playwright 之前的降级路径"),
    ("JINA_MAX_CHARS", "int", "30000", "fulltext", "Jina 返回正文的截断长度"),

    # enrich
    ("ENRICH_AGENT_ENABLED", "bool", "true", "enrich", "关掉则只抓取入库、不做 AI 分析"),
    ("ENRICH_MAX_WORKERS", "int", "10", "enrich", "并发数。实测 ~5.8 篇/分（6 并发）"),
    ("ENRICH_ITEM_TIMEOUT_SECONDS", "int", "120", "enrich", "单篇超时。重试用递减超时：base × 0.8^attempt"),
    ("ENRICH_MAX_RETRIES", "int", "1", "enrich", "超时后最多重试几次"),
    ("ENRICH_RETRY_BACKOFF_SECONDS", "int", "30", "enrich", "重试前的退避等待"),
    ("ENRICH_MAX_BUDGET_USD", "float", "15.0", "enrich", "⚠️ 单篇预算，不是整轮总量上限，拦不住总花费。控总量用 MAX_ITEMS_PER_RUN"),
    ("ENRICH_FLUSH_EVERY", "int", "25", "enrich", "enrich 结果增量落库批大小，0=关闭。一轮 5 小时，不增量写则中断全丢"),
    ("ENRICH_ENABLE_SKILLS", "bool", "true", "enrich", "是否允许 Skill 工具（需要 setting_sources=['project']）"),

    # global
    ("GLOBAL_AGENT_ENABLED", "bool", "true", "global", "全局洞察开关"),
    ("GLOBAL_AGENT_BATCH_SIZE", "int", "200", "global", "每批文章数"),
    ("GLOBAL_AGENT_MAX_CONCURRENT", "int", "10", "global", "并发批数"),
    ("GLOBAL_AGENT_TIMEOUT_SECONDS", "int", "300", "global", "单批超时"),
    ("GLOBAL_AGENT_MIN_CANDIDATES", "int", "3", "global", "少于此数则跳过全局分析"),
    ("GLOBAL_AGENT_MAX_BUDGET_USD", "float", "50.0", "global", "单批预算（同样是单次上限，不是总量）"),
    ("GLOBAL_AGENT_ENABLE_SKILLS", "bool", "true", "global", "是否允许 Skill 工具"),

    # prediction
    ("PREDICTION_LOOP_ENABLED", "bool", "true", "prediction", "预测闭环总开关"),
    ("PREDICTION_LOOP_STATE_DIR", "str", ".rss2cubox-prediction-loop", "prediction", "各阶段 last_run marker 的存放目录"),
    ("RSS2CUBOX_FORCE_PREDICTION_LOOP", "bool", "false", "prediction", "true 则忽略 marker，强制所有阶段立即执行（调试用）"),
    ("PREDICTION_CLUSTER_INTERVAL_HOURS", "int", "24", "prediction", "cluster 阶段最小间隔"),
    ("PREDICTION_GENERATE_INTERVAL_HOURS", "int", "72", "prediction", "generate 阶段最小间隔。cluster 产出新簇会级联触发"),
    ("PREDICTION_REVIEW_INTERVAL_HOURS", "int", "24", "prediction", "review 阶段最小间隔"),
    ("DAILY_REPORT_INTERVAL_HOURS", "int", "24", "prediction", "日报阶段最小间隔"),
    ("PREDICTION_LOOP_ARTICLE_DAYS", "int", "30", "prediction", "cluster 取最近多少天的文章"),
    ("AGENT_SDK_MAX_STRUCTURED_OUTPUT_RETRIES", "int", "5", "agentsdk", "结构化输出自校正重试上限（传给 CLI 的原生 MAX_STRUCTURED_OUTPUT_RETRIES 环境变量，默认 5）。每次重试重发完整上下文，调高会多花 token；schema 精简后通常一次通过"),
    ("PREDICTION_LOOP_ARTICLE_LIMIT", "int", "500", "prediction", "cluster 从 DB 取多少篇（之后还会被 SIGNAL_CLUSTER_MAX_ARTICLES 二次截断）"),
    ("SIGNAL_CLUSTER_MAX_ARTICLES", "int", "200", "prediction", "单次调用处理的文章数。索引+明细文件模式下 200 篇的索引约 14K tokens（原先全字段内联实测 197,530 tokens、占窗口 98.8%）"),
    ("SIGNAL_CLUSTER_MAX_TURNS", "int", "40", "prediction", "cluster agent 轮数上限。不用 200（daily_report 就是 200，实跑 25 轮烧 798K input tokens），但也不能压到个位数——聚类需要对拿不准的文章翻明细，压太死等于禁止深入（实测 12 轮时模型一次文件都没打开）"),
    ("SIGNAL_CLUSTER_MIN_LINK_COVERAGE", "float", "0.9", "prediction", "links 覆盖率下限，低于此值带明确缺口数字重试。实测同一批数据两次分别给出 200/200 和 95/200，方差很大"),
    ("SIGNAL_CLUSTER_MAX_ATTEMPTS", "int", "2", "prediction", "覆盖率不足时的最大尝试次数。保留覆盖率最高的一次，不会因为重试更差而丢掉好结果"),
    ("PREDICTION_LOOP_CLUSTER_LIMIT", "int", "20", "prediction", "generate 阶段取多少个簇"),
    ("PREDICTION_LOOP_EXISTING_CLUSTER_LIMIT", "int", "200", "prediction", "cluster 阶段带入多少已有簇做去重参考"),
    ("PREDICTION_LOOP_MAX_PREDICTIONS", "int", "3", "prediction", "generate 单次最多产出几条预测"),
    ("PREDICTION_LOOP_REVIEW_LIMIT", "int", "20", "prediction", "review 单次最多处理几条到期预测"),
    ("PREDICTION_LOOP_REVIEW_ARTICLE_LIMIT", "int", "200", "prediction", "review 单条预测取多少篇窗口内文章做证据"),
    ("PREDICTION_LOOP_REVIEW_HISTORY_LIMIT", "int", "150", "prediction", "generate 带入多少条历史复盘做自我改进"),
    ("SIGNAL_CLUSTER_AGENT_TIMEOUT_SECONDS", "float", "1800", "prediction", "cluster 单次调用超时。原默认 300 实测必然 TimeoutError → clusters=0 → 整条闭环空转"),
    ("SIGNAL_CLUSTER_AGENT_MAX_BUDGET_USD", "float", "20.0", "prediction", "cluster 单次预算（CLI 价计；强制通读明细后 ~15 轮 ≈ 2.2M input ≈ $7，网关真实成本约 ¥0.16）"),
    ("TREND_PREDICTION_AGENT_TIMEOUT_SECONDS", "float", "900", "prediction", "generate 单次调用超时"),
    ("TREND_PREDICTION_AGENT_MAX_BUDGET_USD", "float", "10.0", "prediction", "generate 单次预算"),
    ("PREDICTION_REVIEW_AGENT_TIMEOUT_SECONDS", "float", "900", "prediction", "review 单条预测的超时"),
    ("PREDICTION_REVIEW_AGENT_MAX_BUDGET_USD", "float", "10.0", "prediction", "review 单条预算"),
    ("DAILY_REPORT_ENABLED", "bool", "true", "prediction", "日报开关"),
    ("DAILY_REPORT_AGENT_TIMEOUT_SECONDS", "float", "1800", "prediction", "日报单次调用超时"),
    ("DAILY_REPORT_MAX_BUDGET_USD", "float", "50", "prediction", "日报单次预算"),
    ("DAILY_REPORT_ENABLE_SKILLS", "bool", "true", "prediction", "是否允许 Skill 工具"),

    # policy
    ("POLICY_SOURCES_FILE", "str", "policy_sources.toml", "policy", "政策站点适配器配置"),
    ("POLICY_FETCH_CONCURRENCY", "int", "4", "policy", "抓取并发"),
    ("POLICY_CONNECT_TIMEOUT_SECONDS", "int", "5", "policy", "connect 超时"),
    ("POLICY_READ_TIMEOUT_SECONDS", "int", "20", "policy", "read 超时"),
    ("POLICY_STALE_EMPTY_RUNS", "int", "2", "policy", "连续空跑几次判定为疑似失效（改版或被拦）"),
    ("POLICY_TRIAGE_BATCH_SIZE", "int", "10", "policy", "预筛每批标题数。实测 10 稳、20 偏激进、50 撞超时"),
    ("POLICY_TRIAGE_MAX_CONCURRENT", "int", "3", "policy", "预筛并发批数"),
    ("POLICY_TRIAGE_TIMEOUT_SECONDS", "float", "240", "policy", "预筛单批超时"),
    ("POLICY_TRIAGE_MAX_BUDGET_USD", "float", "2.0", "policy", "预筛单批预算"),
    ("POLICY_TRIAGE_LIMIT", "int", "300", "policy", "单次最多预筛多少篇"),
    ("POLICY_ENRICH_MIN_RELEVANCE", "int", "3", "policy", "只对预筛相关度 ≥ 此值的做 deep enrich。实测 442 篇里只有 12% 达标，这一层省掉约 8 倍成本"),
    ("POLICY_ENRICH_LIMIT", "int", "20", "policy", "单次最多 deep enrich 多少篇"),
    ("POLICY_ENRICH_MAX_WORKERS", "int", "4", "policy", "deep enrich 并发"),
    ("POLICY_ENRICH_TIMEOUT_SECONDS", "float", "180", "policy", "deep enrich 单篇超时"),
    ("POLICY_ENRICH_MAX_BUDGET_USD", "float", "1.0", "policy", "deep enrich 单篇预算"),
    ("POLICY_ENRICH_MAX_TEXT_CHARS", "int", "12000", "policy", "喂给 deep enrich 的正文截断长度"),
    ("POLICY_FULLTEXT_MAX_WORKERS", "int", "6", "policy", "政策详情页全文抓取并发"),

    # runtime
    ("RSS2CUBOX_RUN_ID", "str", "", "runtime", "一次运行的稳定 ID，留空则自动生成"),
    ("RSS2CUBOX_PROMPTS_DIR", "str", "", "runtime", "提示词 yml 目录，留空用项目根 prompts/"),

    # legacy
    ("MIGRATE_BATCH_SIZE", "int", "100", "legacy", "scripts/legacy/migrate_processed_items_to_ic.py 的批大小（--batch-size 的默认值）"),
]

def _typed_default(kind: str, default: Any) -> Any:
    """把注册表里声明的默认值归一化成 kind 对应的 Python 类型。

    这样 Setting.default 永远是可直接使用的值，调用方不必再做一次转换，
    防漂移测试也能直接和代码里的字面量比较。
    """
    if default is None:
        return None
    try:
        if kind == "bool":
            if isinstance(default, bool):
                return default
            return str(default).strip().lower() in ("1", "true", "yes", "on")
        if kind == "int":
            return int(float(default))
        if kind == "float":
            return float(default)
        if kind == "csv":
            if isinstance(default, (list, tuple)):
                return [str(x).strip() for x in default if str(x).strip()]
            return [p.strip() for p in str(default).split(",") if p.strip()]
        return default if isinstance(default, str) else str(default)
    except (TypeError, ValueError):
        return default


REGISTRY: dict[str, Setting] = {}
for _name, _kind, _default, _group, _help in _TABLE:
    if _name in REGISTRY:
        raise ValueError(f"配置项重复声明: {_name}")
    if _group not in {g for g, _ in GROUPS}:
        raise ValueError(f"配置项 {_name} 的分组 {_group!r} 未在 GROUPS 中定义")
    REGISTRY[_name] = Setting(_name, _kind, _typed_default(_kind, _default), _group, _help)

_GROUP_OF = {g: label for g, label in GROUPS}


def _raw(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _coerce(setting: Setting, raw: str | None) -> Any:
    """按声明的类型转换；非法值回退默认而不是崩溃（与 sync_pipeline.env_int 一致）。"""
    default = setting.default
    if raw is None:
        return default
    kind = setting.kind
    try:
        if kind == "bool":
            if isinstance(default, bool):
                return raw.lower() in ("1", "true", "yes", "on")
            return raw.lower() in ("1", "true", "yes", "on")
        if kind == "int":
            return int(float(raw))
        if kind == "float":
            return float(raw)
        if kind == "csv":
            return [p.strip() for p in raw.split(",") if p.strip()]
        return raw
    except (TypeError, ValueError):
        return default


class _Cfg:
    """类型化访问入口。"""

    def str(self, name: str) -> str:
        value = self.get(name)
        return "" if value is None else str(value)

    def int(self, name: str) -> int:
        return int(self.get(name) or 0)

    def float(self, name: str) -> float:
        return float(self.get(name) or 0.0)

    def bool(self, name: str) -> bool:
        return bool(self.get(name))

    def csv(self, name: str) -> list[str]:
        value = self.get(name)
        return list(value) if isinstance(value, list) else []

    def get(self, name: str) -> Any:
        setting = REGISTRY.get(name)
        if setting is None:
            # 未登记的变量仍然可读，但会在 drift 测试里被抓住
            return os.getenv(name)
        return _coerce(setting, _raw(name))

    def is_overridden(self, name: str) -> bool:
        return _raw(name) is not None

    def missing_required(self) -> list[str]:
        return sorted(n for n in REQUIRED if not _raw(n))

    def __getattr__(self, name: str) -> Any:
        if name in REGISTRY:
            return self.get(name)
        raise AttributeError(name)


cfg = _Cfg()


def iter_grouped() -> Iterator[tuple[str, str, list[Setting]]]:
    for group, label in GROUPS:
        items = [s for s in REGISTRY.values() if s.group == group]
        if items:
            yield group, label, sorted(items, key=lambda s: s.name)


def _display(value: Any) -> str:
    if value is None:
        return "(未设置)"
    if isinstance(value, list):
        return ",".join(value) if value else "(空)"
    text = str(value)
    return text if len(text) <= 46 else text[:43] + "..."


_SENSITIVE = ("TOKEN", "API_KEY", "PASSWORD", "DB_URL", "DATABASE_URL", "SECRET", "DSN")


def _mask(name: str, value: Any) -> str:
    """凭据类只显示头尾，避免 make config 的输出被贴到 issue 里泄露密钥。

    必须在截断**之前**打码：先截断再取尾部会拿到截断后的中间字符，掩码形同虚设。
    """
    if not any(k in name for k in _SENSITIVE):
        return _display(value)
    if value is None:
        return "(未设置)"
    text = ",".join(value) if isinstance(value, list) else str(value)
    if not text:
        return "(空)"
    if len(text) <= 12:
        return "***"
    return f"{text[:8]}…{text[-4:]}"


def describe(*, show_help: bool = False) -> str:
    lines: list[str] = []
    overridden = sum(1 for n in REGISTRY if cfg.is_overridden(n))
    lines.append(f"共 {len(REGISTRY)} 个配置项，其中 {overridden} 个被环境/.env 覆盖，"
                 f"{len(REGISTRY) - overridden} 个用默认值")
    missing = cfg.missing_required()
    if missing:
        lines.append(f"⚠ 必填但未设置: {', '.join(missing)}")
    lines.append("")
    for group, label, items in iter_grouped():
        lines.append(f"── {label} ({group}) ──")
        for s in items:
            value = cfg.get(s.name)
            mark = "●" if cfg.is_overridden(s.name) else " "
            req = " [必填]" if s.name in REQUIRED else ""
            lines.append(f" {mark} {s.name:44s} {_mask(s.name, value):48s}{req}")
            if show_help and s.help:
                lines.append(f"     └ {s.help}")
        lines.append("")
    lines.append("● = 被环境/.env 覆盖    无标记 = 使用默认值")
    return "\n".join(lines)


def _load_dotenv_for_cli() -> None:
    """仅 CLI 入口用：加载 .env 以便 `make config` 能反映真实生效值。

    不在模块 import 时做，否则会改变库的语义（各入口自己负责加载 .env）。
    与 runner._load_local_env_file 一致：.env 覆盖已有环境变量。
    """
    env_file = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ[key] = value.strip()


def main() -> int:
    import argparse

    _load_dotenv_for_cli()

    parser = argparse.ArgumentParser(description="打印全部配置项")
    parser.add_argument("--help-text", action="store_true", help="同时显示每项的说明")
    parser.add_argument("--overridden-only", action="store_true", help="只显示被覆盖的项")
    parser.add_argument("--group", default="", help="只看某个分组")
    parser.add_argument("--names", action="store_true", help="只输出变量名（脚本用）")
    args = parser.parse_args()

    if args.names:
        for name in sorted(REGISTRY):
            if not args.group or REGISTRY[name].group == args.group:
                if not args.overridden_only or cfg.is_overridden(name):
                    print(name)
        return 0

    if args.overridden_only or args.group:
        rows = []
        for group, label, items in iter_grouped():
            if args.group and group != args.group:
                continue
            for s in items:
                if args.overridden_only and not cfg.is_overridden(s.name):
                    continue
                rows.append((label, s))
        if not rows:
            print("（没有符合条件的配置项）")
            return 0
        current = None
        for label, s in rows:
            if label != current:
                print(f"\n── {label} ──")
                current = label
            print(f"  {s.name:44s} {_mask(s.name, cfg.get(s.name))}")
            if args.help_text and s.help:
                print(f"    └ {s.help}")
        print()
        return 0

    print(describe(show_help=args.help_text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
