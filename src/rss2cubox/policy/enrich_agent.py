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

POLICY_ENRICH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issuing_authority": {
            "type": "string",
            "description": "发布机构全称，如「国务院办公厅」「北京市人民政府」「全国网络安全标准化技术委员会」",
        },
        "document_number": {
            "type": ["string", "null"],
            "description": "文号，如「国办发〔2026〕12号」。没有则 null",
        },
        "jurisdiction": {
            "type": "string",
            "description": "管辖范围，如「全国」「北京市」「广东省深圳市」",
        },
        "instrument_type": {"type": "string", "enum": INSTRUMENT_TYPES},
        "stage": {"type": "string", "enum": STAGES},
        "effective_date": {
            "type": ["string", "null"],
            "description": "生效日期 YYYY-MM-DD。未生效或未提及则 null",
        },
        "comment_deadline": {
            "type": ["string", "null"],
            "description": "征求意见截止日期 YYYY-MM-DD。非征求意见稿则 null",
        },
        "affected_parties": {
            "type": "array",
            "items": {"type": "string"},
            "description": "适用/影响的主体，如「生成式AI服务提供者」「算法推荐服务提供者」「数据处理者」",
        },
        "obligation_level": {"type": "string", "enum": OBLIGATION_LEVELS},
        "ai_relevance": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "description": "与 AI/智能体的相关度，判定标准见 system prompt",
        },
        "ai_relevance_reason": {
            "type": "string",
            "description": "给出该相关度评分的具体依据，必须指向原文内容",
        },
        "summary": {
            "type": "string",
            "description": "150 字以内的实质内容摘要，说清楚「要求谁做什么」，不要复述标题",
        },
        "key_provisions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "关键条款要点，每条一句话，最多 6 条。只有标题没有正文时给空数组",
        },
        "source_quote": {
            "type": "string",
            "description": "支撑上述判断的原文逐字引句，≤120 字。没有正文时引标题",
            "minLength": 4,
        },
        "confidence": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "description": "对本次抽取结果的置信度。只有标题没有正文时不应高于 2",
        },
    },
    "required": [
        "issuing_authority",
        "jurisdiction",
        "instrument_type",
        "stage",
        "obligation_level",
        "ai_relevance",
        "ai_relevance_reason",
        "summary",
        "key_provisions",
        "source_quote",
        "confidence",
    ],
}


SYSTEM_PROMPT = (
    "你是中国政策与监管分析专家，任务是把政策文件抽取成结构化字段，供 AI/智能体方向的合规与趋势研判使用。\n"
    "\n"
    "【铁律】\n"
    "1. 只能依据输入提供的标题和正文作答。禁止用你的常识补充文件里没有的信息。\n"
    "2. 任何字段无法从材料确定时，字符串填 null、数组填空数组，绝不允许编造或猜测。\n"
    "3. source_quote 必须是从材料里逐字复制的原文片段（≤120 字），不能改写、不能拼接、不能翻译。"
    "这是人工核查你是否在编造的唯一依据。若只有标题没有正文，就引标题原文。\n"
    "4. summary 要回答「这份文件要求谁、做什么、什么时候」，不要复述标题，不要写「本文强调了…的重要性」这类空话。\n"
    "\n"
    "【instrument_type 判定】按中国法律位阶：法律(全国人大及其常委会) > 行政法规(国务院) > "
    "部门规章(部委令) / 地方性法规(地方人大) > 地方政府规章(地方政府令) > 规范性文件 > 指导意见。"
    "标题含「征求意见稿」一律判为「征求意见稿」，即使它同时是部门规章草案。"
    "TC260/信安标委发布的「实践指南」「基本要求」判为「技术标准」。"
    "「十五五规划」这类判为「规划」。「关于…的通知」若不含实体规则判为「通知公告」。\n"
    "\n"
    "【stage 判定】标题或正文明确「征求…意见」且有截止日期 → 征求意见；"
    "已公布但未到施行日期 → 已发布；施行日期已过 → 已生效；被新文件替代 → 已修订；无法判断 → 不明。\n"
    "\n"
    "【obligation_level】出现「应当」「必须」「不得」「禁止」等强制性表述 → 强制；"
    "「鼓励」「支持」「可以」「建议」→ 推荐；行业标准中自愿采用的 → 自愿；纯人事任免/会议消息等无规制内容 → 不适用。\n"
    "\n"
    "【ai_relevance 评分标准】\n"
    "5 = 直接规制 AI/算法/大模型/智能体本身（如生成式AI服务管理、算法推荐、深度合成、AI安全标准、大模型备案）\n"
    "4 = 虽不点名 AI，但直接约束 AI 系统必然涉及的对象（数据跨境、个人信息处理、自动化决策、训练数据、算力）\n"
    "3 = 行业性政策，AI 是其中一个受影响的应用方向（金融、医疗、交通、教育领域的数字化/智能化条款）\n"
    "2 = 泛数字经济/科技创新政策，与 AI 间接相关\n"
    "1 = 与 AI 基本无关（人事任免、行政区划、财政补贴、环保督察等）\n"
    "ai_relevance_reason 必须指向材料里的具体内容来支撑这个分数，不能只写「与AI相关」。\n"
    "\n"
    "【confidence】材料完整（有正文且条款清晰）可给 4-5；只有标题没有正文时最高只能给 2；"
    "标题含糊、正文与标题不匹配时给 1-2。\n"
    "\n"
    "只输出符合 JSON Schema 的结构化结果。"
)


def _build_prompt(doc: dict[str, Any], full_text: str | None) -> str:
    body = (full_text or "").strip()
    max_chars = int(os.getenv("POLICY_ENRICH_MAX_TEXT_CHARS", "12000"))
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
            "instructions": [
                "严格依据上面的 title 和 full_text 抽取，不得凭常识补充。",
                "has_full_text=false 时 key_provisions 给空数组、confidence 不高于 2。",
                "source_quote 必须是材料里的逐字原文。",
                "无法确定的字段填 null 或空数组。",
            ],
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
        "policy_enrich", log_event=log_event, doc_id=doc.get("id", ""), url=doc.get("url", "")
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
                max_turns=6,
                max_budget_usd=_budget("POLICY_ENRICH_MAX_BUDGET_USD", 1.0),
                timeout_seconds=_agent_timeout("POLICY_ENRICH_TIMEOUT_SECONDS", default=180, minimum=60),
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
    return enriched, "ok"


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

    workers = max_workers or max(1, int(os.getenv("POLICY_ENRICH_MAX_WORKERS", "4")))
    ft_workers = fulltext_workers or max(1, int(os.getenv("POLICY_FULLTEXT_MAX_WORKERS", "6")))

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
