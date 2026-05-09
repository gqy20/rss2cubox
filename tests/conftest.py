"""Shared fixtures for all test modules."""
from unittest.mock import MagicMock

import pytest


class FeedParserDict(dict):
    """A dict subclass that mimics feedparser.util.FeedParserDict for testing."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


@pytest.fixture
def mock_db_conn():
    """Create a properly configured mock DB connection for 'with' statement."""
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__.return_value = conn
    return conn, cur
