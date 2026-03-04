from __future__ import annotations

import json
import re
from typing import Any


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
            "reason": str(item.get("reason", "")),
            "tags": item.get("tags", []) if isinstance(item.get("tags", []), list) else [],
            "brief": str(item.get("brief", "")),
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
        "You are a strict RSS curator. Use only the provided tool to return analysis results. "
        "Rules: keep high-signal technical/news content, reject ads, promo spam, hiring-only posts, low-info reposts. "
        "score must be 0..1."
    )
    user_prompt = json.dumps(items, ensure_ascii=False)
    return {
        "model": model,
        "max_tokens": 2000,
        "temperature": 0.1,
        "system": system_prompt,
        "tools": [
            {
                "name": "analyze_batch",
                "description": "Return structured analysis for RSS entries.",
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
                                    "reason": {"type": "string"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                    "brief": {"type": "string"},
                                },
                                "required": ["eid", "keep", "score", "reason", "tags", "brief"],
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
