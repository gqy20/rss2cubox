from datetime import datetime, timezone

import pytest

from rss2cubox import prediction_agent, prediction_review_agent, signal_cluster_agent
from rss2cubox.prediction_agent import run_trend_prediction_agent
from rss2cubox.prediction_review_agent import run_prediction_review_agent
from rss2cubox.signal_cluster_agent import build_cluster_key, run_signal_cluster_agent


NOW = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)


def _walk_schema_nodes(value):  # noqa: ANN001
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_schema_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_schema_nodes(child)


def test_prediction_agent_schemas_use_single_json_types() -> None:
    schemas = [
        signal_cluster_agent.SIGNAL_CLUSTER_OUTPUT_SCHEMA,
        prediction_agent.TREND_PREDICTION_OUTPUT_SCHEMA,
        prediction_review_agent.PREDICTION_REVIEW_OUTPUT_SCHEMA,
    ]

    for schema in schemas:
        for node in _walk_schema_nodes(schema):
            if "type" in node:
                assert isinstance(node["type"], str)


def test_signal_cluster_agent_groups_articles_by_signal_type_and_cluster_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    articles = [
        {
            "id": "a1",
            "title": "Codex enters CI",
            "source_feed_name": "OpenAI",
            "publish_time": "2026-04-27T10:00:00+00:00",
            "signal_type": 3,
            "importance_score": 4,
            "evidence_strength": 4,
            "novelty_score": 4,
            "confidence": 4,
            "cluster_hint": "异步软件工程代理",
            "entities": ["OpenAI", "Codex"],
            "watch_keywords": ["coding agent", "CI agent"],
        },
        {
            "id": "a2",
            "title": "Coding agent PR automation",
            "source_feed_name": "Hacker News",
            "publish_time": "2026-04-26T10:00:00+00:00",
            "signal_type": 3,
            "importance_score": 3,
            "evidence_strength": 3,
            "novelty_score": 3,
            "confidence": 4,
            "cluster_hint": "异步软件工程代理",
            "entities": ["GitHub"],
            "watch_keywords": ["PR automation"],
        },
    ]

    async def fake_run_json_agent(**kwargs):  # noqa: ANN001
        assert "Signal Cluster Agent" in kwargs["system_prompt"]
        return {
            "clusters": [{
                "cluster_key": "3:异步软件工程代理",
                "label": "异步软件工程代理",
                "normalized_label": "异步软件工程代理",
                "signal_type": 3,
                "status": "warming",
                "summary": "AI coding agent 正进入真实工程流程。",
                "entities": ["OpenAI", "Codex", "GitHub"],
                "watch_keywords": ["coding agent", "CI agent", "PR automation"],
                "first_seen_at": "2026-04-26T10:00:00+00:00",
                "last_seen_at": "2026-04-27T10:00:00+00:00",
                "article_count": 2,
                "source_count": 2,
                "avg_importance": 3.5,
                "avg_evidence_strength": 3.5,
                "avg_novelty": 3.5,
                "avg_confidence": 4,
                "recent_count_7d": 2,
                "previous_count_7d": 0,
                "burst_ratio": 4,
            }],
            "links": [
                {"cluster_key": "3:异步软件工程代理", "article_id": "a1", "relevance_score": 1},
                {"cluster_key": "3:异步软件工程代理", "article_id": "a2", "relevance_score": 1},
            ],
        }

    monkeypatch.setattr(signal_cluster_agent, "run_json_agent", fake_run_json_agent)

    result = run_signal_cluster_agent(articles, now=NOW)

    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["cluster_key"] == "3:异步软件工程代理"
    assert cluster["label"] == "异步软件工程代理"
    assert cluster["article_count"] == 2
    assert cluster["source_count"] == 2
    assert cluster["status"] in {"new", "warming", "bursting"}
    assert {link["article_id"] for link in result["links"]} == {"a1", "a2"}


def test_build_cluster_key_falls_back_to_title_when_hint_missing() -> None:
    key = build_cluster_key({"signal_type": 12, "title": "A new AI workflow"})
    assert key == "12:a-new-ai-workflow"


