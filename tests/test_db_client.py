"""Tests for local PostgreSQL database client."""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest


@pytest.fixture
def sample_articles():
    """Sample article records matching the structure from sync_pipeline."""
    return [
        {
            "id": "ic_123",
            "source_type": "gqy",
            "source_feed_id": "https://rss.arxiv.org/rss/cs.LG",
            "source_feed_name": "arXiv cs.LG",
            "source_article_id": "oai:arXiv.org:2604.23465",
            "title": "Machine learning models for estimating counterfactuals",
            "url": "https://arxiv.org/abs/2604.23465",
            "pic_url": "",
            "description": "Research on ML models for virtual control groups",
            "publish_time": "2026-04-28 12:00:00",
            "tags": ["虚拟对照组", "因果推断"],
            "reason": "ML virtual control group research",
            "actionable": "Engineers can use this framework",
            "hidden_signal": "虚拟对照组技术从概念走向临床实践验证",
            "content_source": "full_text",
            "signal_type": 6,
            "evidence_type": 2,
            "evidence_strength": 3,
            "novelty_score": 4,
            "impact_horizon": 3,
            "audience": [1, 2],
            "market_stage": 1,
            "confidence": 4,
            "entities": ["arXiv"],
            "cluster_hint": "反事实推断临床验证",
            "watch_keywords": ["counterfactual", "clinical trial"],
            "prediction": "未来会出现更多虚拟对照组临床验证案例。",
            "disconfirming_evidence": "若没有后续临床采用则降级。",
        },
        {
            "id": "ic_124",
            "source_type": "gqy",
            "source_feed_id": "https://rss.arxiv.org/rss/cs.CV",
            "source_feed_name": "arXiv cs.CV",
            "source_article_id": "oai:arXiv.org:2604.23466",
            "title": "When Does Removing LayerNorm Help?",
            "url": "https://arxiv.org/abs/2604.23466",
            "pic_url": "",
            "description": "Analysis of LayerNorm in transformers",
            "publish_time": "2026-04-28 12:00:00",
            "tags": ["深度学习", "LayerNorm"],
            "reason": "Deep learning optimization research",
            "actionable": "Practical insights for model architecture",
            "hidden_signal": "激活限制本质上是一种数据依赖的正则化器",
        },
    ]


def make_mock_cursor():
    """Create a properly configured mock cursor."""
    cur = MagicMock()
    return cur


def make_mock_conn():
    """Create a properly configured mock connection for use with 'with' statement."""
    cur = make_mock_cursor()
    conn = MagicMock()
    # Make cursor() return our mock cursor
    conn.cursor.return_value = cur
    # Make __enter__ return the connection itself (for 'with' statement)
    conn.__enter__.return_value = conn
    return conn, cur


