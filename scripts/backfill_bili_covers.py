#!/usr/bin/env python3
"""回填 Bilibili 封面 URL。

对 run_events 表中 cover_url 为空且 URL 含 bilibili 的条目，
通过 wbi 签名调用 Bilibili API 拿真实封面 CDN URL 并写回 DB。

用法：
    uv run scripts/backfill_bili_covers.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from functools import lru_cache
from pathlib import Path

import psycopg
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

NEON_DATABASE_URL = os.environ.get("NEON_DATABASE_URL", "").strip()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
}

BV_RE = re.compile(r"BV[A-Za-z0-9]{8,}", re.IGNORECASE)

# wbi 签名字符重排序表（Bilibili 官方固定值）
_WBI_OE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def _get_mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in _WBI_OE if i < len(raw))[:32]


@lru_cache(maxsize=1)
def _get_wbi_keys() -> tuple[str, str]:
    """从 Bilibili nav 接口获取当天 wbi 密钥（缓存一次）。"""
    r = requests.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers=HEADERS,
        timeout=10,
    )
    data = r.json().get("data", {})
    wbi = data.get("wbi_img", {})
    img_url = wbi.get("img_url", "")
    sub_url = wbi.get("sub_url", "")
    # 取文件名（去路径去扩展名）作为 key
    img_key = re.search(r"/([^/]+)\.\w+$", img_url)
    sub_key = re.search(r"/([^/]+)\.\w+$", sub_url)
    return (img_key.group(1) if img_key else ""), (sub_key.group(1) if sub_key else "")


def _wbi_sign_params(params: dict) -> dict:
    """对参数字典做 wbi 签名，返回带 w_rid 和 wts 的新 dict。"""
    img_key, sub_key = _get_wbi_keys()
    mixin = _get_mixin_key(img_key, sub_key)
    wts = int(time.time())
    signed = dict(sorted({**params, "wts": wts}.items()))
    # wbi 签名：值中去掉特殊字符后做原始拼接（不 URL 编码）
    _SPECIAL = set("!'()*")
    raw_query = "&".join(
        f"{k}=" + "".join(c for c in str(v) if c not in _SPECIAL)
        for k, v in signed.items()
    )
    w_rid = hashlib.md5(f"{raw_query}{mixin}".encode()).hexdigest()
    signed["w_rid"] = w_rid
    return signed


def fetch_cover(bvid: str) -> str:
    """用 wbi 签名调用 Bilibili API 拿封面，失败返回空字符串。"""
    try:
        params = _wbi_sign_params({"bvid": bvid})
        url = "https://api.bilibili.com/x/web-interface/view?" + urllib.parse.urlencode(params)
        r = requests.get(url, headers=HEADERS, timeout=8)
        d = r.json()
        if d.get("code") == 0:
            pic = (d.get("data") or {}).get("pic", "")
            return str(pic).replace("http://", "https://") if pic else ""
        print(f"  [api] {bvid} code={d.get('code')} msg={d.get('message')}", flush=True)
    except Exception as e:
        print(f"  [warn] {bvid}: {e}", flush=True)
    return ""


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    if not NEON_DATABASE_URL:
        print("ERROR: NEON_DATABASE_URL 未设置", flush=True)
        sys.exit(1)

    with psycopg.connect(NEON_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT event_key, data
                FROM run_events
                WHERE data->>'url' ~* 'bilibili\\.com/video/'
                  AND (
                    data->>'cover_url' IS NULL
                    OR data->>'cover_url' = ''
                  )
                ORDER BY event_time DESC
            """)
            all_rows = cur.fetchall()

        rows = all_rows[:limit] if limit else all_rows
        total = len(rows)
        print(f"找到 {len(all_rows)} 条空封面记录，本次处理 {total} 条", flush=True)
        if total == 0:
            return

        updated = 0
        skipped = 0
        for i, (event_key, data) in enumerate(rows, 1):
            url = (data or {}).get("url", "")
            m = BV_RE.search(url)
            if not m:
                skipped += 1
                continue
            bvid = m.group(0).upper()
            cover = fetch_cover(bvid)
            status = f"✓ {cover[:70]}" if cover else "✗ 无封面"
            print(f"[{i}/{total}] {bvid} → {status}", flush=True)

            if cover and not dry_run:
                data["cover_url"] = cover
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE run_events SET data = %s WHERE event_key = %s",
                        (json.dumps(data, ensure_ascii=False), event_key),
                    )
                conn.commit()
                updated += 1

            # 每次请求间隔 1 秒，避免被 Bilibili 封 IP
            time.sleep(1.0)

        print(f"\n完成：更新 {updated} / {total - skipped}（可更新），无 BVID 跳过 {skipped}", flush=True)
        if dry_run:
            print("（dry-run 模式，未写入 DB）", flush=True)


if __name__ == "__main__":
    main()