def test_trend_prediction_agent_creates_verifiable_prediction_from_active_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    clusters = [
        {
            "cluster_key": "3:异步软件工程代理",
            "label": "异步软件工程代理",
            "signal_type": 3,
            "status": "warming",
            "article_count": 5,
            "source_count": 3,
            "avg_evidence_strength": 4,
            "avg_novelty": 4,
            "avg_confidence": 4,
            "burst_ratio": 2.5,
            "watch_keywords": ["coding agent", "CI agent"],
            "summary": "AI coding agent 正进入真实工程流程。",
        }
    ]

    async def fake_run_json_agent(**kwargs):  # noqa: ANN001
        assert "AI 趋势预测 Agent" in kwargs["system_prompt"]
        return {
            "predictions": [{
                "signal_cluster_key": "3:异步软件工程代理",
                "prediction_type": 1,
                "created_at": "2026-04-28T12:00:00+00:00",
                "target_start_at": "2026-04-28T12:00:00+00:00",
                "target_end_at": "2026-05-05T12:00:00+00:00",
                "horizon_days": 7,
                "prediction_title": "异步软件工程代理未来7天验证",
                "prediction_body": "未来7天该方向应出现多源工程实践证据。",
                "watch_keywords": ["coding agent", "CI agent"],
                "expected_evidence": {
                    "minimum_support_count": 2,
                    "required_source_count": 2,
                    "required_evidence_types": [1, 4, 5, 9],
                },
                "disconfirming_evidence": "如果没有工程实践证据则降级。",
                "baseline_metrics": {"burst_ratio": 2.5},
                "confidence": 4,
                "status": "pending",
            }]
        }

    monkeypatch.setattr(prediction_agent, "run_json_agent", fake_run_json_agent)

    predictions = run_trend_prediction_agent(clusters, now=NOW)

    assert len(predictions) == 1
    prediction = predictions[0]
    assert prediction["signal_cluster_key"] == "3:异步软件工程代理"
    assert prediction["prediction_type"] == 1
    assert prediction["target_start_at"] == "2026-04-28T12:00:00+00:00"
    assert prediction["target_end_at"] == "2026-05-05T12:00:00+00:00"
    assert prediction["expected_evidence"]["minimum_support_count"] >= 2
    assert prediction["watch_keywords"] == ["coding agent", "CI agent"]


def test_prediction_review_agent_scores_supporting_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    prediction = {
        "id": 1,
        "signal_cluster_key": "3:异步软件工程代理",
        "watch_keywords": ["coding agent", "CI agent"],
        "expected_evidence": {
            "minimum_support_count": 2,
            "required_source_count": 2,
            "required_evidence_types": [1, 4, 5, 9],
        },
    }
    articles = [
        {
            "id": "a1",
            "title": "Official coding agent CI launch",
            "hidden_signal": "coding agent enters CI",
            "source_feed_name": "OpenAI",
            "evidence_type": 1,
            "evidence_strength": 4,
        },
        {
            "id": "a2",
            "title": "PR automation with CI agent",
            "hidden_signal": "PR automation workflow",
            "source_feed_name": "GitHub",
            "evidence_type": 9,
            "evidence_strength": 4,
        },
    ]

    async def fake_run_json_agent(**kwargs):  # noqa: ANN001
        assert "Prediction Review Agent" in kwargs["system_prompt"]
        return {
            "prediction_id": 1,
            "score": 4,
            "hit_level": "strong",
            "supporting_articles": ["a1", "a2"],
            "contradicting_articles": [],
            "actual_observation": "目标窗口出现多源工程实践证据。",
            "why_score": "满足支持数量和来源要求。",
            "improvement_advice": "下次提高官方或开源证据要求。",
            "review_metrics": {
                "support_count": 2,
                "source_count": 2,
                "avg_evidence_strength": 4,
                "contradiction_count": 0,
            },
        }

    monkeypatch.setattr(prediction_review_agent, "run_json_agent", fake_run_json_agent)

    review = run_prediction_review_agent(prediction, articles)

    assert review["prediction_id"] == 1
    assert review["score"] >= 4
    assert review["hit_level"] in {"strong", "exact"}
    assert review["supporting_articles"] == ["a1", "a2"]
    assert review["review_metrics"]["support_count"] == 2
    assert review["review_metrics"]["source_count"] == 2


