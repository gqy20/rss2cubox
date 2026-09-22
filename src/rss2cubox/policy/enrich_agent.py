"""政策文件结构化抽取 Agent。

为什么不复用 enrich_agent：主链路的 prompt 围绕"AI 与智能体领域"硬编码，
signal_type / market_stage / evidence_type 都是科技产品视角的枚举，拿去量法规
文件会失真。这里用的是一套政策本体：管辖权、法规位阶、立法阶段、生效日期、
适用主体、义务强度。

防幻觉是首要目标 —— source_quote 是 schema required 字段，必须是原文逐字引句，
以便人工抽查时能立刻判断模型是不是在编。
"""
from __future__ import annotations

import json
import os
import time
from functools import partial
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import (
    _agent_timeout,
    _budget,
    make_sdk_logger,
    run_json_agent,
    run_with_fallback,
)
from rss2cubox.policy.engine import parse_policy_date
from rss2cubox.prompt_registry import get, param

INSTRUMENT_TYPES = [
    "法律",
    "行政法规",
    "部门规章",
    "地方性法规",
    "地方政府规章",
    "规范性文件",
    "指导意见",
    "征求意见稿",
    "技术标准",
    "规划",
    "通知公告",
    "司法解释",
    "其他",
]

STAGES = ["征求意见", "已发布", "已生效", "已修订", "已废止", "不明"]

OBLIGATION_LEVELS = ["强制", "推荐", "自愿", "不适用"]

# 活跃政策主线（受控词表）。判定的是文件属于哪条叙事线，不是文件主题——
# 一份文件只归入最贴切的一条；不属于任何主线时为 None。
POLICY_LINEAGES = [
    "十五五规划体系",
    "人工智能+行动",
    "AI安全与监管",
    "数据要素与流通",
    "算力与数字基础设施",
]

# Jev 交叉校验 policy_lineage 用的 choice 题型 criteria：
# 前五个 key 必须与 POLICY_LINEAGES 完全一致（tests/test_jev_client.py 校验），
# 额外提供"不属于任何主线"兜底项 —— Jev 判不属于而 deep 判了主线，是最值得
# 人工复核的分歧形态。
LINEAGE_CHOICE_CRITERIA = {
    "十五五规划体系": "各级十五五规划纲要、专项规划及分解落地方案",
    "人工智能+行动": "AI赋能产业、应用场景开放、大模型/智能体产业培育、词元经济",
    "AI安全与监管": "生成式AI、算法备案、深度合成、安全标准与治理框架",
    "数据要素与流通": "数据产权、交易流通、公共数据授权运营、数据出境",
    "算力与数字基础设施": "算力布局、数据中心、网络与算力调度",
    "不属于任何主线": "以上都不贴切",
}

# system_prompt / 输出 schema / user 静态指令集中在项目根 prompts/policy_enrich.yaml，
# enum 与上方三个常量的同步由 tests/test_prompts.py 校验。
_PROMPT = get("policy_enrich")

SYSTEM_PROMPT = _PROMPT.system_prompt
POLICY_ENRICH_SCHEMA: dict[str, Any] = _PROMPT.output_schema


def _build_prompt(doc: dict[str, Any], full_text: str | None) -> str:
    body = (full_text or "").strip()
    max_chars = param("policy_enrich", "max_text_chars", 12000, env_var="POLICY_ENRICH_MAX_TEXT_CHARS")
    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars]

    return json.dumps(
        {
            "title": doc.get("title", ""),
            "url": doc.get("url", ""),
            "region": doc.get("region", ""),
            "level": doc.get("level", ""),
            "site_name": doc.get("site_name", ""),
            "published_at": str(doc.get("published_at") or ""),
            "has_full_text": bool(body),
            "text_truncated": truncated,
            "full_text": body,
            "instructions": _PROMPT.instructions_list,
        },
        ensure_ascii=False,
    )


