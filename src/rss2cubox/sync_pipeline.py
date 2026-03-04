from __future__ import annotations

import calendar
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[WARN] invalid {name}={raw!r}, fallback to {default}", flush=True)
        return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[WARN] invalid {name}={raw!r}, fallback to {default}", flush=True)
        return default


def load_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {"sent": {}}
    with state_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state_file: Path, state: dict) -> None:
    with state_file.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def save_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
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


def passes_filter(entry: dict, include_keywords: list[str], exclude_keywords: list[str]) -> bool:
    blob = text_blob(entry)
    if include_keywords and not any(k.lower() in blob for k in include_keywords):
        return False
    if exclude_keywords and any(k.lower() in blob for k in exclude_keywords):
        return False
    return True


def parse_entry_timestamp(entry: dict) -> datetime | None:
    for key in ("updated_parsed", "published_parsed"):
        ts = entry.get(key)
        if ts:
            try:
                return datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc)
            except Exception:  # noqa: BLE001
                pass
    for key in ("updated", "published"):
        raw = str(entry.get(key, "")).strip()
        if not raw:
            continue
        parsed = parse_iso_datetime(raw)
        if parsed is None:
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    return None


def parse_iso_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def feed_failure_backoff_seconds(
    failure_count: int,
    base_seconds: int,
    max_seconds: int,
) -> int:
    return min(max_seconds, base_seconds * (2 ** max(0, failure_count - 1)))


def feed_is_circuit_open(feed_failure_state: dict[str, Any], now_utc: datetime) -> tuple[bool, int]:
    until_dt = parse_iso_datetime(str(feed_failure_state.get("cooldown_until", "")))
    if until_dt is None or until_dt <= now_utc:
        return False, 0
    remaining = max(0, int((until_dt - now_utc).total_seconds()))
    return True, remaining


def dedupe_run_candidates(
    candidates: list[dict[str, Any]],
    per_feed_drop_reasons: dict[str, dict[str, int]],
) -> tuple[list[dict[str, Any]], int]:
    run_seen: set[str] = set()
    unique_candidates: list[dict[str, Any]] = []
    run_deduped = 0
    for item in candidates:
        eid = str(item.get("eid", "")).strip()
        if not eid:
            continue
        if eid in run_seen:
            run_deduped += 1
            source_feed = str(item.get("source_feed", "unknown"))
            drop_by_feed = per_feed_drop_reasons.setdefault(source_feed, {})
            drop_by_feed["run_deduped"] = drop_by_feed.get("run_deduped", 0) + 1
            continue
        run_seen.add(eid)
        unique_candidates.append(item)
    return unique_candidates, run_deduped