class TestClusterIndexAndFileMode:
    """cluster agent 改为「索引进 prompt + 明细写文件」。

    动机：原先 200 篇文章全字段 json.dumps 进 prompt，实测写入 CLI 593,402 bytes、
    input 197,530 tokens（占 200K 窗口的 98.8%），且 links 返回空数组导致
    13 个簇全部 article_count=0。
    """

    @staticmethod
    def _articles(n: int) -> list[dict]:
        return [
            {
                "id": f"{i:064x}",
                "title": f"关于 AI Agent 的第 {i} 篇报道",
                "cluster_hint": "agent 工程",
                "entities": ["OpenAI", "Anthropic"],
                "watch_keywords": ["agent", "context"],
                # 长度对齐真实数据：实测单篇全字段投影约 1,604 字符，
                # 其中 hidden_signal 平均 152、reason 57、actionable 58、
                # prediction 74、disconfirming_evidence 71。夹具若显著短于真实值，
                # "索引比全字段小多少"这类断言就会失真。
                "hidden_signal": "隐藏信号" * 38,
                "reason": "判定理由" * 15,
                "actionable": "可执行动作" * 12,
                "prediction": "趋势预测" * 18,
                "disconfirming_evidence": "反证条件" * 18,
                "description": "摘要" * 26,
                "source_feed_name": "某科技媒体源名称" * 2,
                "importance_score": 4,
                "signal_type": 3,
                "publish_time": "2026-09-16T00:00:00+00:00",
                "url": f"https://example.com/{i}",
            }
            for i in range(n)
        ]

    def test_index_uses_short_refs_and_covers_all(self) -> None:
        from rss2cubox.signal_cluster_agent import _build_index

        arts = self._articles(200)
        index, refs, detail = _build_index(arts)
        assert len(index) == 200 and len(detail) == 200
        assert len(refs) == 200
        assert index[0]["ref"] == "a001" and index[-1]["ref"] == "a200"
        # ref 必须能回映到真实的 64 位 id
        assert refs["a001"] == arts[0]["id"]
        assert all(len(v) == 64 for v in refs.values())

    def test_index_excludes_long_enrich_fields(self) -> None:
        """索引只放聚类需要的字段；hidden_signal / reason 这些长文本只在明细文件里。"""
        from rss2cubox.signal_cluster_agent import _build_index

        index, _refs, detail = _build_index(self._articles(3))
        for row in index:
            assert "hidden_signal" not in row and "reason" not in row
        for row in detail:
            assert "hidden_signal" in row and "reason" in row

    def test_index_much_smaller_than_full_inline(self) -> None:
        """核心收益：索引体积必须远小于全字段内联。"""
        import json
        from rss2cubox.signal_cluster_agent import _build_index

        arts = self._articles(200)
        index, _refs, _detail = _build_index(arts)
        index_chars = len(json.dumps(index, ensure_ascii=False))
        full_chars = len(json.dumps(arts, ensure_ascii=False))
        assert index_chars < full_chars * 0.35, (
            f"索引 {index_chars} 字符未显著小于全字段 {full_chars} 字符"
        )

    def test_detail_written_as_jsonl_one_per_line(self) -> None:
        """JSONL 而非 JSON 数组：这样 Grep 能按行精确定位、Read 能分页。"""
        import json
        from rss2cubox.agent_sdk_runner import cleanup_temp_files, write_temp_jsonl
        from rss2cubox.signal_cluster_agent import _build_index

        _i, _r, detail = _build_index(self._articles(5))
        path = write_temp_jsonl(detail)
        try:
            lines = [ln for ln in open(path, encoding="utf-8").read().splitlines() if ln.strip()]
            assert len(lines) == 5
            first = json.loads(lines[0])
            assert first["ref"] == "a001"
        finally:
            cleanup_temp_files(path)

    def test_prompt_contains_index_and_path_not_full_articles(self, monkeypatch) -> None:
        from rss2cubox import signal_cluster_agent as mod

        captured: dict = {}

        async def fake_agent(**kwargs):
            captured.update(kwargs)
            return {"clusters": [], "links": []}

        monkeypatch.setattr(mod, "run_json_agent", fake_agent)
        monkeypatch.setattr(mod, "run_with_fallback", lambda coro, **kw: coro())
        mod.run_signal_cluster_agent(self._articles(30), now=NOW)

        prompt = captured["prompt"]
        assert '"ref": "a001"' in prompt, "索引必须在 prompt 里"
        assert captured["allowed_tools"] == ["Read", "Grep", "Glob"]
        assert captured["max_turns"] == mod.SIGNAL_CLUSTER_MAX_TURNS
        # 长文本字段不该出现在 prompt 里（它们在明细文件中）
        assert "这是不该进索引的长文本" not in prompt
        # 明细文件路径必须告知
        assert ".jsonl" in prompt

    def test_temp_file_cleaned_up_even_on_error(self, monkeypatch) -> None:
        from rss2cubox import signal_cluster_agent as mod

        created: list[str] = []
        real_write = mod.write_temp_jsonl

        def spy(rows, **kw):
            path = real_write(rows, **kw)
            created.append(path)
            return path

        async def boom(**kwargs):
            raise RuntimeError("agent down")

        monkeypatch.setattr(mod, "write_temp_jsonl", spy)
        monkeypatch.setattr(mod, "run_json_agent", boom)
        monkeypatch.setattr(mod, "run_with_fallback", lambda coro, **kw: coro())

        with pytest.raises(RuntimeError):
            mod.run_signal_cluster_agent(self._articles(3), now=NOW)

        import os
        assert created and not os.path.exists(created[0]), "异常路径也必须清理临时文件"

    def test_links_accept_both_ref_and_real_id(self) -> None:
        from rss2cubox.signal_cluster_agent import _validate_payload

        real_id = "x" * 64
        payload = {
            "clusters": [{"cluster_key": "3:agent"}],
            "links": [
                {"cluster_key": "3:agent", "article_id": "a001", "relevance_score": 1},
                {"cluster_key": "3:agent", "article_id": real_id, "relevance_score": 1},
            ],
        }
        out = _validate_payload(payload, {real_id}, ref_to_id={"a001": real_id})
        # ref 和真实 id 都映到同一个 id，去重后只剩一条
        assert len(out["links"]) == 1
        assert out["links"][0]["article_id"] == real_id

    def test_hallucinated_ref_counted_not_silently_dropped(self) -> None:
        from rss2cubox.signal_cluster_agent import _validate_payload

        payload = {
            "clusters": [{"cluster_key": "3:agent"}],
            "links": [
                {"cluster_key": "3:agent", "article_id": "a001", "relevance_score": 1},
                {"cluster_key": "3:agent", "article_id": "a999", "relevance_score": 1},
                {"cluster_key": "不存在的簇", "article_id": "a001", "relevance_score": 1},
            ],
        }
        out = _validate_payload(payload, {"y" * 64}, ref_to_id={"a001": "y" * 64})
        assert len(out["links"]) == 1
        assert out["unmapped_refs"] == 2, "编造的 ref 和无效簇必须被计数，不能静默丢弃"

    def test_low_link_coverage_emits_warning(self, monkeypatch) -> None:
        """回归：上次 links 返回空数组，13 个簇全 article_count=0，但全程零告警。"""
        from rss2cubox import signal_cluster_agent as mod

        events: list[tuple] = []

        async def fake_agent(**kwargs):
            return {"clusters": [{"cluster_key": "3:agent", "label": "x"}], "links": []}

        monkeypatch.setattr(mod, "run_json_agent", fake_agent)
        monkeypatch.setattr(mod, "run_with_fallback", lambda coro, **kw: coro())
        mod.run_signal_cluster_agent(
            self._articles(10), now=NOW,
            log_event=lambda level, event, **kw: events.append((level, event, kw)),
        )

        cov = [e for e in events if e[1] == "signal_cluster_link_coverage"]
        assert cov, "必须发出覆盖率事件"
        level, _event, fields = cov[0]
        assert level == "WARN", "覆盖率 0 必须告警而不是 INFO"
        assert fields["coverage"] == 0.0 and fields["articles"] == 10

    def test_full_coverage_emits_info(self, monkeypatch) -> None:
        from rss2cubox import signal_cluster_agent as mod

        events: list[tuple] = []
        arts = self._articles(4)

        async def fake_agent(**kwargs):
            return {
                "clusters": [{"cluster_key": "3:agent", "label": "x"}],
                "links": [{"cluster_key": "3:agent", "article_id": f"a{i:03d}", "relevance_score": 1}
                          for i in range(1, 5)],
            }

        monkeypatch.setattr(mod, "run_json_agent", fake_agent)
        monkeypatch.setattr(mod, "run_with_fallback", lambda coro, **kw: coro())
        result = mod.run_signal_cluster_agent(
            arts, now=NOW, log_event=lambda lv, ev, **kw: events.append((lv, ev, kw)))

        cov = next(e for e in events if e[1] == "signal_cluster_link_coverage")
        assert cov[0] == "INFO" and cov[2]["coverage"] == 1.0
        # links 里的 ref 必须已回映成真实 id，否则写库会撞外键
        assert {l["article_id"] for l in result["links"]} == {a["id"] for a in arts}


