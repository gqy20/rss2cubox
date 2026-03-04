from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {"sent": {}}
    with state_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state_file: Path, state: dict) -> None:
    with state_file.open("w", encoding="utf-8") as f:
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


def passes_filter(entry: dict, include_keywords: list[str], exclude_keywords: list[str]) -> bool:
    blob = text_blob(entry)
    if include_keywords and not any(k.lower() in blob for k in include_keywords):
        return False
    if exclude_keywords and any(k.lower() in blob for k in exclude_keywords):
        return False
    return True


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
