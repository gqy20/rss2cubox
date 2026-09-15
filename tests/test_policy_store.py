"""政策存储层测试。

store.py 的风险集中在 SQL 本身（upsert 不覆盖 enrich 字段、consecutive_empty_runs
的累加/清零逻辑），mock 掉 psycopg 验证不了这些，所以这里打真实库。
用 _pytest_policy_ 前缀隔离数据，fixture 负责清理；库不可用时整组跳过。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

from rss2cubox.policy.engine import PolicyItem, ScrapeResult
from rss2cubox.policy import store

# pytest 不会自动加载 .env。这里用 override=False（与项目运行时的 override=True 相反），
# 目的是让外部显式指定的 LOCAL_DB_URL 能指向临时库，方便隔离测试。
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

PREFIX = "_pytest_policy_"


def _db_url() -> str:
    return os.getenv("LOCAL_DB_URL", "").strip()


def _reachable(url: str) -> bool:
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=5):
            return True
    except Exception:  # noqa: BLE001
        return False


_DB = _db_url()
pytestmark = pytest.mark.skipif(
    not _reachable(_DB),
    reason=f"LOCAL_DB_URL 不可用（{(_DB.split('@')[-1] if _DB else '未设置')}），跳过 store 测试。先执行 make db",
)


@pytest.fixture(autouse=True)
def _clean(tmp_path):
    """每组测试前后都清掉本文件写入的行。"""
    store.ensure_policy_schema(_DB)

    def _wipe() -> None:
        with psycopg.connect(_DB) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM policy_documents WHERE site_key LIKE %s", (PREFIX + "%",))
            cur.execute("DELETE FROM policy_source_state WHERE site_key LIKE %s", (PREFIX + "%",))
            conn.commit()

    _wipe()
    yield
    _wipe()


def _item(key: str, n: int, title: str | None = None) -> PolicyItem:
    return PolicyItem(
        site_key=f"{PREFIX}{key}",
        title=title or f"{PREFIX}测试政策文件标题 {n}",
        url=f"https://test.gov.cn/{key}/{n}.html",
        published_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
        raw_date="2026-09-15",
    )


def _result(key: str, items: list[PolicyItem] | None = None, status: str = "ok", error: str = "") -> ScrapeResult:
    return ScrapeResult(
        site_key=f"{PREFIX}{key}",
        site_name=f"{PREFIX}测试站",
        items=items if items is not None else [],
        status=status,
        error=error,
        duration_ms=42,
        raw_item_count=len(items or []),
    )


class TestSchema:
    def test_ensure_schema_is_idempotent(self) -> None:
        assert store.ensure_policy_schema(_DB) is True
        assert store.ensure_policy_schema(_DB) is True

    def test_returns_false_without_db_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOCAL_DB_URL", raising=False)
        assert store.ensure_policy_schema("") is False


class TestSavePolicyDocuments:
    def test_insert_then_update_is_idempotent(self) -> None:
        items = [_item("a", 1), _item("a", 2)]
        first = store.save_policy_documents(items, site_name="S", level="city", region="苏州", db_url=_DB)
        assert first == {"inserted": 2, "updated": 0, "skipped": 0}

        second = store.save_policy_documents(items, site_name="S", level="city", region="苏州", db_url=_DB)
        assert second == {"inserted": 0, "updated": 2, "skipped": 0}

        rows = store.get_policy_documents(site_key=f"{PREFIX}a", limit=10, db_url=_DB)
        assert len(rows) == 2

    def test_seen_count_increments_on_repeat(self) -> None:
        items = [_item("b", 1)]
        store.save_policy_documents(items, db_url=_DB)
        store.save_policy_documents(items, db_url=_DB)
        store.save_policy_documents(items, db_url=_DB)
        rows = store.get_policy_documents(site_key=f"{PREFIX}b", limit=5, db_url=_DB)
        assert rows[0]["seen_count"] == 3

    def test_update_does_not_clobber_enrich_fields(self) -> None:
        """复见时只更新 last_seen/seen_count/标题，绝不能覆盖 enrich 阶段回填的字段。"""
        items = [_item("c", 1)]
        store.save_policy_documents(items, db_url=_DB)

        with psycopg.connect(_DB) as conn:
            cur = conn.cursor()
            cur.execute(
                """UPDATE policy_documents SET jurisdiction='中国', instrument_type='地方性法规',
                       stage='已生效', ai_relevance=5, summary='人工回填', source_quote='原文引句',
                       enriched_at=NOW()
                   WHERE site_key=%s""",
                (f"{PREFIX}c",),
            )
            conn.commit()

        store.save_policy_documents([_item("c", 1, title="标题被站点更新了")], db_url=_DB)

        rows = store.get_policy_documents(site_key=f"{PREFIX}c", limit=5, db_url=_DB)
        assert len(rows) == 1
        row = rows[0]
        assert row["title"] == "标题被站点更新了"      # 标题应跟随更新
        assert row["jurisdiction"] == "中国"            # enrich 字段必须保住
        assert row["instrument_type"] == "地方性法规"
        assert row["stage"] == "已生效"
        assert row["ai_relevance"] == 5
        assert row["summary"] == "人工回填"
        assert row["source_quote"] == "原文引句"
        assert row["enriched_at"] is not None

    def test_same_url_from_different_sites_collides_on_url_unique(self) -> None:
        """url 上有 UNIQUE 约束；但 id 是 url 的哈希，所以同 URL 天然是同一行。"""
        item = PolicyItem(site_key=f"{PREFIX}d1", title="跨站重复的政策文件标题", url="https://dup.gov.cn/x.html")
        dup = PolicyItem(site_key=f"{PREFIX}d2", title="跨站重复的政策文件标题", url="https://dup.gov.cn/x.html")
        assert item.doc_id == dup.doc_id
        store.save_policy_documents([item], db_url=_DB)
        store.save_policy_documents([dup], db_url=_DB)
        with psycopg.connect(_DB) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM policy_documents WHERE url=%s", ("https://dup.gov.cn/x.html",))
            assert cur.fetchone()[0] == 1

    def test_empty_input_is_noop(self) -> None:
        assert store.save_policy_documents([], db_url=_DB) == {"inserted": 0, "updated": 0, "skipped": 0}

    def test_without_db_url_reports_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOCAL_DB_URL", raising=False)
        out = store.save_policy_documents([_item("e", 1)], db_url="")
        assert out["skipped"] == 1 and out["inserted"] == 0


class TestSourceStateAndStaleness:
    """失效监测：连续空跑必须累加，成功必须清零。"""

    def test_success_records_zero_streak(self) -> None:
        store.record_source_state(_result("s1", [_item("s1", 1)]), level="city", region="苏州", db_url=_DB)
        states = {r["site_key"]: r for r in store.get_source_states(_DB)}
        row = states[f"{PREFIX}s1"]
        assert row["last_status"] == "ok"
        assert row["consecutive_empty_runs"] == 0
        assert row["last_item_count"] == 1

    def test_empty_runs_accumulate(self) -> None:
        for i in range(3):
            store.record_source_state(
                _result("s2", [], status="parse_error", error="selector_matched_nothing"), db_url=_DB
            )
        row = next(r for r in store.get_source_states(_DB) if r["site_key"] == f"{PREFIX}s2")
        assert row["consecutive_empty_runs"] == 3
        assert row["last_success_at"] is None

    def test_success_resets_streak(self) -> None:
        store.record_source_state(_result("s3", [], status="empty"), db_url=_DB)
        store.record_source_state(_result("s3", [], status="empty"), db_url=_DB)
        store.record_source_state(_result("s3", [_item("s3", 1)]), db_url=_DB)
        store.record_source_state(_result("s3", [], status="empty"), db_url=_DB)
        row = next(r for r in store.get_source_states(_DB) if r["site_key"] == f"{PREFIX}s3")
        # 成功清零后只失败了 1 次
        assert row["consecutive_empty_runs"] == 1
        assert row["last_success_at"] is not None

    def test_total_runs_and_items_accumulate(self) -> None:
        store.record_source_state(_result("s4", [_item("s4", 1), _item("s4", 2)]), db_url=_DB)
        store.record_source_state(_result("s4", [_item("s4", 3)]), db_url=_DB)
        with psycopg.connect(_DB) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT total_runs, total_items FROM policy_source_state WHERE site_key=%s",
                (f"{PREFIX}s4",),
            )
            runs, items = cur.fetchone()
        assert (runs, items) == (2, 3)

    def test_get_stale_sources_respects_threshold(self) -> None:
        for _ in range(3):
            store.record_source_state(_result("s5", [], status="empty"), db_url=_DB)
        store.record_source_state(_result("s6", [_item("s6", 1)]), db_url=_DB)

        stale3 = {r["site_key"] for r in store.get_stale_sources(min_empty_runs=3, db_url=_DB)}
        assert f"{PREFIX}s5" in stale3
        assert f"{PREFIX}s6" not in stale3

        stale9 = {r["site_key"] for r in store.get_stale_sources(min_empty_runs=9, db_url=_DB)}
        assert f"{PREFIX}s5" not in stale9


class TestQueryFilters:
    def _seed(self) -> None:
        store.save_policy_documents(
            [_item("q1", 1), _item("q1", 2)], site_name="N", level="national", region="全国", db_url=_DB
        )
        store.save_policy_documents(
            [_item("q2", 1)], site_name="C", level="city", region="苏州", db_url=_DB
        )

    def test_filter_by_level(self) -> None:
        self._seed()
        rows = store.get_policy_documents(level="national", limit=50, db_url=_DB)
        assert rows and all(r["level"] == "national" for r in rows)

    def test_filter_by_region(self) -> None:
        self._seed()
        rows = store.get_policy_documents(region="苏州", limit=50, db_url=_DB)
        assert rows and all(r["region"] == "苏州" for r in rows)

    def test_filter_by_site_key(self) -> None:
        self._seed()
        rows = store.get_policy_documents(site_key=f"{PREFIX}q2", limit=50, db_url=_DB)
        assert len(rows) == 1

    def test_unenriched_only(self) -> None:
        self._seed()
        with psycopg.connect(_DB) as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE policy_documents SET enriched_at=NOW(), summary='x' WHERE site_key=%s",
                (f"{PREFIX}q1",),
            )
            conn.commit()
        # 表里可能共存真实跑批数据，所以只验证过滤语义，不断言全局行数
        rows = store.get_policy_documents(unenriched_only=True, limit=500, db_url=_DB)
        assert all(r["enriched_at"] is None for r in rows)
        keys = {r["site_key"] for r in rows}
        assert f"{PREFIX}q2" in keys       # 未 enrich 的应被返回
        assert f"{PREFIX}q1" not in keys   # 已 enrich 的应被排除

    def test_limit_is_respected(self) -> None:
        self._seed()
        assert len(store.get_policy_documents(limit=2, db_url=_DB)) == 2

    def test_ordered_by_published_desc(self) -> None:
        store.save_policy_documents(
            [
                PolicyItem(site_key=f"{PREFIX}o", title="旧的政策文件标题", url="https://t.gov.cn/old",
                           published_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                PolicyItem(site_key=f"{PREFIX}o", title="新的政策文件标题", url="https://t.gov.cn/new",
                           published_at=datetime(2026, 9, 15, tzinfo=timezone.utc)),
            ],
            db_url=_DB,
        )
        rows = store.get_policy_documents(site_key=f"{PREFIX}o", limit=10, db_url=_DB)
        assert [r["title"] for r in rows] == ["新的政策文件标题", "旧的政策文件标题"]

    def test_without_db_url_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOCAL_DB_URL", raising=False)
        assert store.get_policy_documents(db_url="") == []
        assert store.get_source_states("") == []
        assert store.get_stale_sources(db_url="") == []


class TestTriageStore:
    """预筛层：把昂贵的逐篇 deep enrich 限制在真正相关的文档上。"""

    def _seed(self, n: int = 4) -> list[str]:
        items = [_item("t", i) for i in range(n)]
        store.save_policy_documents(items, site_name="T", level="national", region="全国", db_url=_DB)
        return [it.doc_id for it in items]

    def test_untriaged_returns_only_untriaged(self) -> None:
        ids = self._seed(3)
        docs = store.get_untriaged_documents(limit=50, db_url=_DB)
        got = {d["id"] for d in docs}
        assert set(ids) <= got
        # 只带轻量字段，不含正文
        assert "full_text" not in docs[0]

    def test_save_triage_marks_documents(self) -> None:
        ids = self._seed(2)
        assert set(ids) <= {d["id"] for d in store.get_untriaged_documents(limit=500, db_url=_DB)}

        saved = store.save_triage_results(
            [
                {"id": ids[0], "is_policy": True, "ai_relevance": 5},
                {"id": ids[1], "is_policy": False, "ai_relevance": 1},
            ],
            db_url=_DB,
        )
        assert saved == 2
        dist = store.count_policy_triage(db_url=_DB)
        assert dist.get("5", 0) >= 1 and dist.get("1", 0) >= 1
        # 已预筛的不再出现在待预筛列表里
        still = {d["id"] for d in store.get_untriaged_documents(limit=500, db_url=_DB)}
        assert not (set(ids) & still)

    def test_enrich_selection_respects_triage_threshold(self) -> None:
        """核心行为：阈值过滤必须生效，否则停水通知会和法规文件同等消耗预算。

        表里可能共存真实跑批数据，所以只验证本组三条的相对关系，不断言全局集合。
        """
        ids = self._seed(3)
        store.save_triage_results(
            [
                {"id": ids[0], "is_policy": True, "ai_relevance": 5},
                {"id": ids[1], "is_policy": True, "ai_relevance": 3},
                {"id": ids[2], "is_policy": False, "ai_relevance": 1},
            ],
            db_url=_DB,
        )
        high = {d["id"] for d in store.get_documents_for_enrichment(limit=500, min_triage_relevance=4, db_url=_DB)}
        assert ids[0] in high
        assert ids[1] not in high
        assert ids[2] not in high

        mid = {d["id"] for d in store.get_documents_for_enrichment(limit=500, min_triage_relevance=3, db_url=_DB)}
        assert {ids[0], ids[1]} <= mid
        assert ids[2] not in mid

    def test_no_threshold_means_no_triage_filter(self) -> None:
        """min_triage_relevance=None 时不过滤，保持向后兼容。"""
        ids = self._seed(2)
        docs = store.get_documents_for_enrichment(limit=500, db_url=_DB)
        assert set(ids) <= {d["id"] for d in docs}

    def test_out_of_range_relevance_stored_as_null(self) -> None:
        ids = self._seed(1)
        store.save_triage_results([{"id": ids[0], "is_policy": True, "ai_relevance": 99}], db_url=_DB)
        with psycopg.connect(_DB) as conn:
            cur = conn.cursor()
            cur.execute("SELECT triage_relevance, triaged_at IS NOT NULL FROM policy_documents WHERE id=%s", (ids[0],))
            relevance, triaged = cur.fetchone()
        assert relevance is None
        assert triaged is True   # 仍然标记为已预筛，避免反复重试

    def test_unknown_ids_are_ignored(self) -> None:
        assert store.save_triage_results([{"id": "not_a_real_id", "is_policy": True, "ai_relevance": 5}], db_url=_DB) == 0

    def test_empty_results_noop(self) -> None:
        assert store.save_triage_results([], db_url=_DB) == 0
