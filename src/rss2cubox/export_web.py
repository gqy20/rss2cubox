from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rss2cubox import sync_pipeline

STATE_FILE = Path(os.getenv('STATE_FILE', 'state.json'))
RUN_EVENTS_FILE = Path(os.getenv('RUN_EVENTS_FILE', 'run_events.jsonl'))
WEB_HISTORY_FILE = Path(os.getenv('WEB_HISTORY_FILE', 'web/public/data/updates_history.jsonl'))
WEB_UPDATES_FILE = Path(os.getenv('WEB_UPDATES_FILE', 'web/public/data/updates.json'))
WEB_METRICS_FILE = Path(os.getenv('WEB_METRICS_FILE', 'web/public/data/metrics.json'))
WEB_UPDATES_LIMIT = max(1, sync_pipeline.env_int('WEB_UPDATES_LIMIT', 2000))
WEB_HISTORY_LIMIT = max(1, sync_pipeline.env_int('WEB_HISTORY_LIMIT', 20000))


def _parse_ts(raw: str) -> datetime:
    dt = sync_pipeline.parse_iso_datetime(raw)
    if dt is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return dt


def _guess_title_from_url(url: str) -> str:
    path = urlparse(url).path.strip('/')
    if not path:
        return urlparse(url).netloc
    tail = path.split('/')[-1].replace('-', ' ').replace('_', ' ').strip()
    return tail or urlparse(url).netloc


def _source_from_feed_value(raw: str) -> str:
    text = str(raw or '').strip()
    if not text:
        return 'unknown'
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        return parsed.netloc
    return text


def _normalize_event_row(row: dict[str, Any]) -> dict[str, Any] | None:
    url = str(row.get('url', '')).strip()
    if not url:
        return None
    item_id = str(row.get('id', '')).strip()
    if not item_id:
        item_id = sync_pipeline.stable_id({'link': url, 'title': str(row.get('title', ''))})
    source_feed = str(row.get('source_feed', '')).strip()
    source_label = str(row.get('source_label', '')).strip()
    cover_url = str(row.get('cover_url', '')).strip()
    source = source_label or _source_from_feed_value(source_feed) or urlparse(url).netloc or 'unknown'
    title = str(row.get('title', '')).strip() or _guess_title_from_url(url)
    status = str(row.get('status', 'unknown')).strip() or 'unknown'
    drop_reason = str(row.get('drop_reason', '')).strip()
    try:
        score = float(row.get('score', 0.0))
    except (TypeError, ValueError):
        score = 0.0
    tags = row.get('tags', [])
    if not isinstance(tags, list):
        tags = []
    return {
        'id': item_id,
        'time': str(row.get('time', '')).strip(),
        'source': source,
        'source_feed': source_feed,
        'source_label': source_label,
        'cover_url': cover_url,
        'url': url,
        'title': title,
        'score': score,
        'keep': row.get('keep'),
        'status': status,
        'drop_reason': drop_reason,
        'pushed': bool(row.get('pushed', False)),
        'enriched': bool(row.get('enriched', False)),
        'tags': tags,
        'core_event': str(row.get('core_event', '') or ''),
        'hidden_signal': str(row.get('hidden_signal', '') or ''),
        'actionable': str(row.get('actionable', '') or ''),
        'reason': str(row.get('reason', '') or ''),
        'run_id': str(row.get('run_id', '')).strip(),
        'head_sha': str(row.get('head_sha', '')).strip(),
        'event_name': str(row.get('event_name', '')).strip(),
        'ref_name': str(row.get('ref_name', '')).strip(),
    }


def _event_key(row: dict[str, Any]) -> str:
    key_obj = {
        'run_id': row.get('run_id', ''),
        'id': row.get('id', ''),
        'status': row.get('status', ''),
        'time': row.get('time', ''),
        'url': row.get('url', ''),
    }
    return json.dumps(key_obj, sort_keys=True, ensure_ascii=False)


def merge_history_rows(
    history_rows: list[dict[str, Any]],
    run_rows: list[dict[str, Any]],
    *,
    history_limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in history_rows:
        if not isinstance(raw, dict):
            continue
        normalized = _normalize_event_row(raw)
        if normalized is None:
            continue
        key = _event_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)

    for raw in run_rows:
        if not isinstance(raw, dict):
            continue
        normalized = _normalize_event_row(raw)
        if normalized is None:
            continue
        key = _event_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)

    merged.sort(key=lambda x: _parse_ts(str(x.get('time', ''))), reverse=True)
    return merged[: max(1, history_limit)]


