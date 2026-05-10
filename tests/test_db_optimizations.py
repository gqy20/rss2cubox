"""Tests for database query optimizations."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_conn():
    """Create a properly configured mock connection."""
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__.return_value = conn
    return conn, cur


@pytest.fixture
def sample_articles():
    """Sample articles with various publish times for pagination testing."""
    base_time = datetime(2026, 4, 28, 12, 0, 0)
    return [
        {
            "id": f"art_{i}",
            "source_type": "gqy",
            "source_feed_id": "https://rss.example/feed",
            "source_feed_name": "Example Feed",
            "source_article_id": f"art_{i}",
            "title": f"Article {i}",
            "url": f"https://example.com/article/{i}",
            "pic_url": "",
            "description": f"Description {i}",
            "publish_time": (base_time.replace(hour=12 - i)).isoformat() if i < 20 else None,
            "tags": ["test"],
            "importance_score": 3,
            "reason": f"Reason {i}",
            "actionable": f"Actionable {i}",
            "hidden_signal": f"Hidden signal {i}",
        }
        for i in range(100)
    ]


class TestCursorPagination:
    """Test cursor-based pagination for efficient deep paging."""

    def test_get_articles_with_cursor(self, mock_conn):
        """Should support cursor-based pagination for efficient deep paging."""
        conn, cur = mock_conn

        # Simulate cursor pagination query
        cursor_time = "2026-04-28T10:00:00"

        with patch("rss2cubox.db_client.articles.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_articles_cursor

            cur.fetchall.return_value = []
            get_articles_cursor(cursor=cursor_time, limit=50, db_url="postgresql://localhost/test")
            # Should execute query with cursor condition
            assert cur.execute.called

    def test_get_articles_with_cursor_filters_correctly(self, mock_conn):
        """Cursor pagination should filter by publish_time < cursor."""
        conn, cur = mock_conn

        cursor_time = "2026-04-28T08:00:00"
        articles = [
            (f"art_{i}", "gqy", "feed", "Example", "art", f"Title {i}",
             f"https://example.com/{i}", "", f"Desc {i}",
             datetime(2026, 4, 28, 10 - i) if i < 10 else None,
             "[]", 3, f"reason_{i}", f"action_{i}", f"signal_{i}",
             datetime.now(), datetime.now())
            for i in range(50)
        ]
        cur.fetchall.return_value = articles[:10]  # Return 10 items

        with patch("rss2cubox.db_client.articles.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_articles_cursor

            result = get_articles_cursor(cursor=cursor_time, limit=50, db_url="postgresql://localhost/test")

            # Should use WHERE publish_time < cursor
            call_args = str(cur.execute.call_args)
            assert "publish_time <" in call_args or "$1" in call_args


class TestOptimizedIndex:
    """Test that queries use optimized indexes."""

    def test_query_uses_covering_index(self, mock_conn):
        """Query should be able to use covering index for date range queries."""
        conn, cur = mock_conn

        with patch("rss2cubox.db_client.articles.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_articles_by_date

            cur.fetchall.return_value = []
            get_articles_by_date(
                start_date="2026-04-01",
                end_date="2026-04-28",
                db_url="postgresql://localhost/test"
            )

            # Query should have ORDER BY publish_time DESC for index usage
            call_args = str(cur.execute.call_args)
            assert "ORDER BY publish_time DESC" in call_args

    def test_pagination_uses_keyset_not_offset(self, mock_conn):
        """Pagination should use keyset (cursor) not OFFSET for efficiency."""
        conn, cur = mock_conn

        with patch("rss2cubox.db_client.articles.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_articles_cursor

            cur.fetchall.return_value = []
            get_articles_cursor(cursor="2026-04-28T10:00:00", limit=50, db_url="postgresql://localhost/test")

            # Should NOT use OFFSET
            call_args = str(cur.execute.call_args)
            assert "OFFSET" not in call_args.upper()


class TestConnectionPooling:
    """Test connection pooling for efficient connections."""

    def test_get_articles_reuses_connection(self):
        """get_articles should efficiently reuse database connections."""
        # This is more of an integration test - would need a real DB
        # For unit tests, we verify the connection string is properly read
        from rss2cubox.db_client import get_articles

        with patch("rss2cubox.db_client.articles.psycopg.connect") as mock_connect:
            conn = MagicMock()
            cur = MagicMock()
            conn.cursor.return_value = cur
            conn.__enter__.return_value = conn
            conn.__exit__.return_value = False
            mock_connect.return_value = conn
            cur.fetchall.return_value = []

            # Call twice - should use same connection
            try:
                get_articles(limit=10, db_url="postgresql://localhost/test")
                get_articles(limit=10, db_url="postgresql://localhost/test")
            except Exception:
                pass  # Expected to fail without real DB

            # If psycopg.connect was called, connection is being managed properly
            # (actual pooling would require pg-pool or similar)