class TestSaveArticles:
    """Test saving articles to local PostgreSQL."""

    def test_save_articles_creates_table_if_not_exists(self, sample_articles):
        """Should create articles table if it doesn't exist."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_articles
            save_articles(sample_articles, db_url="postgresql://localhost/test")

            # Verify CREATE TABLE was called
            sql_calls = [c[0][0] for c in cur.execute.call_args_list]
            create_calls = [s for s in sql_calls if "CREATE TABLE" in s.upper()]
            assert len(create_calls) > 0, f"No CREATE TABLE call found. Calls: {sql_calls}"

    def test_save_articles_inserts_all_records(self, sample_articles):
        """Should insert all article records."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_articles
            save_articles(sample_articles, db_url="postgresql://localhost/test")

            # Should have INSERT calls for each article
            sql_calls = [c[0][0] for c in cur.execute.call_args_list]
            insert_calls = [s for s in sql_calls if s.strip().upper().startswith("INSERT")]
            assert len(insert_calls) == len(sample_articles), f"Expected {len(sample_articles)} INSERT calls, got {len(insert_calls)}"

    def test_save_articles_commits_transaction(self, sample_articles):
        """Should commit after inserting."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_articles
            save_articles(sample_articles, db_url="postgresql://localhost/test")

            conn.commit.assert_called_once()

    def test_save_articles_handles_empty_list(self):
        """Should not execute any INSERT for empty list."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_articles
            result = save_articles([], db_url="postgresql://localhost/test")

            assert result == 0
            sql_calls = [c[0][0] for c in cur.execute.call_args_list]
            insert_calls = [s for s in sql_calls if s.strip().upper().startswith("INSERT")]
            assert len(insert_calls) == 0

    def test_save_articles_uses_upsert(self, sample_articles):
        """Should use ON CONFLICT to handle duplicates."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_articles
            save_articles(sample_articles, db_url="postgresql://localhost/test")

            sql_calls = [c[0][0] for c in cur.execute.call_args_list]
            upsert_calls = [s for s in sql_calls if "ON CONFLICT" in s.upper()]
            assert len(upsert_calls) > 0, "Should use ON CONFLICT for upsert"


class TestGetArticles:
    """Test retrieving articles from local PostgreSQL."""

    def test_get_articles_queries_with_limit(self):
        """Should query with limit and offset parameters."""
        conn, cur = make_mock_conn()
        cur.fetchall.return_value = []
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_articles
            get_articles(limit=10, offset=5, db_url="postgresql://localhost/test")

            cur.execute.assert_called()
            call_args = cur.execute.call_args
            sql = call_args[0][0]
            params = call_args[0][1]
            assert "LIMIT" in sql
            assert "OFFSET" in sql
            assert params == (10, 5)

    def test_get_articles_returns_list_of_dicts(self):
        """Should return list of article dictionaries."""
        conn, cur = make_mock_conn()
        cur.fetchall.return_value = [
            (
                "ic_123",
                "gqy",
                "https://rss.arxiv.org/rss/cs.LG",
                "arXiv cs.LG",
                "oai:arXiv.org:2604.23465",
                "Machine learning models",
                "https://arxiv.org/abs/2604.23465",
                "",
                "Research on ML models",
                datetime(2026, 4, 28, 12, 0, 0),
                '["虚拟对照组", "因果推断"]',
                3,  # importance_score
                "ML virtual control group",
                "Engineers can use this",
                "虚拟对照组技术",
                "full_text",
                6,
                2,
                3,
                4,
                3,
                "[1, 2]",
                1,
                4,
                '["arXiv"]',
                "反事实推断临床验证",
                '["counterfactual", "clinical trial"]',
                "未来会出现更多虚拟对照组临床验证案例。",
                "若没有后续临床采用则降级。",
                "{}",
                datetime(2026, 4, 28, 14, 0, 0),
                datetime(2026, 4, 28, 14, 0, 0),
            )
        ]
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_articles
            result = get_articles(limit=10, db_url="postgresql://localhost/test")

            assert isinstance(result, list)
            assert len(result) == 1
            article = result[0]
            assert article["id"] == "ic_123"
            assert article["title"] == "Machine learning models"
            assert article["source_type"] == "gqy"
            assert article["tags"] == ["虚拟对照组", "因果推断"]


class TestGetArticlesByDate:
    """Test retrieving articles by date range."""

    def test_get_articles_by_date_range(self):
        """Should query articles within date range."""
        conn, cur = make_mock_conn()
        cur.fetchall.return_value = []
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_articles_by_date
            get_articles_by_date(
                start_date="2026-04-28",
                end_date="2026-04-28",
                db_url="postgresql://localhost/test",
            )

            cur.execute.assert_called()
            call_args = cur.execute.call_args
            sql = call_args[0][0]
            params = call_args[0][1]
            assert "WHERE" in sql
            assert "publish_time" in sql
            assert ">=" in sql or "BETWEEN" in sql  # Uses >= or BETWEEN for date range
            assert "2026-04-28" in params


class TestSchema:
    """Test database schema creation."""

    def test_schema_has_required_columns(self):
        """Schema should define all required columns for articles."""
        from rss2cubox.db_client import ARTICLES_SCHEMA

        schema_lower = ARTICLES_SCHEMA.lower()
        required_columns = [
            "id",
            "source_type",
            "source_feed_id",
            "source_feed_name",
            "source_article_id",
            "title",
            "url",
            "pic_url",
            "description",
            "publish_time",
            "tags",
            "reason",
            "actionable",
            "hidden_signal",
            "created_at",
            "updated_at",
            "content_source",
            "signal_type",
            "evidence_type",
            "evidence_strength",
            "novelty_score",
            "impact_horizon",
            "audience",
            "market_stage",
            "confidence",
            "entities",
            "cluster_hint",
            "watch_keywords",
            "prediction",
            "disconfirming_evidence",
            "enrich_meta",
        ]
        for col in required_columns:
            assert col in schema_lower, f"Column {col} not found in schema"

    def test_schema_has_indexes_for_signal_fields(self):
        """Should index structured signal fields for filtering."""
        from rss2cubox.db_client import ARTICLES_SCHEMA

        schema_lower = ARTICLES_SCHEMA.lower()
        assert "idx_articles_signal_type" in schema_lower
        assert "idx_articles_evidence_strength" in schema_lower
        assert "idx_articles_novelty_score" in schema_lower
        assert "idx_articles_entities" in schema_lower
        assert "idx_articles_watch_keywords" in schema_lower

    def test_save_articles_writes_signal_extension_fields(self, sample_articles):
        """Should persist local-only enrich extension fields."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_articles

            save_articles(sample_articles[:1], db_url="postgresql://localhost/test")

            insert_call = next(
                call_args for call_args in cur.execute.call_args_list
                if call_args[0][0].strip().upper().startswith("INSERT")
            )
            params = insert_call[0][1]
            assert params["content_source"] == "full_text"
            assert params["signal_type"] == 6
            assert params["evidence_type"] == 2
            assert params["evidence_strength"] == 3
            assert params["novelty_score"] == 4
            assert params["impact_horizon"] == 3
            assert json.loads(params["audience"]) == [1, 2]
            assert params["market_stage"] == 1
            assert params["confidence"] == 4
            assert json.loads(params["entities"]) == ["arXiv"]
            assert params["cluster_hint"] == "反事实推断临床验证"
            assert json.loads(params["watch_keywords"]) == ["counterfactual", "clinical trial"]

    def test_schema_has_index_on_publish_time(self):
        """Should have index on publish_time for date range queries."""
        from rss2cubox.db_client import ARTICLES_SCHEMA

        assert "INDEX" in ARTICLES_SCHEMA.upper()
        assert "publish_time" in ARTICLES_SCHEMA.lower()

    def test_schema_has_primary_key_on_id(self):
        """Should have PRIMARY KEY on id column."""
        from rss2cubox.db_client import ARTICLES_SCHEMA

        assert "PRIMARY KEY" in ARTICLES_SCHEMA.upper()

    def test_prediction_loop_schema_has_required_tables(self):
        """Prediction loop schema should define clusters, predictions, and reviews."""
        from rss2cubox.db_client import PREDICTION_LOOP_SCHEMA

        schema_lower = PREDICTION_LOOP_SCHEMA.lower()
        assert "create table if not exists signal_clusters" in schema_lower
        assert "create table if not exists signal_cluster_articles" in schema_lower
        assert "create table if not exists trend_predictions" in schema_lower
        assert "create table if not exists prediction_reviews" in schema_lower


