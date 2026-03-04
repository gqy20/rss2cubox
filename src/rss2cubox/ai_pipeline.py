from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from rss2cubox.metrics import StageMetrics


def anthropic_messages_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1/messages"):
        return base
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def extract_first_json(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def coerce_analysis_map(parsed: object) -> dict[str, dict]:
    if not isinstance(parsed, list):
        return {}
    out: dict[str, dict] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("eid", "")).strip()
        if not eid:
            continue
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        out[eid] = {
            "keep": bool(item.get("keep", False)),
            "score": score,
            "core_event": str(item.get("core_event", "")),
            "hidden_signal": str(item.get("hidden_signal", "")),
            "actionable": str(item.get("actionable", "")),
            "reason": str(item.get("hidden_signal", item.get("reason", ""))), # Fallback for old pipeline
            "tags": item.get("tags", []) if isinstance(item.get("tags", []), list) else [],
            "brief": str(item.get("core_event", item.get("brief", ""))),
        }
    return out


def extract_tool_use_results(data: dict) -> dict[str, dict]:
    blocks = data.get("content", [])
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        payload = block.get("input")
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            return coerce_analysis_map(payload["results"])
        if isinstance(payload, list):
            return coerce_analysis_map(payload)
    return {}


def extract_text_results(data: dict) -> dict[str, dict]:
    content_blocks = data.get("content", [])
    text = "\n".join(block.get("text", "") for block in content_blocks if isinstance(block, dict))
    parsed = json.loads(extract_first_json(text))
    if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
        return coerce_analysis_map(parsed["results"])
    return coerce_analysis_map(parsed)


def build_ai_items(candidates: list[dict]) -> list[dict]:
    items = []
    for c in candidates:
        items.append(
            {
                "eid": c["eid"],
                "url": c["url"],
                "title": c["title"],
                "description": c["description"][:800],
            }
        )
    return items


def build_ai_payload(model: str, items: list[dict]) -> dict[str, Any]:
    system_prompt = (
        "You are an elite Tech/Business Intelligence Analyst filtering RSS feeds.\n"
        "Your goal is to extract high-value 'signals' from noise.\n"
        "Rules:\n"
        "1. Reject generic news, PR fluff, tool ads, and low-info reposts (keep=false).\n"
        "2. Provide `core_event`: A cold, objective one-sentence summary of the factual event. MUST be in Chinese (简体中文).\n"
        "3. Provide `hidden_signal`: What does this actually mean? The underlying paradigm shift, industry impact, or deep technical implication. MUST be in Chinese (简体中文).\n"
        "4. Provide `actionable`: How should an engineer or tech professional react? MUST be in Chinese (简体中文).\n"
        "5. Provide `score`: 0.0 to 1.0 (>= 0.85 means high value).\n"
        "6. Provide `tags`: 1-3 sharp tech categories. MUST be in Chinese (简体中文).\n"
        "7. ALL generated text and summaries MUST be written in fluent, professional Simplified Chinese (简体中文)."
    )
    user_prompt = json.dumps(items, ensure_ascii=False)
    return {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.1,
        "system": system_prompt,
        "tools": [
            {
                "name": "analyze_batch",
                "description": "Return structured analysis and intelligence signals for RSS entries.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "eid": {"type": "string"},
                                    "keep": {"type": "boolean"},
                                    "score": {"type": "number"},
                                    "core_event": {"type": "string"},
                                    "hidden_signal": {"type": "string"},
                                    "actionable": {"type": "string"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["eid", "keep", "score", "core_event", "hidden_signal", "actionable", "tags"],
                            },
                        }
                    },
                    "required": ["results"],
                },
            }
        ],
        "tool_choice": {"type": "any"},
        "messages": [{"role": "user", "content": user_prompt}],
    }


def ai_analysis_enabled(auth_token: str, model: str) -> bool:
    return bool(auth_token.strip() and model.strip())


