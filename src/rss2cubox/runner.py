#!/usr/bin/env python3
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

FEEDS_FILE = Path(os.getenv("FEEDS_FILE", "feeds.txt"))
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))

CUBOX_API_URL = os.getenv("CUBOX_API_URL")
CUBOX_FOLDER = os.getenv("CUBOX_FOLDER", "RSS Inbox")
KEYWORDS_INCLUDE = [k.strip() for k in os.getenv("KEYWORDS_INCLUDE", "").split(",") if k.strip()]
KEYWORDS_EXCLUDE = [k.strip() for k in os.getenv("KEYWORDS_EXCLUDE", "").split(",") if k.strip()]
MAX_ITEMS_PER_RUN = int(os.getenv("MAX_ITEMS_PER_RUN", "20"))

ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "").strip()


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[WARN] invalid {name}={raw!r}, fallback to {default}")
        return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[WARN] invalid {name}={raw!r}, fallback to {default}")
        return default


AI_MIN_SCORE = env_float("AI_MIN_SCORE", 0.6)
AI_TIMEOUT_SECONDS = env_int("AI_TIMEOUT_SECONDS", 45)


def load_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"sent": {}}
    with STATE_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def stable_id(entry: dict) -> str:
    identifier = entry.get("id") or entry.get("guid")
    if identifier:
        raw = str(identifier)
    else:
        raw = (entry.get("link") or "") + "|" + (entry.get("title") or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def text_blob(entry: dict) -> str:
    return " ".join(
        [
            entry.get("title", "") or "",
            entry.get("summary", "") or "",
            entry.get("description", "") or "",
            entry.get("link", "") or "",
        ]
    ).lower()


def passes_filter(entry: dict) -> bool:
    blob = text_blob(entry)
    if KEYWORDS_INCLUDE and not any(k.lower() in blob for k in KEYWORDS_INCLUDE):
        return False
    if KEYWORDS_EXCLUDE and any(k.lower() in blob for k in KEYWORDS_EXCLUDE):
        return False
    return True


def cubox_save_url(url: str, title: str = "", description: str = "", tags=None, folder: str = "") -> str:
    if not CUBOX_API_URL:
        raise RuntimeError("CUBOX_API_URL is missing.")

    payload = {"type": "url", "content": url}
    if title:
        payload["title"] = title
    if description:
        payload["description"] = description
    if tags:
        payload["tags"] = tags
    if folder:
        payload["folder"] = folder

    response = requests.post(CUBOX_API_URL, json=payload, timeout=30)
    response.raise_for_status()
    return response.text


def ai_analysis_enabled() -> bool:
    return bool(ANTHROPIC_AUTH_TOKEN and ANTHROPIC_MODEL)


def anthropic_messages_url() -> str:
    base = ANTHROPIC_BASE_URL.rstrip("/")
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


def analyze_candidates_with_ai(candidates: list[dict]) -> dict[str, dict]:
    if not candidates or not ai_analysis_enabled():
        return {}

    items = build_ai_items(candidates)

    system_prompt = (
        "You are a strict RSS curator. Use only the provided tool to return analysis results. "
        "Rules: keep high-signal technical/news content, reject ads, promo spam, hiring-only posts, low-info reposts. "
        "score must be 0..1."
    )
    user_prompt = json.dumps(items, ensure_ascii=False)
    headers = {
        "content-type": "application/json",
        "x-api-key": ANTHROPIC_AUTH_TOKEN,
        "anthropic-version": "2023-06-01",
        "authorization": f"Bearer {ANTHROPIC_AUTH_TOKEN}",
    }
    payload = {
        "model": ANTHROPIC_MODEL,
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

    try:
        response = requests.post(
            anthropic_messages_url(),
            headers=headers,
            json=payload,
            timeout=AI_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        parsed = extract_tool_use_results(data)
        if parsed:
            return parsed
        # Compatibility fallback for gateways that return plain text JSON.
        parsed = extract_text_results(data)
        if parsed:
            return parsed
        print("[WARN] AI analysis empty output, fallback to keyword-only mode")
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] AI analysis failed, fallback to keyword-only mode: {exc}")
        return {}


def main() -> None:
    feeds = load_lines(FEEDS_FILE)
    state = load_state()
    sent = state.get("sent", {})
    ai = state.get("ai", {})

    candidates: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for feed_url in feeds:
        parsed = feedparser.parse(feed_url)
        if getattr(parsed, "bozo", False):
            print(f"[WARN] skip invalid feed: {feed_url}")
            continue

        for entry in parsed.entries:
            eid = stable_id(entry)
            if eid in sent:
                continue
            if not entry.get("link"):
                continue
            if not passes_filter(entry):
                continue

            url = entry["link"]
            title = entry.get("title", "") or ""
            description = (entry.get("summary", "") or "").strip()
            if len(description) > 600:
                description = description[:600] + "..."
            candidates.append(
                {
                    "eid": eid,
                    "url": url,
                    "title": title,
                    "description": description,
                }
            )

    analyses = analyze_candidates_with_ai(candidates)

    pushed = 0
    for item in candidates:
        if pushed >= MAX_ITEMS_PER_RUN:
            break

        eid = item["eid"]
        url = item["url"]
        title = item["title"]
        description = item["description"]
        tags = None

        result = analyses.get(eid)
        if result:
            ai[eid] = {
                "keep": result.get("keep", False),
                "score": result.get("score", 0.0),
                "reason": result.get("reason", ""),
                "ts": now,
                "model": ANTHROPIC_MODEL,
            }
            if not result.get("keep", False):
                continue
            if float(result.get("score", 0.0)) < AI_MIN_SCORE:
                continue
            brief = str(result.get("brief", "")).strip()
            if brief:
                description = brief[:600]
            if result.get("tags"):
                tags = result["tags"]

        try:
            cubox_save_url(
                url=url,
                title=title,
                description=description,
                tags=tags,
                folder=CUBOX_FOLDER,
            )
            sent[eid] = {"url": url, "ts": now}
            pushed += 1
            time.sleep(0.3)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] push failed: {url} -> {exc}")

    state["sent"] = sent
    state["ai"] = ai
    save_state(state)
    print(f"Done. Pushed {pushed} items. State size={len(sent)}")


if __name__ == "__main__":
    main()
