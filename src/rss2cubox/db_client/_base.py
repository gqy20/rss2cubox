"""Shared utilities for db_client sub-modules."""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import psycopg


def _get_db_url(db_url: str | None = None) -> str:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    return db_url


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bounded_int(value: Any, lower: int, upper: int) -> int | None:
    return value if isinstance(value, int) and lower <= value <= upper else None


def _bounded_int_list(value: Any, lower: int, upper: int, limit: int) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and lower <= item <= upper][:limit]


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _parse_json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _parse_publish_time(value: Any) -> datetime | None:
    """Parse publish_time to timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None
