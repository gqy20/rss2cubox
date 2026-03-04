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
WEB_UPDATES_FILE = Path(os.getenv('WEB_UPDATES_FILE', 'web/public/data/updates.json'))
WEB_METRICS_FILE = Path(os.getenv('WEB_METRICS_FILE', 'web/public/data/metrics.json'))
WEB_UPDATES_LIMIT = max(1, sync_pipeline.env_int('WEB_UPDATES_LIMIT', 2000))


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
                'title': _guess_title_from_url(url),
                'score': score,
                'tags': ai_result.get('tags', []) if isinstance(ai_result, dict) else [],
            }
        )

    items.sort(key=lambda x: _parse_ts(str(x.get('time', ''))), reverse=True)
    return items[: max(1, limit)]


def build_metrics(updates: list[dict[str, Any]]) -> dict[str, Any]:
    source_counter = Counter()
    for row in updates:
        source_counter[str(row.get('source', 'unknown'))] += 1
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'updates_total': len(updates),
        'sources_total': len(source_counter),
        'top_sources': [
            {'source': source, 'count': count}
            for source, count in source_counter.most_common(20)
        ],
    }


def export_web_data(
    state_file: Path = STATE_FILE,
    updates_file: Path = WEB_UPDATES_FILE,
    metrics_file: Path = WEB_METRICS_FILE,
    limit: int = WEB_UPDATES_LIMIT,
) -> tuple[int, int]:
    state = sync_pipeline.load_state(state_file)
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