# ── 聚合评分必须从真实文章算，不能采信模型 ──────────────────
import os as _os
from pathlib import Path as _Path

import psycopg as _psycopg
from dotenv import load_dotenv as _load_dotenv

_load_dotenv(_Path(__file__).resolve().parent.parent / ".env", override=False)
_DB = _os.getenv("LOCAL_DB_URL", "").strip()


def _db_ok() -> bool:
    if not _DB:
        return False
    try:
        with _psycopg.connect(_DB, connect_timeout=5):
            return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _db_ok(), reason="LOCAL_DB_URL 不可用（先 make db）")
class TestClusterAggregatesFromRealArticles:
    """回归：avg_importance 曾直接采信模型输出。

    模型给的是 0~1 区间（实测 0.60~0.77），而 articles.importance_score 是 1~5，
    prediction_agent 的 prompt 又要求「优先选择 avg_importance ≥3.5 的 cluster」，
    于是这条筛选规则永远命中不了任何簇——静默失效，日志里看不出来。
    source_count 同理：prompt 明确禁止模型输出它，所以恒为 0。
    """

    LABEL = "pytest_agg_check"

    @pytest.fixture(autouse=True)
    def _clean(self):
        def wipe():
            with _psycopg.connect(_DB) as c:
                c.cursor().execute("DELETE FROM signal_clusters WHERE normalized_label=%s", (self.LABEL,))
                c.commit()
        wipe(); yield; wipe()

    def test_aggregates_computed_not_trusted_from_model(self) -> None:
        from rss2cubox.db_client import save_signal_clusters

        with _psycopg.connect(_DB) as c:
            cur = c.cursor()
            cur.execute("""SELECT id, importance_score, confidence, source_feed_id
                           FROM articles
                           WHERE coalesce(reason,'')<>'' AND importance_score IS NOT NULL
                           LIMIT 6""")
            rows = cur.fetchall()
        if len(rows) < 2:
            pytest.skip("库里没有足够的已 enrich 文章")

        imp = [r[1] for r in rows if r[1] is not None]
        conf = [r[2] for r in rows if r[2] is not None]
        srcs = {r[3] for r in rows if r[3]}
        key = f"9:{self.LABEL}"
        result = {
            "clusters": [{
                "cluster_key": key, "label": self.LABEL, "normalized_label": self.LABEL,
                "signal_type": 9, "status": "new", "summary": "s",
                # 模型给的错误区间值，必须被真实计算覆盖
                "avg_importance": 0.65, "avg_confidence": 0.75, "source_count": 0,
            }],
            "links": [{"cluster_key": key, "article_id": r[0], "relevance_score": 1.0} for r in rows],
        }
        save_signal_clusters(result)

        with _psycopg.connect(_DB) as c:
            cur = c.cursor()
            cur.execute("""SELECT article_count, source_count, avg_importance, avg_confidence
                           FROM signal_clusters WHERE normalized_label=%s""", (self.LABEL,))
            got = cur.fetchone()

        assert got is not None, "簇未写入"
        assert got[0] == len(rows)
        assert got[1] == len(srcs), "source_count 应从真实文章的 source_feed_id 去重算出，不是恒 0"
        assert float(got[2]) == pytest.approx(sum(imp) / len(imp), abs=0.01)
        assert float(got[2]) > 1.0, "avg_importance 必须落在 1~5 区间，不能是模型编的 0~1"
        if conf:
            assert float(got[3]) == pytest.approx(sum(conf) / len(conf), abs=0.01)

    def test_falls_back_to_model_when_no_links(self) -> None:
        """没有 links 时无从计算，应回退到模型给的值而不是写 NULL。"""
        from rss2cubox.db_client import save_signal_clusters

        key = f"9:{self.LABEL}"
        save_signal_clusters({
            "clusters": [{"cluster_key": key, "label": self.LABEL, "normalized_label": self.LABEL,
                          "signal_type": 9, "status": "new", "summary": "s",
                          "avg_importance": 0.65, "avg_confidence": 0.75}],
            "links": [],
        })
        with _psycopg.connect(_DB) as c:
            cur = c.cursor()
            cur.execute("SELECT article_count, avg_importance FROM signal_clusters WHERE normalized_label=%s",
                        (self.LABEL,))
            got = cur.fetchone()
        assert got[0] == 0
        assert float(got[1]) == pytest.approx(0.65)
