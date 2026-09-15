"""政策信源抓取子系统。

与主 RSS 链路物理隔离：独立的配置文件（policy_sources.toml）、独立的表
（policy_documents / policy_source_state）、独立的入口（policy_runner）。
删掉这个包不会在主链路留下残留。
"""
from rss2cubox.policy.config import (  # noqa: F401
    SiteSpec,
    group_by_level,
    load_sources,
    parse_site,
)
from rss2cubox.policy.engine import (  # noqa: F401
    PolicyItem,
    ScrapeResult,
    parse_list_html,
    parse_policy_date,
    scrape_all,
    scrape_site,
    stable_policy_id,
)
from rss2cubox.policy.store import (  # noqa: F401
    POLICY_DOCUMENTS_SCHEMA,
    POLICY_SOURCE_STATE_SCHEMA,
    ensure_policy_schema,
    get_policy_documents,
    get_source_states,
    get_stale_sources,
    record_source_state,
    save_policy_documents,
)

__all__ = [
    "SiteSpec",
    "load_sources",
    "parse_site",
    "group_by_level",
    "PolicyItem",
    "ScrapeResult",
    "scrape_site",
    "scrape_all",
    "parse_list_html",
    "parse_policy_date",
    "stable_policy_id",
    "POLICY_DOCUMENTS_SCHEMA",
    "POLICY_SOURCE_STATE_SCHEMA",
    "ensure_policy_schema",
    "save_policy_documents",
    "record_source_state",
    "get_stale_sources",
    "get_source_states",
    "get_policy_documents",
]