def _coerce_enriched(payload: dict[str, Any]) -> dict[str, Any]:
    """收敛模型输出的类型与枚举，越界值降级为安全默认，避免脏数据入库。"""
    from rss2cubox.policy.store import _ENRICH_COLUMNS  # 延迟导入避免循环

    out: dict[str, Any] = {}

    def _text(key: str, limit: int = 400) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text[:limit] or None

    for key in ("issuing_authority", "jurisdiction", "document_number", "summary",
                "ai_relevance_reason", "source_quote"):
        value = _text(key, limit=1200 if key in ("summary", "source_quote", "ai_relevance_reason") else 200)
        if value is not None:
            out[key] = value

    # 日期字段必须归一化成 ISO，否则模型返回「2026年9月15日」「尚未生效」
    # 这类字符串时 PostgreSQL 会拒绍转型，导致整个 UPDATE 失败、enrich 结果静默丢失。
    for key in ("effective_date", "comment_deadline"):
        raw = payload.get(key)
        if raw is None:
            continue
        dt, _matched = parse_policy_date(str(raw))
        out[key] = dt.date().isoformat() if dt else None

    instrument_type = _text("instrument_type", 40)
    out["instrument_type"] = instrument_type if instrument_type in INSTRUMENT_TYPES else "其他"

    stage = _text("stage", 20)
    out["stage"] = stage if stage in STAGES else "不明"

    obligation = _text("obligation_level", 20)
    out["obligation_level"] = obligation if obligation in OBLIGATION_LEVELS else "不适用"

    lineage = _text("policy_lineage", 40)
    out["policy_lineage"] = lineage if lineage in POLICY_LINEAGES else None

    for key in ("ai_relevance", "confidence"):
        value = payload.get(key)
        out[key] = int(value) if isinstance(value, int) and 1 <= value <= 5 else 1

    for key in ("affected_parties", "key_provisions"):
        raw = payload.get(key)
        if isinstance(raw, list):
            cleaned = [str(x).strip()[:300] for x in raw if str(x).strip()][:12]
        else:
            cleaned = []
        out[key] = cleaned

    # 只有标题没正文时，强制压低 confidence —— 模型经常不听 prompt 的这条约束
    if not str(payload.get("_has_full_text", "")).strip():
        out["confidence"] = min(out["confidence"], 2)
        if not out.get("key_provisions"):
            out["key_provisions"] = []

    return {k: v for k, v in out.items() if k in _ENRICH_COLUMNS}


async def _enrich_one(
    doc: dict[str, Any],
    full_text: str | None,
    log_event: Any | None = None,
) -> tuple[dict[str, Any] | None, str]:
    sdk_logger = make_sdk_logger(
        "policy_enrich", log_event=log_event, doc_id=doc.get("id", ""), url=doc.get("url", ""),
        prompt_version=_PROMPT.version,
    )
    try:
        payload = await run_with_fallback(
            partial(
                run_json_agent,
                prompt=_build_prompt(doc, full_text),
                system_prompt=SYSTEM_PROMPT,
                schema=POLICY_ENRICH_SCHEMA,
                allowed_tools=[],
                mcp_servers=None,
                max_turns=param("policy_enrich", "max_turns", 6),
                max_budget_usd=_budget("POLICY_ENRICH_MAX_BUDGET_USD", param("policy_enrich", "max_budget_usd", 1.0)),
                timeout_seconds=_agent_timeout(
                    "POLICY_ENRICH_TIMEOUT_SECONDS",
                    default=param("policy_enrich", "timeout_seconds", 180),
                    minimum=60,
                ),
                setting_sources=None,
                sdk_log=sdk_logger,
            ),
            agent_name="policy_enrich",
            validate=lambda d: bool(str(d.get("source_quote", "")).strip()) and bool(str(d.get("summary", "")).strip()),
            sdk_log=log_event,
        )
    except TimeoutError:
        return None, "timeout"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:200]}"

    if not isinstance(payload, dict):
        return None, "invalid_payload"
    if not str(payload.get("source_quote", "")).strip():
        # source_quote 是防幻觉的锚点，缺了就不要这份结果
        return None, "missing_source_quote"

    enriched = _coerce_enriched({**payload, "_has_full_text": "1" if (full_text or "").strip() else ""})
    # Jev 交叉校验主线归属：分歧只记录进 enrich_meta（观察期不改数据），
    # 未配置/失败完全无感。同步 requests 放线程里跑，避免阻塞 anyio 事件循环。
    await anyio.to_thread.run_sync(
        lambda: _jev_lineage_check(doc, enriched, log_event)
    )
    return enriched, "ok"


def _jev_lineage_check(
    doc: dict[str, Any],
    enriched: dict[str, Any],
    log_event: Any = None,
) -> None:
    """用 Jev choice 题复判 policy_lineage，结果与一致性写入 enrich_meta.jev_lineage。"""
    from rss2cubox.jev_client import jev_systemone

    doc_id = str(doc.get("id", ""))
    state = f"标题：{doc.get('title', '')}\n摘要：{enriched.get('summary') or ''}"
    data = jev_systemone(
        state,
        {"lineage": {
            "type": "choice",
            "instructions": "该文件最属于哪条政策主线？",
            "criteria": LINEAGE_CHOICE_CRITERIA,
        }},
        log_event=log_event,
        doc_id=doc_id,
        stage="policy_enrich_jev",
    )
    if not data:
        return
    answer = (data.get("answers") or {}).get("lineage") or {}
    deep = enriched.get("policy_lineage")
    pick = answer.get("choice")
    meta = enriched.get("enrich_meta") if isinstance(enriched.get("enrich_meta"), dict) else {}
    meta["jev_lineage"] = {
        "choice": pick,
        "confidence": answer.get("confidence"),
        # deep 为 None（不属于任何主线）时 Jev 判"不属于任何主线"才算一致
        "agree": (pick == deep) if deep else pick == "不属于任何主线",
        "model": data.get("model"),
    }
    enriched["enrich_meta"] = meta
    if log_event:
        log_event(
            "INFO",
            "jev_lineage_checked",
            stage="policy_enrich_jev",
            doc_id=doc_id,
            deep=deep,
            jev=pick,
            agree=meta["jev_lineage"]["agree"],
        )