def _analyze_batch_with_ai(
    *,
    batch: list[dict],
    stage_metrics: StageMetrics,
    auth_token: str,
    base_url: str,
    model: str,
    timeout_seconds: int,
    retry_attempts: int,
    retry_backoff_seconds: float,
    log_event: Any,
) -> dict[str, dict]:
    if not batch or not ai_analysis_enabled(auth_token, model):
        return {}

    items = build_ai_items(batch)
    headers = {
        "content-type": "application/json",
        "x-api-key": auth_token,
        "anthropic-version": "2023-06-01",
        "authorization": f"Bearer {auth_token}",
    }
    payload = build_ai_payload(model, items)
    batch_eids = [item.get("eid", "") for item in batch]

    for attempt in range(1, max(1, retry_attempts) + 1):
        start = time.perf_counter()
        try:
            response = requests.post(
                anthropic_messages_url(base_url),
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            duration_ms = int((time.perf_counter() - start) * 1000)
            stage_metrics.observe("ai", duration_ms)
            stop_reason = data.get("stop_reason")
            block_types = [block.get("type") for block in data.get("content", []) if isinstance(block, dict)]
            usage = data.get("usage", {})
            log_event(
                "INFO",
                "ai_batch_response",
                stage="ai_analyze",
                batch_size=len(batch),
                attempt=attempt,
                duration_ms=duration_ms,
                stop_reason=stop_reason,
                block_types=block_types,
                usage=usage,
            )
            parsed = extract_tool_use_results(data)
            if parsed:
                return parsed
            parsed = extract_text_results(data)
            if parsed:
                return parsed
            raise ValueError("empty or unrecognized AI output")
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - start) * 1000)
            stage_metrics.observe("ai", duration_ms)
            if attempt >= max(1, retry_attempts):
                log_event(
                    "WARN",
                    "ai_batch_failed",
                    stage="ai_analyze",
                    attempts=attempt,
                    batch_size=len(batch),
                    duration_ms=duration_ms,
                    eids_preview=batch_eids[:3],
                    error=str(exc),
                )
                return {}
            sleep_seconds = retry_backoff_seconds * (2 ** (attempt - 1))
            log_event(
                "WARN",
                "ai_batch_retrying",
                stage="ai_analyze",
                attempt=attempt,
                batch_size=len(batch),
                duration_ms=duration_ms,
                retry_in_seconds=round(sleep_seconds, 3),
                error=str(exc),
            )
            time.sleep(sleep_seconds)
    return {}


def analyze_candidates_with_ai(
    *,
    candidates: list[dict],
    stage_metrics: StageMetrics,
    auth_token: str,
    base_url: str,
    model: str,
    timeout_seconds: int,
    retry_attempts: int,
    retry_backoff_seconds: float,
    batch_size: int,
    max_workers: int = 3,
    log_event: Any,
) -> dict[str, dict]:
    if not candidates or not ai_analysis_enabled(auth_token, model):
        return {}
    out: dict[str, dict] = {}
    size = max(1, batch_size)
    total = len(candidates)
    batches = (total + size - 1) // size

    # Prepare all batches
    batch_list: list[tuple[int, list[dict]]] = []
    for idx in range(0, total, size):
        batch = candidates[idx : idx + size]
        batch_no = idx // size + 1
        batch_list.append((batch_no, batch))
        log_event(
            "INFO",
            "ai_batch_start",
            stage="ai_analyze",
            batch_no=batch_no,
            batches=batches,
            batch_size=len(batch),
        )

    # Process batches in parallel
    def process_batch(batch_no: int, batch: list[dict]) -> dict[str, dict]:
        return _analyze_batch_with_ai(
            batch=batch,
            stage_metrics=stage_metrics,
            auth_token=auth_token,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            retry_attempts=retry_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            log_event=log_event,
        )

    workers = min(max(1, max_workers), len(batch_list))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_batch, bn, b): bn for bn, b in batch_list}
        for future in as_completed(futures):
            try:
                parsed = future.result()
                out.update(parsed)
            except Exception as exc:
                batch_no = futures[future]
                log_event("ERROR", "ai_batch_exception", stage="ai_analyze", batch_no=batch_no, error=str(exc))

    if out:
        log_event("INFO", "ai_analyze_done", stage="ai_analyze", analyzed=len(out), total=total)
    else:
        log_event("WARN", "ai_analyze_empty", stage="ai_analyze", total=total)
    return out