def reorder_candidates_by_ai_score(
    candidates_for_run: list[dict[str, Any]],
    analyses: dict[str, dict[str, Any]],
    *,
    ai_enabled: bool,
    ai_min_score: float,
) -> list[dict[str, Any]]:
    if not (ai_enabled and analyses):
        return candidates_for_run

    ranked: list[tuple[int, float, int, dict[str, Any]]] = []
    for idx, item in enumerate(candidates_for_run):
        eid = str(item.get("eid", "")).strip()
        result = analyses.get(eid, {})
        keep = bool(result.get("keep", False))
        try:
            score = float(result.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        if keep and score >= ai_min_score:
            priority = 2
        elif keep:
            priority = 1
        else:
            priority = 0
        ranked.append((priority, score, idx, item))

    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return [row[3] for row in ranked]


def process_candidates_for_push(
    *,
    candidates_for_run: list[dict[str, Any]],
    analyses: dict[str, dict[str, Any]],
    stats: dict[str, Any],
    sent: dict[str, Any],
    ai_state: dict[str, Any],
    now_iso: str,
    max_items_per_run: int,
    ai_enabled: bool,
    ai_min_score: float,
    ai_model: str,
    cubox_api_url: str | None,
    cubox_folder: str,
    request_post: Any,
    stage_metrics: Any,
    log_event: Any,
    event_sink: list[dict[str, Any]] | None = None,
    sleep_seconds: float = 0.3,
) -> None:
    def emit_event(event: dict[str, Any]) -> None:
        if event_sink is not None:
            event_sink.append(event)

    for item in candidates_for_run:
        eid = item["eid"]
        url = item["url"]
        title = item["title"]
        description = item["description"]
        tags = None
        source_feed = item.get("source_feed", "unknown")
        event: dict[str, Any] = {
            "id": eid,
            "time": now_iso,
            "source_feed": source_feed,
            "url": url,
            "title": title,
            "score": 0.0,
            "keep": None,
            "status": "pending",
            "drop_reason": "",
            "pushed": False,
            "tags": [],
        }
        if stats["pushed"] >= max_items_per_run:
            event["status"] = "dropped"
            event["drop_reason"] = "max_items_per_run_reached"
            drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
            drop_by_feed["max_items_per_run_reached"] = drop_by_feed.get("max_items_per_run_reached", 0) + 1
            emit_event(event)
            continue
        if eid in sent:
            stats["run_deduped"] += 1
            drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
            drop_by_feed["run_deduped"] = drop_by_feed.get("run_deduped", 0) + 1
            event["status"] = "dropped"
            event["drop_reason"] = "run_deduped"
            emit_event(event)
            continue

        result = analyses.get(eid)
        if ai_enabled and analyses and not result:
            drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
            drop_by_feed["missing_ai_result"] = drop_by_feed.get("missing_ai_result", 0) + 1
            log_event(
                "INFO",
                "candidate_skipped",
                stage="ai_decision",
                item_id=eid,
                url=url,
                action="drop",
                reason="missing_ai_result",
            )
            event["status"] = "dropped"
            event["drop_reason"] = "missing_ai_result"
            emit_event(event)
            continue
        if result:
            keep = bool(result.get("keep", False))
            score = float(result.get("score", 0.0))
            reason = str(result.get("reason", ""))
            event["keep"] = keep
            event["score"] = score
            event["tags"] = result.get("tags", []) if isinstance(result.get("tags", []), list) else []
            action = "keep" if keep and score >= ai_min_score else "drop"
            log_event(
                "INFO",
                "ai_item_decision",
                stage="ai_decision",
                item_id=eid,
                url=url,
                action=action,
                keep=keep,
                score=score,
                threshold=ai_min_score,
                reason=reason,
            )
            ai_state[eid] = {
                "keep": keep,
                "score": score,
                "reason": reason,
                "ts": now_iso,
                "model": ai_model,
            }
            if not keep:
                stats["ai_dropped_keep_false"] += 1
                drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
                drop_by_feed["ai_keep_false"] = drop_by_feed.get("ai_keep_false", 0) + 1
                event["status"] = "dropped"
                event["drop_reason"] = "ai_keep_false"
                emit_event(event)
                continue
            if score < ai_min_score:
                stats["ai_dropped_score"] += 1
                drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
                drop_by_feed["ai_score_below_threshold"] = drop_by_feed.get("ai_score_below_threshold", 0) + 1
                event["status"] = "dropped"
                event["drop_reason"] = "ai_score_below_threshold"
                emit_event(event)
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
                api_url=cubox_api_url,
                request_post=request_post,
                url=url,
                title=title,
                description=description,
                tags=tags,
                folder=cubox_folder,
            )
            sent[eid] = {"url": url, "ts": now_iso}
            stats["pushed"] += 1
            stats["per_feed_push_counts"][source_feed] = stats["per_feed_push_counts"].get(source_feed, 0) + 1
            event["status"] = "pushed"
            event["pushed"] = True
            push_duration_ms = int((time.perf_counter() - push_start) * 1000)
            stage_metrics.observe("push", push_duration_ms)
            log_event(
                "INFO",
                "push_success",
                stage="push",
                item_id=eid,
                url=url,
                duration_ms=push_duration_ms,
            )
            time.sleep(sleep_seconds)
        except Exception as exc:  # noqa: BLE001
            stats["push_failed"] += 1
            push_duration_ms = int((time.perf_counter() - push_start) * 1000)
            stage_metrics.observe("push", push_duration_ms)
            drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
            drop_by_feed["push_failed"] = drop_by_feed.get("push_failed", 0) + 1
            log_event(
                "ERROR",
                "push_failed",
                stage="push",
                item_id=eid,
                url=url,
                duration_ms=push_duration_ms,
                error=str(exc),
            )
            event["status"] = "failed"
            event["drop_reason"] = "push_failed"
        emit_event(event)


def cubox_save_url(
    *,
    api_url: str | None,
    request_post: Any,
    url: str,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
    folder: str = "",
) -> str:
    if not api_url:
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

    response = request_post(api_url, json=payload, timeout=30)
    response.raise_for_status()
    return response.text