async def _enrich_all(
    docs: list[dict[str, Any]],
    full_texts: dict[str, str],
    log_event: Any | None,
    *,
    max_workers: int,
) -> dict[str, tuple[dict[str, Any] | None, str]]:
    semaphore = anyio.Semaphore(max(1, max_workers))
    results: dict[str, tuple[dict[str, Any] | None, str]] = {}

    async def run_one(doc: dict[str, Any]) -> None:
        doc_id = str(doc.get("id", ""))
        async with semaphore:
            started = time.perf_counter()
            enriched, reason = await _enrich_one(doc, full_texts.get(doc_id), log_event)
            results[doc_id] = (enriched, reason)
            if log_event:
                log_event(
                    "INFO" if enriched else "WARN",
                    "policy_enrich_item_done",
                    stage="policy_enrich",
                    doc_id=doc_id,
                    title=str(doc.get("title", ""))[:80],
                    ok=bool(enriched),
                    reason=reason,
                    ai_relevance=(enriched or {}).get("ai_relevance"),
                    has_full_text=bool(full_texts.get(doc_id)),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

    async with anyio.create_task_group() as tg:
        for doc in docs:
            tg.start_soon(run_one, doc)
    return results


def _fetch_full_texts(
    docs: list[dict[str, Any]],
    *,
    max_workers: int,
    log_event: Any | None = None,
) -> dict[str, str]:
    """并发抓详情页正文。复用主链路的三级降级 trafilatura → playwright → 微信。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from rss2cubox.fulltext_fetcher import fetch_full_text

    out: dict[str, str] = {}
    todo = [d for d in docs if str(d.get("id")) and not (d.get("full_text") or "").strip()]
    for doc in docs:
        existing = (doc.get("full_text") or "").strip()
        if existing:
            out[str(doc["id"])] = existing

    if not todo:
        return out

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {executor.submit(fetch_full_text, str(d.get("url", ""))): d for d in todo}
        for future in as_completed(futures):
            doc = futures[future]
            doc_id = str(doc.get("id"))
            text = ""
            source = ""
            try:
                result = future.result()
                text = (getattr(result, "text", "") or "").strip()
                source = getattr(result, "source", "") or ""
            except Exception as exc:  # noqa: BLE001
                if log_event:
                    log_event("WARN", "policy_fulltext_failed", stage="policy_enrich",
                              doc_id=doc_id, error=f"{type(exc).__name__}")
            if text:
                out[doc_id] = text
            if log_event:
                log_event("INFO" if text else "WARN", "policy_fulltext_fetched", stage="policy_enrich",
                          doc_id=doc_id, chars=len(text), source=source)
    return out


def enrich_policy_documents(
    docs: list[dict[str, Any]],
    *,
    fetch_full_text_enabled: bool = True,
    max_workers: int | None = None,
    fulltext_workers: int | None = None,
    log_event: Any | None = None,
) -> dict[str, Any]:
    """对一批政策文件做结构化抽取，返回 {doc_id: (enriched|None, reason)} 与统计。"""
    if not docs:
        return {"results": {}, "stats": {"total": 0, "succeeded": 0, "failed": 0, "fulltext": 0}}

    workers = max_workers or param("policy_enrich", "max_workers", 4, env_var="POLICY_ENRICH_MAX_WORKERS", minimum=1)
    ft_workers = fulltext_workers or param("policy_enrich", "fulltext_workers", 6, env_var="POLICY_FULLTEXT_MAX_WORKERS", minimum=1)

    full_texts: dict[str, str] = {}
    if fetch_full_text_enabled:
        full_texts = _fetch_full_texts(docs, max_workers=ft_workers, log_event=log_event)

    if log_event:
        log_event("INFO", "policy_enrich_start", stage="policy_enrich",
                  count=len(docs), max_workers=workers,
                  with_full_text=len(full_texts))

    results = anyio.run(partial(_enrich_all, docs, full_texts, log_event, max_workers=workers))

    stats = {
        "total": len(docs),
        "succeeded": sum(1 for v in results.values() if v[0]),
        "failed": sum(1 for v in results.values() if not v[0]),
        "fulltext": len(full_texts),
    }
    if log_event:
        log_event("INFO", "policy_enrich_done", stage="policy_enrich", **stats)
    return {"results": results, "stats": stats, "full_texts": full_texts}
