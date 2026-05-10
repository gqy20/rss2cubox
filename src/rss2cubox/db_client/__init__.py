"""Local PostgreSQL database client — re-exports from sub-modules for backward compatibility."""
from rss2cubox.db_client._base import (  # noqa: F401
    _bounded_int,
    _bounded_int_list,
    _get_db_url,
    _optional_text,
    _parse_json_value,
    _parse_publish_time,
    _string_list,
)
from rss2cubox.db_client.articles import (  # noqa: F401
    ARTICLE_SELECT_COLUMNS,
    ARTICLES_SCHEMA,
    _row_to_article,
    get_all_article_ids,
    get_articles,
    get_articles_by_date,
    get_articles_cursor,
    get_feed_cursors,
    get_fulltexts_by_eids,
    save_articles,
    save_fulltext,
    save_fulltext_batch,
)
from rss2cubox.db_client.insights import (  # noqa: F401
    GLOBAL_INSIGHTS_SCHEMA,
    get_all_global_insights,
    get_latest_global_insights,
    save_global_insights,
)
from rss2cubox.db_client.predictions import (  # noqa: F401
    PREDICTION_LOOP_SCHEMA,
    ensure_prediction_loop_schema,
    get_due_trend_predictions,
    get_existing_signal_clusters,
    get_prediction_window_articles,
    get_recent_enriched_articles,
    get_recent_prediction_reviews,
    get_signal_clusters_for_prediction,
    save_prediction_review,
    save_signal_clusters,
    save_trend_predictions,
)
from rss2cubox.db_client.reports import (  # noqa: F401
    DAILY_REPORTS_SCHEMA,
    get_daily_report,
    get_recent_reports,
    save_daily_report,
)

__all__ = [
    # Schema constants
    "ARTICLES_SCHEMA",
    "PREDICTION_LOOP_SCHEMA",
    "GLOBAL_INSIGHTS_SCHEMA",
    "DAILY_REPORTS_SCHEMA",
    "ARTICLE_SELECT_COLUMNS",
    # Articles
    "save_articles",
    "save_fulltext",
    "save_fulltext_batch",
    "get_fulltexts_by_eids",
    "get_articles",
    "get_articles_cursor",
    "get_articles_by_date",
    "_row_to_article",
    "get_all_article_ids",
    "get_feed_cursors",
    # Predictions
    "ensure_prediction_loop_schema",
    "get_recent_enriched_articles",
    "_cluster_from_row",
    "get_existing_signal_clusters",
    "get_signal_clusters_for_prediction",
    "get_recent_prediction_reviews",
    "get_due_trend_predictions",
    "get_prediction_window_articles",
    "save_signal_clusters",
    "save_trend_predictions",
    "save_prediction_review",
    # Insights
    "save_global_insights",
    "get_latest_global_insights",
    "get_all_global_insights",
    # Reports
    "save_daily_report",
    "get_daily_report",
    "get_recent_reports",
    # Internal helpers (exposed for tests)
    "_optional_text",
    "_bounded_int",
    "_bounded_int_list",
    "_string_list",
    "_parse_json_value",
    "_parse_publish_time",
]
