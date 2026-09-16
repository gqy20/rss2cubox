"""enrich 结果的 durability 修复测试。

覆盖三个真实事故：
1. 去重基线把"只有原文没有分析结果"的行也算成已处理 → 中断后永久跳过
   （实测三次中断留下 1501 篇再也不会被 enrich）
2. enrich 结果全程只在内存 → 中断丢失整轮几小时的分析
3. 全文回补是"全有或全无" → 抓到一篇就不回补其余缺失的
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

from rss2cubox import enrich_agent, sync_pipeline
from rss2cubox.db_client import get_all_article_ids, save_articles

_DB = os.getenv("LOCAL_DB_URL", "").strip()


def _reachable(url: str) -> bool:
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=5):
            return True
    except Exception:  # noqa: BLE001
        return False


needs_db = pytest.mark.skipif(
    not _reachable(_DB),
    reason="LOCAL_DB_URL 不可用，跳过 DB 测试（先执行 make db）",
)

PREFIX = "pytest_durability_"


def _article(eid: str, *, enriched: bool) -> dict:
    base = dict(
        id=PREFIX + eid,
        source_type="gqy",
        source_feed_id="f",
        source_feed_name="F",
        source_article_id=PREFIX + eid,
        title="T" * 24,
        url=f"https://example.test/{PREFIX}{eid}",
        pic_url="",
        description="d",
        publish_time="2026-09-16T00:00:00+00:00",
        tags=[],
        importance_score=3,
        reason="",
        actionable="",
        hidden_signal="",
        full_text="正文" * 100,
        full_text_source="trafilatura",
    )
    if enriched:
        base.update(reason="这是 enrich 产出的理由", actionable="跟进", hidden_signal="弱信号")
    return base


@pytest.fixture
def db():
    if not _reachable(_DB):
        pytest.skip("LOCAL_DB_URL 不可用")

    def _wipe() -> None:
        with psycopg.connect(_DB) as conn:
            conn.cursor().execute("DELETE FROM articles WHERE id LIKE %s", (PREFIX + "%",))
            conn.commit()

    _wipe()
    yield _DB
    _wipe()


@needs_db
class TestDedupBaselineOnlyCountsEnriched:
    """事故 1：中断后只有原文的行不该永久占着去重位。"""

    def test_enriched_only_excludes_raw_rows(self, db) -> None:
        save_articles([_article("a", enriched=True), _article("b", enriched=False)], db_url=db)

        everything = get_all_article_ids(db, enriched_only=False)
        enriched = get_all_article_ids(db, enriched_only=True)

        assert {PREFIX + "a", PREFIX + "b"} <= everything
        assert PREFIX + "a" in enriched
        assert PREFIX + "b" not in enriched, "只有原文、没有分析结果的行不该算已处理"

    def test_any_of_three_markers_counts_as_enriched(self, db) -> None:
        """对齐 has_signal_analysis：reason / actionable / hidden_signal 任一非空即算。"""
        rows = [_article("m1", enriched=False), _article("m2", enriched=False), _article("m3", enriched=False)]
        rows[0]["actionable"] = "只有 actionable"
        rows[1]["hidden_signal"] = "只有 hidden_signal"
        save_articles(rows, db_url=db)

        enriched = get_all_article_ids(db, enriched_only=True)
        assert {PREFIX + "m1", PREFIX + "m2"} <= enriched
        assert PREFIX + "m3" not in enriched

    def test_interrupted_run_becomes_reprocessable(self, db) -> None:
        """端到端语义：phase1 存了 1500 篇但只 enrich 了 500 篇时，
        去重基线只应含那 500 篇，剩下 1000 篇下轮要能重新处理。"""
        rows = [_article(f"r{i}", enriched=(i < 500)) for i in range(1000)]
        save_articles(rows, db_url=db)

        enriched = get_all_article_ids(db, enriched_only=True)
        mine = {i for i in enriched if i.startswith(PREFIX)}
        assert len(mine) == 500
        assert len(get_all_article_ids(db, enriched_only=False) & {PREFIX + f"r{i}" for i in range(1000)}) == 1000


@needs_db
class TestLoadLocalStateRespectsEnrichFlag:
    def test_enrich_enabled_uses_enriched_only(self, db, monkeypatch: pytest.MonkeyPatch) -> None:
        save_articles([_article("e1", enriched=True), _article("e2", enriched=False)], db_url=db)
        monkeypatch.setenv("ENRICH_AGENT_ENABLED", "true")
        processed, _ = sync_pipeline.load_local_state(db)
        assert PREFIX + "e1" in processed
        assert PREFIX + "e2" not in processed

    @pytest.mark.parametrize("value", ["false", "0", "no", "False", "NO"])
    def test_enrich_disabled_keeps_old_semantics(self, db, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        """enrich 关掉时沿用旧语义，否则每轮都会重复处理同一批文章。"""
        save_articles([_article("d1", enriched=False)], db_url=db)
        monkeypatch.setenv("ENRICH_AGENT_ENABLED", value)
        processed, _ = sync_pipeline.load_local_state(db)
        assert PREFIX + "d1" in processed


class TestIncrementalFlushCallback:
    """事故 2：enrich 结果必须能边跑边落库。"""

    @staticmethod
    def _items(n: int) -> list[tuple[dict, dict]]:
        return [({"eid": f"e{i}", "url": f"https://x.test/{i}", "title": f"标题{i}"},
                 {"eid": f"e{i}"}) for i in range(n)]

    def test_callback_fires_once_per_successful_item(self) -> None:
        import anyio

        seen: list[tuple[str, dict]] = []

        async def fake_enrich_one(item, original, log_event=None, *, pre_fetched_text=None):  # noqa: ANN001
            return {"reason": f"分析结果 {item['eid']}", "importance_score": 4}, "ok"

        analyses: dict = {}
        with patch.object(enrich_agent, "_enrich_one", side_effect=fake_enrich_one):
            anyio.run(
                lambda: enrich_agent._enrich_all(
                    self._items(5), analyses, None, on_item_done=lambda item, a: seen.append((item["eid"], a))
                )
            )

        assert sorted(eid for eid, _ in seen) == ["e0", "e1", "e2", "e3", "e4"]
        assert all(a.get("reason") for _, a in seen)

    def test_callback_receives_item_so_runner_can_build_record(self) -> None:
        """runner 侧要用 item + analysis 调 build_processed_article，两个都得给。"""
        import anyio

        captured: list[dict] = []

        async def fake_enrich_one(item, original, log_event=None, *, pre_fetched_text=None):  # noqa: ANN001
            return {"reason": "r", "actionable": "a", "hidden_signal": "h"}, "ok"

        with patch.object(enrich_agent, "_enrich_one", side_effect=fake_enrich_one):
            anyio.run(
                lambda: enrich_agent._enrich_all(
                    self._items(1), {}, None, on_item_done=lambda item, a: captured.append(item)
                )
            )

        assert captured and captured[0]["eid"] == "e0"
        assert captured[0]["url"] == "https://x.test/0"

    def test_callback_not_fired_for_failed_items(self) -> None:
        import anyio

        seen: list[str] = []

        async def fake_enrich_one(item, original, log_event=None, *, pre_fetched_text=None):  # noqa: ANN001
            if item["eid"] == "e1":
                return None, "timeout"
            return {"reason": "ok"}, "ok"

        with patch.object(enrich_agent, "_enrich_one", side_effect=fake_enrich_one):
            anyio.run(
                lambda: enrich_agent._enrich_all(
                    self._items(3), {}, None, on_item_done=lambda item, a: seen.append(item["eid"])
                )
            )

        assert seen == ["e0", "e2"]

    def test_callback_exception_does_not_break_enrich(self) -> None:
        """落库失败不该让分析结果丢失 —— 回调异常必须被吞掉并计数。"""
        import anyio

        def boom(item, analysis):  # noqa: ANN001
            raise RuntimeError("db down")

        async def fake_enrich_one(item, original, log_event=None, *, pre_fetched_text=None):  # noqa: ANN001
            return {"reason": "r"}, "ok"

        analyses: dict = {}
        events: list[str] = []
        with patch.object(enrich_agent, "_enrich_one", side_effect=fake_enrich_one):
            stats = anyio.run(
                lambda: enrich_agent._enrich_all(
                    self._items(3), analyses,
                    lambda level, event, **kw: events.append(event),
                    on_item_done=boom,
                )
            )

        assert len(analyses) == 3, "回调抛异常不能影响 enrich 结果"
        assert stats["succeeded"] == 3
        assert stats.get("flush_failed") == 3
        assert "enrich_flush_failed" in events

    def test_no_callback_is_backward_compatible(self) -> None:
        import anyio

        async def fake_enrich_one(item, original, log_event=None, *, pre_fetched_text=None):  # noqa: ANN001
            return {"reason": "r"}, "ok"

        analyses: dict = {}
        with patch.object(enrich_agent, "_enrich_one", side_effect=fake_enrich_one):
            stats = anyio.run(lambda: enrich_agent._enrich_all(self._items(2), analyses, None))
        assert stats["succeeded"] == 2 and len(analyses) == 2
