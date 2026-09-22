"""科技链路 Jev 预筛（影子模式）——给抓取候选打早期重要性分数。

为什么存在：科技链路没有政策侧那样的 triage 层，MAX_ITEMS_PER_RUN 的
总量截断是"先到先得"（feed 顺序 = 分析特权）。本模块在截断**之前**用 Jev
给每篇候选打 importance / AI相关性，落库观察，**不影响任何现有行为**：
- 被分析的文章 → Jev 分数 vs deepseek importance 可对比
- 被截断的文章 → 分数可以看出"截断漏了多少好货"，作为将来切换到
  质量筛选的依据（新表记录候选，被截断的也留痕）。

Jev 未配置（JEV_BASE_URL/KEY 缺失）时整体 no-op；单篇失败只记 WARN，
不阻断主链路 —— 影子模式的第一原则是不给主链路添任何新故障点。
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import psycopg

from rss2cubox.jev_client import jev_configured, jev_systemone

DDL = """
CREATE TABLE IF NOT EXISTS tech_triage_scores (
    article_id  TEXT PRIMARY KEY,
    importance  REAL,
    relevance   REAL,
    probabilities JSONB DEFAULT '{}',
    model       TEXT,
    run_id      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tech_triage_run ON tech_triage_scores(run_id);
"""

# score 题的等级锚定与主链路 enrich 的 importance 语义对齐
#（prompts/enrich.yaml 的判定标准），保证两套分数可对比。
IMPORTANCE_CRITERIA = [
    "1 无关噪音：与AI/科技产业无关",
    "2 常规动态：产品更新、版本发布、常规报道",
    "3 值得关注：行业趋势、融资、政策影响、值得追踪的产品动作",
    "4 重要信号：可能改变市场格局的发布/合作/监管/技术突破",
    "5 重大事件：行业分水岭级别的发布、法案、突破",
]

RELEVANCE_INSTRUCTIONS = "该内容是否与人工智能、大模型、智能体、科技产业直接相关？"


def tech_triage_enabled() -> bool:
    if os.getenv("TECH_TRIAGE_ENABLED", "true").lower() in ("false", "0", "no"):
        return False
    return jev_configured()


def _state_for(item: dict[str, Any]) -> str:
    title = str(item.get("title", "")).strip()
    summary = str(item.get("summary", "") or "").strip()[:500]
    return f"标题：{title}\n摘要：{summary}" if summary else f"标题：{title}"


def _score_one(item: dict[str, Any], run_id: str, log_event: Any) -> dict[str, Any] | None:
    eid = str(item.get("eid", "")).strip()
    if not eid:
        return None
    data = jev_systemone(
        _state_for(item),
        {
            "importance": {
                "type": "score",
                "instructions": "这篇科技资讯的重要性等级",
                "criteria": IMPORTANCE_CRITERIA,
            },
            "relevance": {"type": "noul", "instructions": RELEVANCE_INSTRUCTIONS},
        },
        log_event=log_event,
        doc_id=eid,
        stage="tech_triage",
    )
    if not data:
        return None
    answers = data.get("answers") or {}
    imp = (answers.get("importance") or {}).get("score")
    rel = (answers.get("relevance") or {}).get("noul")
    if imp is None:
        return None
    return {
        "article_id": eid,
        "importance": float(imp),
        "relevance": float(rel) if rel is not None else None,
        "probabilities": {
            k: (v.get("probabilities") if isinstance(v, dict) else None) or {}
            for k, v in answers.items()
        },
        "model": data.get("model"),
        "run_id": run_id,
    }


def score_candidates(
    candidates: list[dict[str, Any]],
    *,
    run_id: str,
    db_url: str | None,
    log_event: Any = None,
    max_candidates: int | None = None,
    concurrency: int | None = None,
) -> int:
    """并发给候选打分并写入 tech_triage_scores。返回成功条数（用于 stats）。"""
    if not candidates or not db_url or not tech_triage_enabled():
        return 0
    if max_candidates is None:
        max_candidates = int(os.getenv("TECH_TRIAGE_MAX_CANDIDATES", "3000"))
    if concurrency is None:
        concurrency = int(os.getenv("TECH_TRIAGE_CONCURRENCY", "8"))
    batch = candidates[: max(1, max_candidates)]
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        scored = [
            row
            for row in pool.map(lambda it: _score_one(it, run_id, log_event), batch)
            if row
        ]
    if not scored:
        return 0
    import json as _json

    for row in scored:
        row["probabilities"] = _json.dumps(row.get("probabilities") or {}, ensure_ascii=False)
    try:
        with psycopg.connect(db_url) as conn:
            conn.execute(DDL)
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO tech_triage_scores
                        (article_id, importance, relevance, probabilities, model, run_id)
                        VALUES (%(article_id)s, %(importance)s, %(relevance)s,
                                %(probabilities)s, %(model)s, %(run_id)s)
                        ON CONFLICT (article_id) DO UPDATE SET
                            importance = EXCLUDED.importance,
                            relevance = EXCLUDED.relevance,
                            probabilities = EXCLUDED.probabilities,
                            model = EXCLUDED.model,
                            run_id = EXCLUDED.run_id,
                            created_at = now()""",
                    scored,
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        if log_event:
            log_event("WARN", "tech_triage_save_failed", stage="tech_triage", error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return 0
    if log_event:
        log_event(
            "INFO",
            "tech_triage_done",
            stage="tech_triage",
            input=len(batch),
            scored=len(scored),
            avg_importance=round(sum(r["importance"] for r in scored) / len(scored), 2),
        )
    return len(scored)