class TestGetAllArticleIds:
    """Test get_all_article_ids for deduplication."""

    def test_get_all_article_ids_returns_set(self):
        """Should return a set of article IDs."""
        conn, cur = make_mock_conn()
        cur.fetchall.return_value = [("eid_1",), ("eid_2",), ("eid_3",)]
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_all_article_ids
            result = get_all_article_ids(db_url="postgresql://localhost/test")

            assert isinstance(result, set)
            assert len(result) == 3
            assert "eid_1" in result
            assert "eid_2" in result
            assert "eid_3" in result

    def test_get_all_article_ids_uses_correct_query(self):
        """Should query id column with proper filtering."""
        conn, cur = make_mock_conn()
        cur.fetchall.return_value = []
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_all_article_ids
            get_all_article_ids(db_url="postgresql://localhost/test")

            cur.execute.assert_called()
            call_args = cur.execute.call_args
            sql = call_args[0][0]
            params = call_args[0][1] if len(call_args[0]) > 1 else None
            assert "SELECT id FROM articles" in sql
            assert "id IS NOT NULL" in sql
            assert "id != ''" in sql

    def test_get_all_article_ids_returns_empty_set_on_error(self):
        """Should return empty set when database query fails."""
        with patch("rss2cubox.db_client.psycopg.connect", side_effect=Exception("Connection failed")):
            from rss2cubox.db_client import get_all_article_ids
            result = get_all_article_ids(db_url="postgresql://localhost/test")

            assert result == set()

    def test_get_all_article_ids_returns_empty_set_when_no_url(self):
        """Should return empty set when LOCAL_DB_URL is not set."""
        with patch.dict("os.environ", {}, clear=True):
            from rss2cubox.db_client import get_all_article_ids
            result = get_all_article_ids(db_url=None)

            assert result == set()


