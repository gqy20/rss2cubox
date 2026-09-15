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
    parse_rss_items,
    scrape_all,
    scrape_site,
    stable_policy_id,
)
from rss2cubox.policy.enrich_agent import (  # noqa: F401
    INSTRUMENT_TYPES,
    OBLIGATION_LEVELS,
    POLICY_ENRICH_SCHEMA,
    STAGES,
    SYSTEM_PROMPT as POLICY_ENRICH_SYSTEM_PROMPT,
    enrich_policy_documents,
)
from rss2cubox.policy.triage_agent import (  # noqa: F401
    SYSTEM_PROMPT as POLICY_TRIAGE_SYSTEM_PROMPT,
    TRIAGE_OUTPUT_SCHEMA,
    triage_policy_documents,
)
from rss2cubox.policy.store import (  # noqa: F401
    POLICY_DOCUMENTS_SCHEMA,
    POLICY_SOURCE_STATE_SCHEMA,
    count_policy_documents,
    count_policy_triage,
    ensure_policy_schema,
    get_documents_for_enrichment,
    get_policy_documents,
    get_source_states,
    get_stale_sources,
    get_untriaged_documents,
    record_source_state,
    save_policy_documents,
    save_policy_enrichment,
    save_triage_results,
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
    "parse_rss_items",
    "parse_policy_date",
    "stable_policy_id",
    "POLICY_ENRICH_SCHEMA",
    "POLICY_ENRICH_SYSTEM_PROMPT",
    "INSTRUMENT_TYPES",
    "STAGES",
    "OBLIGATION_LEVELS",
    "enrich_policy_documents",
    "TRIAGE_OUTPUT_SCHEMA",
    "POLICY_TRIAGE_SYSTEM_PROMPT",
    "triage_policy_documents",
    "POLICY_DOCUMENTS_SCHEMA",
    "POLICY_SOURCE_STATE_SCHEMA",
    "ensure_policy_schema",
    "save_policy_documents",
    "save_policy_enrichment",
    "get_documents_for_enrichment",
    "get_untriaged_documents",
    "save_triage_results",
    "count_policy_triage",
    "count_policy_documents",
    "record_source_state",
    "get_stale_sources",
    "get_source_states",
    "get_policy_documents",
]
