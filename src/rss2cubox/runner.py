#!/usr/bin/env python3
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests

FEEDS_FILE = Path(os.getenv("FEEDS_FILE", "feeds.txt"))
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
RSSHUB_INSTANCES_FILE = Path(os.getenv("RSSHUB_INSTANCES_FILE", "rsshub_instances.txt"))

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
AI_TIMEOUT_SECONDS = env_int("AI_TIMEOUT_SECONDS", 90)
AI_RETRY_ATTEMPTS = env_int("AI_RETRY_ATTEMPTS", 3)
AI_RETRY_BACKOFF_SECONDS = env_float("AI_RETRY_BACKOFF_SECONDS", 1.5)
AI_BATCH_SIZE = env_int("AI_BATCH_SIZE", 5)
AI_MAX_CANDIDATES = env_int("AI_MAX_CANDIDATES", max(MAX_ITEMS_PER_RUN * 2, 1))
DEFAULT_RSSHUB_INSTANCES = ["https://rsshub.rssforever.com", "https://rsshub.app"]


def log_event(level: str, event: str, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def write_step_summary(summary: dict[str, Any]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    lines = [
        "## RSS2Cubox Run Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| feeds_total | {summary.get('feeds_total', 0)} |",
        f"| feeds_invalid | {summary.get('feeds_invalid', 0)} |",
        f"| rsshub_routes | {summary.get('rsshub_routes', 0)} |",
        f"| rsshub_fallback_used | {summary.get('rsshub_fallback_used', 0)} |",
        f"| rsshub_instances | {summary.get('rsshub_instances', 0)} |",
        f"| fetched | {summary.get('fetched', 0)} |",
        f"| deduped | {summary.get('deduped', 0)} |",
        f"| missing_link | {summary.get('missing_link', 0)} |",
        f"| keyword_filtered | {summary.get('keyword_filtered', 0)} |",
        f"| candidates | {summary.get('candidates', 0)} |",
        f"| candidates_selected | {summary.get('candidates_selected', 0)} |",
        f"| ai_enabled | {summary.get('ai_enabled', False)} |",
        f"| ai_analyzed | {summary.get('ai_analyzed', 0)} |",
        f"| ai_missing | {summary.get('ai_missing', 0)} |",
        f"| ai_kept | {summary.get('ai_kept', 0)} |",
        f"| ai_dropped_keep_false | {summary.get('ai_dropped_keep_false', 0)} |",
        f"| ai_dropped_score | {summary.get('ai_dropped_score', 0)} |",
        f"| push_attempted | {summary.get('push_attempted', 0)} |",
        f"| pushed | {summary.get('pushed', 0)} |",
        f"| push_failed | {summary.get('push_failed', 0)} |",
        f"| state_size | {summary.get('state_size', 0)} |",
    ]
    with Path(summary_path).open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def normalize_feed_kind(kind: str, raw: str) -> str:
    if kind in {"rsshub", "direct"}:
        return kind
    return "direct" if raw.startswith(("http://", "https://")) else "rsshub"


def load_feed_specs(path: Path) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    section = "auto"
    with path.open("r", encoding="utf-8") as f:
        for ln in f:
            raw = ln.strip()
            if not raw or raw.startswith("#"):
                continue
            lowered = raw.lower()
            if lowered in {"[rsshub]", "rsshub:"}:
                section = "rsshub"
                continue
            if lowered in {"[direct]", "direct:"}:
                section = "direct"
                continue
            specs.append({"kind": normalize_feed_kind(section, raw), "value": raw})
    return specs


def load_rsshub_instances() -> list[str]:
    instances: list[str] = []
    if RSSHUB_INSTANCES_FILE.exists():
        instances.extend(load_lines(RSSHUB_INSTANCES_FILE))
    if not instances:
        env_value = os.getenv("RSSHUB_INSTANCES", "").strip()
        if env_value:
            instances.extend(part.strip() for part in env_value.split(",") if part.strip())
    if not instances:
        instances = DEFAULT_RSSHUB_INSTANCES[:]
    normalized: list[str] = []
    seen: set[str] = set()
    for instance in instances:
        v = instance.strip().rstrip("/")
        if not v or v in seen:
            continue
        seen.add(v)
        normalized.append(v)
    return normalized


def resolve_feed_urls(feed_kind: str, feed_value: str, rsshub_instances: list[str]) -> list[str]:
    value = feed_value.strip()
    if not value:
        return []
    kind = normalize_feed_kind(feed_kind, value)
    if kind == "direct":
        return [value]
    route = value
    if value.startswith("rsshub://"):
        route = value[len("rsshub://") :]
    if route.startswith(("http://", "https://")):
        return [route]
    if not route.startswith("/"):
        route = f"/{route}"
    return [f"{base}{route}" for base in rsshub_instances]


def parse_feed_with_fallback(feed_kind: str, feed_value: str, rsshub_instances: list[str]) -> tuple[str | None, Any | None, int]:
    for idx, candidate_url in enumerate(resolve_feed_urls(feed_kind, feed_value, rsshub_instances), start=1):
        parsed = feedparser.parse(candidate_url)
        if not getattr(parsed, "bozo", False):
            if idx > 1:
                log_event(
                    "WARN",
                    "feed_fallback_used",
                    stage="fetch",
                    feed=feed_value,
                    selected=candidate_url,
                    attempt=idx,
                )
            return candidate_url, parsed, idx
        log_event(
            "WARN",
            "feed_candidate_failed",
            stage="fetch",
            feed=feed_value,
            candidate=candidate_url,
            attempt=idx,
        )
    return None, None, 0


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


def _analyze_batch_with_ai(batch: list[dict]) -> dict[str, dict]:
    if not batch or not ai_analysis_enabled():
        return {}

    items = build_ai_items(batch)

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

    batch_eids = [item.get("eid", "") for item in batch]
    for attempt in range(1, max(1, AI_RETRY_ATTEMPTS) + 1):
        start = time.perf_counter()
        try:
            response = requests.post(
                anthropic_messages_url(),
                headers=headers,
                json=payload,
                timeout=AI_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            duration_ms = int((time.perf_counter() - start) * 1000)
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
            # Compatibility fallback for gateways that return plain text JSON.
            parsed = extract_text_results(data)
            if parsed:
                return parsed
            raise ValueError("empty or unrecognized AI output")
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - start) * 1000)
            if attempt >= max(1, AI_RETRY_ATTEMPTS):
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
            sleep_seconds = AI_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
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


def analyze_candidates_with_ai(candidates: list[dict]) -> dict[str, dict]:
    if not candidates or not ai_analysis_enabled():
        return {}
    batch_size = max(1, AI_BATCH_SIZE)
    out: dict[str, dict] = {}
    total = len(candidates)
    batches = (total + batch_size - 1) // batch_size
    for idx in range(0, total, batch_size):
        batch = candidates[idx : idx + batch_size]
        batch_no = idx // batch_size + 1
        log_event(
            "INFO",
            "ai_batch_start",
            stage="ai_analyze",
            batch_no=batch_no,
            batches=batches,
            batch_size=len(batch),
        )
        parsed = _analyze_batch_with_ai(batch)
        out.update(parsed)
    if out:
        log_event("INFO", "ai_analyze_done", stage="ai_analyze", analyzed=len(out), total=total)
    else:
        log_event("WARN", "ai_analyze_empty", stage="ai_analyze", total=total)
    return out


def main() -> None:
    feed_specs = load_feed_specs(FEEDS_FILE)
    rsshub_instances = load_rsshub_instances()
    state = load_state()
    sent = state.get("sent", {})
    ai = state.get("ai", {})

    candidates: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    stats: dict[str, Any] = {
        "feeds_total": len(feed_specs),
        "feeds_invalid": 0,
        "rsshub_routes": 0,
        "rsshub_fallback_used": 0,
        "rsshub_instances": len(rsshub_instances),
        "fetched": 0,
        "deduped": 0,
        "missing_link": 0,
        "keyword_filtered": 0,
        "candidates": 0,
        "candidates_selected": 0,
        "ai_enabled": ai_analysis_enabled(),
        "ai_analyzed": 0,
        "ai_missing": 0,
        "ai_kept": 0,
        "ai_dropped_keep_false": 0,
        "ai_dropped_score": 0,
        "push_attempted": 0,
        "pushed": 0,
        "push_failed": 0,
        "state_size": 0,
    }
    log_event(
        "INFO",
        "run_start",
        stage="start",
        feeds_total=stats["feeds_total"],
        max_items_per_run=MAX_ITEMS_PER_RUN,
        rsshub_instances=stats["rsshub_instances"],
        ai_enabled=stats["ai_enabled"],
        ai_model=ANTHROPIC_MODEL if stats["ai_enabled"] else "",
    )

    for spec in feed_specs:
        feed_kind = spec["kind"]
        feed_url = spec["value"]
        feed_seen = 0
        feed_candidates = 0
        feed_start = time.perf_counter()
        if feed_kind == "rsshub":
            stats["rsshub_routes"] += 1
        selected_url, parsed, selected_attempt = parse_feed_with_fallback(feed_kind, feed_url, rsshub_instances)
        if selected_url is None or parsed is None:
            stats["feeds_invalid"] += 1
            log_event("WARN", "feed_invalid", stage="fetch", feed=feed_url, kind=feed_kind)
            continue
        resolved_from_pool = selected_url != feed_url and feed_kind == "rsshub"
        if selected_attempt > 1:
            stats["rsshub_fallback_used"] += 1
        if resolved_from_pool:
            log_event(
                "INFO",
                "feed_resolved",
                stage="fetch",
                feed=feed_url,
                kind=feed_kind,
                resolved_url=selected_url,
            )

        for entry in parsed.entries:
            feed_seen += 1
            stats["fetched"] += 1
            eid = stable_id(entry)
            if eid in sent:
                stats["deduped"] += 1
                continue
            if not entry.get("link"):
                stats["missing_link"] += 1
                continue
            if not passes_filter(entry):
                stats["keyword_filtered"] += 1
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
            feed_candidates += 1
        feed_duration_ms = int((time.perf_counter() - feed_start) * 1000)
        log_event(
            "INFO",
            "feed_processed",
            stage="fetch",
            feed=feed_url,
            kind=feed_kind,
            resolved_url=selected_url,
            fetched=feed_seen,
            candidates=feed_candidates,
            duration_ms=feed_duration_ms,
        )

    stats["candidates"] = len(candidates)

    candidates_for_run = candidates[: max(1, AI_MAX_CANDIDATES)]
    stats["candidates_selected"] = len(candidates_for_run)
    if len(candidates_for_run) < len(candidates):
        log_event(
            "INFO",
            "candidates_limited",
            stage="pre_push",
            selected=len(candidates_for_run),
            total=len(candidates),
        )

    analyses = analyze_candidates_with_ai(candidates_for_run)
    stats["ai_analyzed"] = len(analyses)
    ai_enabled = stats["ai_enabled"]
    if ai_enabled and analyses:
        missing = sum(1 for item in candidates_for_run if item["eid"] not in analyses)
        stats["ai_missing"] = missing
        if missing:
            log_event("WARN", "ai_missing_results", stage="ai_analyze", missing=missing)

    for item in candidates_for_run:
        if stats["pushed"] >= MAX_ITEMS_PER_RUN:
            break

        eid = item["eid"]
        url = item["url"]
        title = item["title"]
        description = item["description"]
        tags = None

        result = analyses.get(eid)
        if ai_enabled and analyses and not result:
            log_event(
                "INFO",
                "candidate_skipped",
                stage="ai_decision",
                item_id=eid,
                url=url,
                action="drop",
                reason="missing_ai_result",
            )
            continue
        if result:
            keep = bool(result.get("keep", False))
            score = float(result.get("score", 0.0))
            reason = str(result.get("reason", ""))
            action = "keep" if keep and score >= AI_MIN_SCORE else "drop"
            log_event(
                "INFO",
                "ai_item_decision",
                stage="ai_decision",
                item_id=eid,
                url=url,
                action=action,
                keep=keep,
                score=score,
                threshold=AI_MIN_SCORE,
                reason=reason,
            )
            ai[eid] = {
                "keep": keep,
                "score": score,
                "reason": reason,
                "ts": now,
                "model": ANTHROPIC_MODEL,
            }
            if not keep:
                stats["ai_dropped_keep_false"] += 1
                continue
            if score < AI_MIN_SCORE:
                stats["ai_dropped_score"] += 1
                continue
            stats["ai_kept"] += 1
            brief = str(result.get("brief", "")).strip()
            if brief:
                description = brief[:600]
            if result.get("tags"):
                tags = result["tags"]

        stats["push_attempted"] += 1
        push_start = time.perf_counter()
        try:
            cubox_save_url(
                url=url,
                title=title,
                description=description,
                tags=tags,
                folder=CUBOX_FOLDER,
            )
            sent[eid] = {"url": url, "ts": now}
            stats["pushed"] += 1
            log_event(
                "INFO",
                "push_success",
                stage="push",
                item_id=eid,
                url=url,
                duration_ms=int((time.perf_counter() - push_start) * 1000),
            )
            time.sleep(0.3)
        except Exception as exc:  # noqa: BLE001
            stats["push_failed"] += 1
            log_event(
                "ERROR",
                "push_failed",
                stage="push",
                item_id=eid,
                url=url,
                duration_ms=int((time.perf_counter() - push_start) * 1000),
                error=str(exc),
            )

    state["sent"] = sent
    state["ai"] = ai
    save_state(state)
    stats["state_size"] = len(sent)
    write_step_summary(stats)
    log_event("INFO", "run_summary", stage="summary", **stats)
    print(f"Done. Pushed {stats['pushed']} items. State size={len(sent)}")


if __name__ == "__main__":
    main()