def build_updates_from_history(history_rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rows = [row for row in history_rows if isinstance(row, dict)]
    rows.sort(key=lambda x: _parse_ts(str(x.get('time', ''))), reverse=True)
    return rows[: max(1, limit)]


def build_updates(state: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    sent = state.get('sent', {})
    ai = state.get('ai', {})
    items: list[dict[str, Any]] = []
    for eid, value in sent.items():
        if not isinstance(value, dict):
            continue
        url = str(value.get('url', '')).strip()
        if not url:
            continue
        ts = str(value.get('ts', '')).strip()
        parsed = urlparse(url)
        host = parsed.netloc
        ai_result = ai.get(eid, {}) if isinstance(ai, dict) else {}
        score = 0.0
        if isinstance(ai_result, dict):
            try:
                score = float(ai_result.get('score', 0.0))
            except (TypeError, ValueError):
                score = 0.0
        items.append(
            {
                'id': eid,
                'time': ts,
                'source': host,
                'url': url,
                'title': str(value.get('title', '')).strip() or _guess_title_from_url(url),
                'score': score,
                'core_event': ai_result.get('core_event', '') if isinstance(ai_result, dict) else '',
                'hidden_signal': ai_result.get('hidden_signal', '') if isinstance(ai_result, dict) else '',
                'actionable': ai_result.get('actionable', '') if isinstance(ai_result, dict) else '',
                'reason': ai_result.get('reason', '') if isinstance(ai_result, dict) else '',
                'tags': ai_result.get('tags', []) if isinstance(ai_result, dict) else [],
                'enriched': bool(ai_result.get('enriched', False)) if isinstance(ai_result, dict) else False,
            }
        )

    items.sort(key=lambda x: _parse_ts(str(x.get('time', ''))), reverse=True)
    return items[: max(1, limit)]


def build_metrics(updates: list[dict[str, Any]]) -> dict[str, Any]:
    source_counter = Counter()
    status_counter = Counter()
    drop_counter = Counter()
    for row in updates:
        source_counter[str(row.get('source', 'unknown'))] += 1
        status = str(row.get('status', '')).strip()
        if status:
            status_counter[status] += 1
        drop_reason = str(row.get('drop_reason', '')).strip()
        if drop_reason:
            drop_counter[drop_reason] += 1
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'updates_total': len(updates),
        'pushed_total': status_counter.get('pushed', 0),
        'dropped_total': status_counter.get('dropped', 0),
        'failed_total': status_counter.get('failed', 0),
        'sources_total': len(source_counter),
        'top_sources': [
            {'source': source, 'count': count}
            for source, count in source_counter.most_common(20)
        ],
        'top_drop_reasons': [
            {'reason': reason, 'count': count}
            for reason, count in drop_counter.most_common(20)
        ],
    }


def export_web_data(
    state_file: Path = STATE_FILE,
    run_events_file: Path = RUN_EVENTS_FILE,
    history_file: Path = WEB_HISTORY_FILE,
    updates_file: Path = WEB_UPDATES_FILE,
    metrics_file: Path = WEB_METRICS_FILE,
    limit: int = WEB_UPDATES_LIMIT,
    history_limit: int = WEB_HISTORY_LIMIT,
) -> tuple[int, int]:
    state = sync_pipeline.load_state(state_file)
    history_rows = sync_pipeline.load_jsonl(history_file)
    run_rows = sync_pipeline.load_jsonl(run_events_file)
    merged_history = merge_history_rows(history_rows, run_rows, history_limit=history_limit)

    # 用 state.json 中的 AI 字段回填 history 中缺失的摘要
    ai_state: dict[str, Any] = state.get('ai', {})
    if isinstance(ai_state, dict) and ai_state:
        for row in merged_history:
            eid = row.get('id', '')
            ai = ai_state.get(eid)
            if not isinstance(ai, dict):
                continue
            for field in ('core_event', 'hidden_signal', 'actionable', 'reason', 'tags'):
                if not row.get(field):
                    row[field] = ai.get(field, '' if field != 'tags' else [])
            if not row.get('score'):
                try:
                    row['score'] = float(ai.get('score', 0.0))
                except (TypeError, ValueError):
                    pass
    history_file.parent.mkdir(parents=True, exist_ok=True)
    sync_pipeline.save_jsonl(history_file, merged_history)

    updates = build_updates_from_history(merged_history, limit=limit)
    if not updates:
        updates = build_updates(state, limit=limit)
    metrics = build_metrics(updates)

    updates_file.parent.mkdir(parents=True, exist_ok=True)
    metrics_file.parent.mkdir(parents=True, exist_ok=True)

    with updates_file.open('w', encoding='utf-8') as f:
        json.dump(updates, f, ensure_ascii=False, indent=2)
        f.write('\n')

    with metrics_file.open('w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
        f.write('\n')

    return len(updates), int(metrics.get('sources_total', 0))


def main() -> None:
    count, sources = export_web_data()
    print(f'Exported web data: updates={count}, sources={sources}')


if __name__ == '__main__':
    main()
