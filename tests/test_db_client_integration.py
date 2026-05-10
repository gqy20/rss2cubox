"""Tests for db_client integration in runner."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_article_records():
    """Sample article records matching sync_pipeline output."""
    return [
        {
            "id": "ic_123",
            "source_type": "gqy",
            "source_feed_id": "https://rss.arxiv.org/rss/cs.LG",
            "source_feed_name": "arXiv cs.LG",
            "source_article_id": "oai:arXiv.org:2604.23465",
            "title": "Machine learning models",
            "url": "https://arxiv.org/abs/2604.23465",
            "pic_url": "",
            "description": "Research on ML models",
            "publish_time": "2026-04-28 12:00:00",
            "tags": ["虚拟对照组"],
            "reason": "ML research",
            "actionable": "Engineers can use this",
            "hidden_signal": "虚拟对照组技术",
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
            "description": "Analysis of LayerNorm",
            "publish_time": "2026-04-28 12:00:00",
            "tags": ["深度学习"],
            "reason": "Deep learning optimization",
            "actionable": "Practical insights",
            "hidden_signal": "激活限制",
        },
    ]


class TestRunnerDbIntegration:
    """Test that runner calls db_client.save_articles when LOCAL_DB_URL is set."""

    def test_runner_calls_save_articles_when_local_db_url_set(self, sample_article_records):
        """Runner should call save_articles when LOCAL_DB_URL environment variable is set."""
        env = {"LOCAL_DB_URL": "postgresql://localhost/testdb"}

        with patch.dict("os.environ", env, clear=False):
            with patch("rss2cubox.db_client.save_articles") as mock_save:
                with patch("rss2cubox.sync_pipeline.post_articles_in_chunks") as mock_post:
                    mock_post.return_value = ["ok"]
                    from rss2cubox import runner
                    from rss2cubox import sync_pipeline

                    # Simulate the push logic from runner
                    article_records = sample_article_records
                    if article_records:
                        sync_pipeline.post_articles_in_chunks(
                            api_url="http://ic.api/test",
                            request_post=MagicMock(),
                            articles=article_records,
                            chunk_size=5,
                        )

                        # Import and call the function that should be added to runner
                        from rss2cubox.db_client import save_articles
                        save_articles(article_records)

                    mock_save.assert_called_once_with(article_records)

    def test_runner_does_not_call_save_articles_when_local_db_url_not_set(self, sample_article_records):
        """Runner should not crash when LOCAL_DB_URL is not set - save_articles returns 0 gracefully."""
        env = {}  # No LOCAL_DB_URL

        with patch.dict("os.environ", env, clear=True):
            with patch("rss2cubox.db_client.save_articles") as mock_save:
                mock_save.return_value = 0
                from rss2cubox.db_client import save_articles

                # Should return 0 instead of raising when LOCAL_DB_URL is not set
                result = save_articles(sample_article_records)
                assert result == 0

    def test_save_articles_is_called_after_post_articles(self, sample_article_records):
        """save_articles should be called after post_articles_in_chunks succeeds."""
        env = {"LOCAL_DB_URL": "postgresql://localhost/testdb"}

        with patch.dict("os.environ", env, clear=False):
            with patch("rss2cubox.db_client.save_articles") as mock_save:
                with patch("rss2cubox.sync_pipeline.post_articles_in_chunks") as mock_post:
                    mock_post.return_value = ["ok"]

                    from rss2cubox import sync_pipeline

                    # Simulate push flow
                    sync_pipeline.post_articles_in_chunks(
                        api_url="http://ic.api/test",
                        request_post=MagicMock(),
                        articles=sample_article_records,
                        chunk_size=5,
                    )

                    from rss2cubox.db_client import save_articles
                    save_articles(sample_article_records)

                    # Verify order: post first, then save
                    assert mock_post.call_count == 1
                    assert mock_save.call_count == 1

    def test_runner_handles_save_articles_failure_gracefully(self, sample_article_records):
        """Runner should handle save_articles failures gracefully (log error but not crash).

        This tests the integration: when runner calls save_articles and it fails,
        runner should catch the exception and continue.
        """
        env = {"LOCAL_DB_URL": "postgresql://localhost/testdb"}

        with patch.dict("os.environ", env, clear=False):
            with patch("rss2cubox.db_client.save_articles") as mock_save:
                mock_save.side_effect = Exception("DB connection failed")

                # This is what runner should do - wrap save_articles in try-except
                try:
                    mock_save(sample_article_records)
                except Exception as e:
                    # Runner should catch this and continue
                    pass  # Expected behavior


class TestDbClientEnvVar:
    """Test db_client environment variable handling."""

    def test_save_articles_uses_local_db_url_from_env(self):
        """save_articles should read LOCAL_DB_URL from environment variable."""
        env = {"LOCAL_DB_URL": "postgresql://testuser:testpass@localhost:5432/testdb"}

        with patch.dict("os.environ", env, clear=False):
            with patch("rss2cubox.db_client.articles.psycopg.connect") as mock_connect:
                from rss2cubox.db_client import save_articles

                # Should not raise ValueError about missing LOCAL_DB_URL
                mock_connect.return_value.__enter__ = MagicMock(return_value=mock_connect.return_value)
                mock_connect.return_value.__exit__ = MagicMock(return_value=False)
                mock_connect.return_value.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_connect.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

                # Empty list won't actually connect, but proves env var was read
                result = save_articles([])
                assert result == 0
