"""Tests for saving global_insights to local PostgreSQL."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_insights_payload():
    """Sample global insights payload matching the structure from global_agent."""
    return {
        "generated_at": "2026-04-28T08:32:47.583402+00:00",
        "source_count": 491,
        "trends": [
            "虚拟对照组技术正从概念走向临床实践验证",
            "激活限制本质上是一种数据依赖的正则化器",
        ],
        "weak_signals": [
            "ML反事实推断在单臂试验中的应用",
        ],
        "daily_advices": [
            "工程师可基于LGBM框架针对其他单臂试验进行迁移学习",
        ],
    }


def make_mock_conn():
    """Create a properly configured mock connection for use with 'with' statement."""
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__.return_value = conn
    return conn, cur


class TestSaveGlobalInsights:
    """Test saving global_insights to local PostgreSQL."""

    def test_save_global_insights_creates_table_if_not_exists(self, sample_insights_payload):
        """Should create global_insights table if it doesn't exist."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_global_insights

            save_global_insights(sample_insights_payload, db_url="postgresql://localhost/test")

            # Verify CREATE TABLE was called
            sql_calls = [c[0][0] for c in cur.execute.call_args_list]
            create_calls = [s for s in sql_calls if "CREATE TABLE" in s.upper()]
            assert len(create_calls) > 0, f"No CREATE TABLE call found. Calls: {sql_calls}"

    def test_save_global_insights_inserts_record(self, sample_insights_payload):
        """Should insert global_insights record."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_global_insights

            save_global_insights(sample_insights_payload, db_url="postgresql://localhost/test")

            # Verify INSERT was called
            sql_calls = [c[0][0] for c in cur.execute.call_args_list]
            insert_calls = [s for s in sql_calls if s.strip().upper().startswith("INSERT")]
            assert len(insert_calls) > 0, f"No INSERT call found. Calls: {sql_calls}"

    def test_save_global_insights_commits(self, sample_insights_payload):
        """Should commit transaction after insert."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_global_insights

            save_global_insights(sample_insights_payload, db_url="postgresql://localhost/test")

            conn.commit.assert_called_once()

    def test_save_global_insights_handles_missing_fields(self):
        """Should handle payload with missing fields gracefully."""
        conn, cur = make_mock_conn()
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_global_insights

            # Payload with only required field
            minimal_payload = {
                "generated_at": "2026-04-28T08:32:47.583402+00:00",
            }

            # Should not raise
            save_global_insights(minimal_payload, db_url="postgresql://localhost/test")

            # Verify INSERT was called
            sql_calls = [c[0][0] for c in cur.execute.call_args_list]
            insert_calls = [s for s in sql_calls if s.strip().upper().startswith("INSERT")]
            assert len(insert_calls) > 0


class TestGetGlobalInsights:
    """Test retrieving global_insights from local PostgreSQL."""

    def test_get_latest_global_insights_returns_single_record(self):
        """Should return the latest global_insights record."""
        conn, cur = make_mock_conn()
        # SELECT returns (generated_at, data) - 2 columns
        cur.fetchone.return_value = (
            datetime(2026, 4, 28, 8, 32, 47),
            '{"generated_at": "2026-04-28T08:32:47+00:00", "source_count": 491, "trends": ["trend1"]}',
        )
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_latest_global_insights

            result = get_latest_global_insights(db_url="postgresql://localhost/test")

            assert result is not None
            assert result["source_count"] == 491
            assert "trends" in result

    def test_get_latest_global_insights_returns_none_when_empty(self):
        """Should return None when no records exist."""
        conn, cur = make_mock_conn()
        cur.fetchone.return_value = None
        with patch("rss2cubox.db_client.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_latest_global_insights

            result = get_latest_global_insights(db_url="postgresql://localhost/test")

            assert result is None


class TestSchema:
    """Test global_insights schema."""

    def test_schema_has_required_columns(self):
        """Schema should define all required columns for global_insights."""
        from rss2cubox.db_client import GLOBAL_INSIGHTS_SCHEMA

        schema_lower = GLOBAL_INSIGHTS_SCHEMA.lower()
        assert "id" in schema_lower
        assert "generated_at" in schema_lower
        assert "data" in schema_lower

    def test_schema_has_index_on_generated_at(self):
        """Should have index on generated_at for ordering."""
        from rss2cubox.db_client import GLOBAL_INSIGHTS_SCHEMA

        assert "INDEX" in GLOBAL_INSIGHTS_SCHEMA.upper()
        assert "generated_at" in GLOBAL_INSIGHTS_SCHEMA.lower()
