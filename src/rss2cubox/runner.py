#!/usr/bin/env python3
import hashlib
import json
import os
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
MAX_ITEMS_PER_RUN = int(os.getenv("MAX_ITEMS_PER_RUN", "30"))


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


def main() -> None:
    feeds = load_lines(FEEDS_FILE)
    state = load_state()
    sent = state.get("sent", {})

    pushed = 0
    now = datetime.now(timezone.utc).isoformat()

    for feed_url in feeds:
        parsed = feedparser.parse(feed_url)
        if getattr(parsed, "bozo", False):
            print(f"[WARN] skip invalid feed: {feed_url}")
            continue

        for entry in parsed.entries:
            if pushed >= MAX_ITEMS_PER_RUN:
                break

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

            try:
                cubox_save_url(
                    url=url,
                    title=title,
                    description=description,
                    tags=None,
                    folder=CUBOX_FOLDER,
                )
                sent[eid] = {"url": url, "ts": now}
                pushed += 1
                time.sleep(0.3)
            except Exception as exc:  # noqa: BLE001
                print(f"[ERROR] push failed: {url} -> {exc}")

        if pushed >= MAX_ITEMS_PER_RUN:
            break

    state["sent"] = sent
    save_state(state)
    print(f"Done. Pushed {pushed} items. State size={len(sent)}")


if __name__ == "__main__":
    main()