class TestGetFeedCursors:
    """Test get_feed_cursors for feed cursor-based incremental fetching."""

    def test_get_feed_cursors_returns_dict(self):
        """Should return dict mapping source_feed_id to latest time."""
        conn, cur = make_mock_conn()
        cur.fetchall.return_value = [
            ("https://rss.arxiv.org/rss/cs.LG", datetime(2026, 4, 28, 12, 0, 0)),
            ("https://rsshub.app/sspai/index", datetime(2026, 4, 27, 10, 30, 0)),
        ]
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_feed_cursors
            result = get_feed_cursors(db_url="postgresql://localhost/test")

            assert isinstance(result, dict)
            assert len(result) == 2
            assert "https://rss.arxiv.org/rss/cs.LG" in result
            assert "https://rsshub.app/sspai/index" in result

    def test_get_feed_cursors_uses_group_by_query(self):
        """Should use GROUP BY source_feed_id with MAX(publish_time)."""
        conn, cur = make_mock_conn()
        cur.fetchall.return_value = []
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_feed_cursors
            get_feed_cursors(db_url="postgresql://localhost/test")

            cur.execute.assert_called()
            call_args = cur.execute.call_args
            sql = call_args[0][0]
            assert "GROUP BY source_feed_id" in sql
            assert "MAX(publish_time)" in sql
            assert "source_feed_id IS NOT NULL" in sql

    def test_get_feed_cursors_returns_empty_dict_on_error(self):
        """Should return empty dict when database query fails."""
        with patch("rss2cubox.db_client.psycopg.connect", side_effect=Exception("Connection failed")):
            from rss2cubox.db_client import get_feed_cursors
            result = get_feed_cursors(db_url="postgresql://localhost/test")

            assert result == {}

    def test_get_feed_cursors_returns_empty_dict_when_no_url(self):
        """Should return empty dict when LOCAL_DB_URL is not set."""
        with patch.dict("os.environ", {}, clear=True):
            from rss2cubox.db_client import get_feed_cursors
            result = get_feed_cursors(db_url=None)

            assert result == {}


class TestPredictionLoopPersistence:
    """Test local persistence helpers for prediction loop agents."""

    def test_save_signal_clusters_upserts_clusters_and_links_articles(self):
        conn, cur = make_mock_conn()
        cur.fetchone.return_value = (42,)
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_signal_clusters

            result = save_signal_clusters(
                {
                    "clusters": [{
                        "cluster_key": "3:异步软件工程代理",
                        "label": "异步软件工程代理",
                        "normalized_label": "异步软件工程代理",
                        "signal_type": 3,
                        "status": "warming",
                        "summary": "summary",
                        "entities": ["OpenAI"],
                        "watch_keywords": ["coding agent"],
                    }],
                    "links": [{
                        "cluster_key": "3:异步软件工程代理",
                        "article_id": "a1",
                        "relevance_score": 1.0,
                    }],
                },
                db_url="postgresql://localhost/test",
            )

            assert result == {"3:异步软件工程代理": 42}
            sql_calls = " ".join(c[0][0] for c in cur.execute.call_args_list)
            assert "INSERT INTO signal_clusters" in sql_calls
            assert "INSERT INTO signal_cluster_articles" in sql_calls

    def test_save_trend_predictions_inserts_rows(self):
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_trend_predictions

            result = save_trend_predictions(
                [{
                    "signal_cluster_key": "3:异步软件工程代理",
                    "prediction_type": 1,
                    "target_start_at": "2026-04-28T12:00:00+00:00",
                    "target_end_at": "2026-05-05T12:00:00+00:00",
                    "horizon_days": 7,
                    "prediction_title": "title",
                    "prediction_body": "body",
                    "watch_keywords": ["coding agent"],
                    "expected_evidence": {"minimum_support_count": 2},
                    "confidence": 4,
                }],
                {"3:异步软件工程代理": 42},
                db_url="postgresql://localhost/test",
            )

            assert result == 1
            sql_calls = " ".join(c[0][0] for c in cur.execute.call_args_list)
            assert "INSERT INTO trend_predictions" in sql_calls

    def test_save_prediction_review_inserts_row(self):
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_prediction_review

            assert save_prediction_review(
                {
                    "prediction_id": 1,
                    "score": 4,
                    "hit_level": "strong",
                    "supporting_articles": ["a1"],
                    "contradicting_articles": [],
                    "review_metrics": {"support_count": 1},
                },
                db_url="postgresql://localhost/test",
            ) is True
            sql_calls = " ".join(c[0][0] for c in cur.execute.call_args_list)
            assert "INSERT INTO prediction_reviews" in sql_calls
