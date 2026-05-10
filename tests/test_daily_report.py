"""Tests for daily_report_agent module (TDD Red Phase)."""
import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def sample_today_articles():
    """今日文章数据样本"""
    return [
        {
            "id": "art_001",
            "source_type": "gqy",
            "source_feed_id": "https://www.anthropic.com/news/rss",
            "source_feed_name": "Anthropic News",
            "title": "Claude 4.7 发布：最强推理模型",
            "url": "https://www.anthropic.com/news/claude-4-7",
            "pic_url": "",
            "description": "Anthropic 发布 Claude 4.7...",
            "publish_time": datetime(2026, 5, 9, 10, 30, tzinfo=timezone.utc),
            "tags": ["模型发布", "Claude"],
            "importance_score": 5,
            "reason": "Anthropic 新旗舰模型发布",
            "actionable": "关注 benchmark 变化",
            "hidden_signal": "Anthropic 推出推理能力最强的模型，重新定义 SOTA",
            "content_source": "full_text",
            "signal_type": 1,
            "evidence_type": 1,
            "evidence_strength": 5,
            "novelty_score": 5,
            "impact_horizon": 2,
            "audience": [1, 3],
            "market_stage": 3,
            "confidence": 5,
            "entities": ["Anthropic", "Claude"],
            "cluster_hint": "claude-model-release",
            "watch_keywords": ["claude", "model", "benchmark"],
        },
        {
            "id": "art_002",
            "source_type": "gqy",
            "source_feed_id": "https://sspai.com/feed",
            "source_feed_name": "少数派",
            "title": "Agent 运行时框架对比评测",
            "url": "https://sspai.com/post/12345",
            "pic_url": "",
            "description": "主流 Agent 框架深度对比...",
            "publish_time": datetime(2026, 5, 9, 14, 0, tzinfo=timezone.utc),
            "tags": ["Agent", "框架"],
            "importance_score": 4,
            "reason": "Agent 框架生态持续演进",
            "actionable": "评估团队技术选型",
            "hidden_signal": "Agent 编排框架从实验走向生产级成熟",
            "content_source": "full_text",
            "signal_type": 2,
            "evidence_type": 2,
            "evidence_strength": 4,
            "novelty_score": 4,
            "impact_horizon": 3,
            "audience": [1, 2],
            "market_stage": 3,
            "confidence": 4,
            "entities": ["LangChain", "CrewAI"],
            "cluster_hint": "agent-orchestration-framework",
            "watch_keywords": ["agent", "framework", "runtime"],
        },
        {
            "id": "art_003",
            "source_type": "gqy",
            "source_feed_id": "https://openai.com/blog/rss",
            "source_feed_name": "OpenAI Blog",
            "title": "GPT-5 定价调整公告",
            "url": "https://openai.com/blog/pricing-update",
            "pic_url": "",
            "description": "OpenAI 调整 API 定价...",
            "publish_time": datetime(2026, 5, 9, 16, 0, tzinfo=timezone.utc),
            "tags": ["定价", "OpenAI"],
            "importance_score": 3,
            "reason": "API 定价策略变化",
            "actionable": "评估成本影响",
            "hidden_signal": "大模型 API 价格战进入新阶段",
            "content_source": "summary_only",
            "signal_type": 8,
            "evidence_type": 3,
            "evidence_strength": 3,
            "novelty_score": 3,
            "impact_horizon": 2,
            "audience": [2],
            "market_stage": 4,
            "confidence": 3,
            "entities": ["OpenAI"],
            "cluster_hint": "llm-pricing-war",
            "watch_keywords": ["pricing", "api", "cost"],
        },
    ]


@pytest.fixture
def sample_global_insights():
    """今日全局洞察数据样本"""
    return [
        {
            "generated_at": datetime(2026, 5, 9, 8, 0, tzinfo=timezone.utc),
            "data": {
                "trends": [
                    {"text": "多模态推理成为竞争焦点", "source_urls": ["https://..."], "source_titles": ["..."]}
                ],
                "weak_signals": [
                    {"text": "开源小模型边缘部署加速", "source_urls": [], "source_titles": []}
                ],
                "daily_advices": [
                    {"text": "关注 multimodal reasoning benchmark", "source_urls": [], "source_titles": []}
                ],
                "key_topics": ["AI Agent", "多模态"],
                "confidence_level": "high",
            },
        },
        {
            "generated_at": datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc),
            "data": {
                "trends": [
                    {"text": "Agent 工具链标准化趋势", "source_urls": [], "source_titles": []}
                ],
                "weak_signals": [],
                "daily_advices": [],
                "key_topics": ["Agent Tooling"],
                "confidence_level": "medium",
            },
        },
    ]


@pytest.fixture
def sample_clusters():
    """信号簇数据样本"""
    return [
        {
            "id": 1,
            "label": "Claude 模型能力迭代",
            "normalized_label": "claude-model-capability",
            "signal_type": 1,
            "status": "bursting",
            "summary": "Anthropic 持续推进 Claude 能力边界",
            "entities": ["Anthropic", "Claude"],
            "watch_keywords": ["claude", "model"],
            "first_seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "last_seen_at": datetime(2026, 5, 9, tzinfo=timezone.utc),
            "article_count": 18,
            "source_count": 3,
            "avg_importance": 4.2,
            "avg_evidence_strength": 4.0,
            "avg_novelty": 4.5,
            "avg_confidence": 4.3,
        },
        {
            "id": 2,
            "label": "Agent 运行时框架",
            "normalized_label": "agent-orchestration-framework",
            "signal_type": 2,
            "status": "warming",
            "summary": "Agent 编排框架生态持续演进",
            "entities": ["LangChain", "CrewAI"],
            "watch_keywords": ["agent", "framework"],
            "first_seen_at": datetime(2026, 5, 5, tzinfo=timezone.utc),
            "last_seen_at": datetime(2026, 5, 9, tzinfo=timezone.utc),
            "article_count": 12,
            "source_count": 2,
            "avg_importance": 3.8,
            "avg_evidence_strength": 3.5,
            "avg_novelty": 3.8,
            "avg_confidence": 3.6,
        },
    ]


@pytest.fixture
def sample_predictions():
    """预测数据样本"""
    return [
        {
            "id": 1,
            "prediction_title": "Agent 编排框架将在 Q2 进入主流采用",
            "target_end_at": datetime(2026, 5, 12, tzinfo=timezone.utc),
            "horizon_days": 7,
            "confidence": 4,
            "status": "pending",
            "signal_cluster_key": "2:agent-orchestration-framework",
        },
        {
            "id": 2,
            "prediction_title": "多模态小模型将进入手机端侧部署",
            "target_end_at": datetime(2026, 5, 20, tzinfo=timezone.utc),
            "horizon_days": 15,
            "confidence": 3,
            "status": "pending",
            "signal_cluster_key": "1:multimodal-edge-model",
        },
    ]


@pytest.fixture
def sample_reviews():
    """预测评审数据样本"""
    return [
        {
            "prediction_id": 3,
            "reviewed_at": datetime(2026, 5, 8, tzinfo=timezone.utc),
            "score": 4,
            "hit_level": "hit",
            "actual_observation": "多家厂商宣布端侧 7B 方案",
            "prediction_title": "端侧小模型将迎来爆发期",
        }
    ]


# ══════════════════════════════════════════════════════════
# 测试组 1: db_client - daily_reports 表 DDL 和 CRUD
# ══════════════════════════════════════════════════════════

class TestDailyReportsSchema:
    """Test daily_reports table DDL."""

    def test_ddl_contains_create_table(self):
        """DDL 应包含 CREATE TABLE IF NOT EXISTS daily_reports."""
        from rss2cubox.db_client import DAILY_REPORTS_SCHEMA
        assert "CREATE TABLE IF NOT EXISTS daily_reports" in DAILY_REPORTS_SCHEMA

    def test_ddl_has_required_columns(self):
        """DDL 应包含 id, report_date, generated_at, data 列"""
        from rss2cubox.db_client import DAILY_REPORTS_SCHEMA
        assert "id" in DAILY_REPORTS_SCHEMA.lower()
        assert "report_date" in DAILY_REPORTS_SCHEMA.lower()
        assert "generated_at" in DAILY_REPORTS_SCHEMA.lower()
        assert "data" in DAILY_REPORTS_SCHEMA.lower()

    def test_ddl_has_unique_constraint_on_report_date(self):
        """report_date 应有 UNIQUE 约束（同一天只存一份日报）"""
        from rss2cubox.db_client import DAILY_REPORTS_SCHEMA
        assert "UNIQUE" in DAILY_REPORTS_SCHEMA.upper()

    def test_ddl_has_index_on_report_date(self):
        """应有按 report_date DESC 的索引"""
        from rss2cubox.db_client import DAILY_REPORTS_SCHEMA
        assert "INDEX" in DAILY_REPORTS_SCHEMA.upper()
        assert "daily_reports" in DAILY_REPORTS_SCHEMA.lower()


class TestSaveDailyReport:
    """Test save_daily_report function."""

    def test_save_creates_table_first(self, mock_db_conn):
        """保存前应先执行 DDL 建表"""
        conn, cur = mock_db_conn
        payload = {
            "report_date": "2026-05-09",
            "generated_at": datetime(2026, 5, 9, 23, 59, tzinfo=timezone.utc).isoformat(),
            "summary": {"total_articles": 100},
            "trends": [],
            "weak_signals": [],
            "daily_advices": [],
        }

        with patch("rss2cubox.db_client.reports.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_daily_report
            save_daily_report(payload, db_url="postgresql://localhost/test")

            sql_calls = [c[0][0] for c in cur.execute.call_args_list]
            ddl_calls = [s for s in sql_calls if "daily_reports" in s.lower()]
            assert len(ddl_calls) > 0, "应先执行 DDL"

    def test_save_inserts_payload(self, mock_db_conn):
        """应 INSERT 报告数据"""
        conn, cur = mock_db_conn
        payload = {
            "report_date": "2026-05-09",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {},
            "trends": [{"text": "test"}],
            "weak_signals": [],
            "daily_advices": [],
        }

        with patch("rss2cubox.db_client.reports.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_daily_report
            result = save_daily_report(payload, db_url="postgresql://localhost/test")

            assert result is True
            # 验证有 INSERT 调用
            insert_calls = [c[0][0] for c in cur.execute.call_args_list if "INSERT" in c[0][0].upper()]
            assert len(insert_calls) > 0

    def test_save_commits_transaction(self, mock_db_conn):
        """写入后应 commit"""
        conn, cur = mock_db_conn
        payload = {"report_date": "2026-05-09", "generated_at": datetime.now(timezone.utc).isoformat(), "summary": {}, "trends": [], "weak_signals": [], "daily_advices": []}

        with patch("rss2cubox.db_client.reports.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_daily_report
            save_daily_report(payload, db_url="postgresql://localhost/test")
            conn.commit.assert_called_once()

    def test_save_returns_false_when_no_db_url(self):
        """无 DB URL 时返回 False"""
        with patch.dict(os.environ, {}, clear=True):
            # 清除环境变量确保没有 LOCAL_DB_URL
            pass
        from rss2cubox.db_client import save_daily_report
        result = save_daily_report({"report_date": "2026-05-09"}, db_url="")
        assert result is False

    def test_save_handles_json_serialization(self, mock_db_conn):
        """payload 应被 JSON 序列化后写入"""
        conn, cur = mock_db_conn
        payload = {
            "report_date": "2026-05-09",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {"total": 42},
            "trends": [{"text": "趋势", "source_urls": ["http://a"], "source_titles": ["A"]}],
            "weak_signals": [],
            "daily_advices": [],
        }

        with patch("rss2cubox.db_client.reports.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import save_daily_report
            save_daily_report(payload, db_url="postgresql://localhost/test")

            # 检查 INSERT 的参数包含 JSON 字符串（参数化查询用 tuple）
            insert_call = [c for c in cur.execute.call_args_list if "INSERT" in c[0][0].upper()][0]
            args = insert_call[0][1]  # 参数 tuple: (report_date, generated_at, data)
            assert isinstance(args[2], str)  # 第三个参数 (data) 应该是 JSON 字符串
            parsed = json.loads(args[2])
            assert parsed["summary"]["total"] == 42


class TestGetDailyReport:
    """Test get_daily_report function."""

    def test_get_by_date_queries_correctly(self, mock_db_conn):
        """应按 report_date 查询单条"""
        conn, cur = mock_db_conn
        # get_daily_report 只 SELECT data 列
        mock_row = (json.dumps({"report_date": "2026-05-09"}),)
        cur.fetchone.return_value = mock_row

        with patch("rss2cubox.db_client.reports.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_daily_report
            result = get_daily_report("2026-05-09", db_url="postgresql://localhost/test")

            assert result is not None
            assert result["report_date"] == "2026-05-09"

    def test_get_returns_none_when_not_found(self, mock_db_conn):
        """无数据时返回 None"""
        conn, cur = mock_db_conn
        cur.fetchone.return_value = None

        with patch("rss2cubox.db_client.reports.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_daily_report
            result = get_daily_report("2099-01-01", db_url="postgresql://localhost/test")
            assert result is None


class TestGetRecentReports:
    """Test get_recent_reports function."""

    def test_get_recent_orders_by_date_desc(self, mock_db_conn):
        """应按日期倒序排列"""
        conn, cur = mock_db_conn
        cur.fetchall.return_value = []

        with patch("rss2cubox.db_client.reports.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_recent_reports
            get_recent_reports(limit=10, db_url="postgresql://localhost/test")

            select_call = [c for c in cur.execute.call_args_list if "SELECT" in c[0][0].upper()][0]
            assert "DESC" in select_call[0][0].upper()

    def test_get_recent_respects_limit(self, mock_db_conn):
        """应使用 LIMIT 参数"""
        conn, cur = mock_db_conn
        cur.fetchall.return_value = []

        with patch("rss2cubox.db_client.reports.psycopg.connect", return_value=conn):
            from rss2cubox.db_client import get_recent_reports
            get_recent_reports(limit=5, db_url="postgresql://localhost/test")

            select_call = [c for c in cur.execute.call_args_list if "SELECT" in c[0][0].upper()][0]
            assert "LIMIT" in select_call[0][0].upper()


# ══════════════════════════════════════════════════════════
# 测试组 2: daily_report_agent - Schema 和配置
# ══════════════════════════════════════════════════════════

class TestDailyReportSchema:
    """Test output schema definition."""

    def test_schema_exists(self):
        """DAILY_REPORT_OUTPUT_SCHEMA 应存在"""
        from rss2cubox.daily_report_agent import DAILY_REPORT_OUTPUT_SCHEMA
        assert isinstance(DAILY_REPORT_OUTPUT_SCHEMA, dict)

    def test_schema_has_required_top_level_fields(self):
        """Schema 应包含顶层必需字段"""
        from rss2cubox.daily_report_agent import DAILY_REPORT_OUTPUT_SCHEMA
        props = DAILY_REPORT_OUTPUT_SCHEMA["properties"]
        required = set(DAILY_REPORT_OUTPUT_SCHEMA.get("required", []))

        for field in ("report_date", "generated_at", "summary", "trends", "weak_signals", "daily_advices"):
            assert field in props, f"Schema 缺少 {field} 字段"

    def test_schema_summary_structure(self):
        """summary 应包含统计概览子字段"""
        from rss2cubox.daily_report_agent import DAILY_REPORT_OUTPUT_SCHEMA
        summary_props = DAILY_REPORT_OUTPUT_SCHEMA["properties"]["summary"]["properties"]

        for field in ("total_articles", "high_importance_count", "top_feeds"):
            assert field in summary_props, f"summary 缺少 {field}"

    def test_schema_trend_items_have_source_attribution(self):
        """trends/weak_signals/daily_advices 条目应带溯源字段"""
        from rss2cubox.daily_report_agent import DAILY_REPORT_OUTPUT_SCHEMA

        for field in ("trends", "weak_signals", "daily_advices"):
            item_props = DAILY_REPORT_OUTPUT_SCHEMA["properties"][field]["items"]["properties"]
            assert "source_urls" in item_props, f"{field} items 缺少 source_urls"
            assert "source_titles" in item_props, f"{field} items 缺少 source_titles"

    def test_schema_has_enhanced_fields(self):
        """Schema 应包含日报增强字段"""
        from rss2cubox.daily_report_agent import DAILY_REPORT_OUTPUT_SCHEMA
        props = DAILY_REPORT_OUTPUT_SCHEMA["properties"]

        for field in ("top_articles", "cluster_evolution", "prediction_status", "key_topics", "confidence_level"):
            assert field in props, f"Schema 缺少增强字段 {field}"


class TestDailyReportConfig:
    """Test configuration constants."""

    def test_config_defaults_exist(self):
        """默认配置常量应存在且有合理值"""
        from rss2cubox.daily_report_agent import (
            DAILY_REPORT_ENABLED,
            DAILY_REPORT_INTERVAL_HOURS,
            DAILY_REPORT_MAX_BUDGET_USD,
        )

        assert isinstance(DAILY_REPORT_ENABLED, bool)
        assert DAILY_REPORT_INTERVAL_HOURS >= 1
        assert DAILY_REPORT_MAX_BUDGET_USD is None or DAILY_REPORT_MAX_BUDGET_USD > 0

    def test_enabled_can_be_disabled_via_env(self):
        """可通过环境变量禁用"""
        import os
        with patch.dict(os.environ, {"DAILY_REPORT_ENABLED": "false"}):
            # reload module to pick up new env
            import importlib
            import rss2cubox.daily_report_agent
            importlib.reload(rss2cubox.daily_report_agent)
            assert rss2cubox.daily_report_agent.DAILY_REPORT_ENABLED is False


# ══════════════════════════════════════════════════════════
# 测试组 3: _collect_day_data 数据聚合逻辑
# ══════════════════════════════════════════════════════════

class TestCollectDayData:
    """Test day data aggregation from DB queries."""

    @patch("rss2cubox.db_client.get_recent_prediction_reviews")
    @patch("rss2cubox.db_client.get_due_trend_predictions")
    @patch("rss2cubox.db_client.get_existing_signal_clusters")
    @patch("rss2cubox.db_client.get_all_global_insights")
    @patch("rss2cubox.db_client.get_articles_by_date")
    def test_collect_aggregates_all_sources(
        self,
        mock_articles,
        mock_insights,
        mock_clusters,
        mock_predictions,
        mock_reviews,
        sample_today_articles,
        sample_global_insights,
        sample_clusters,
        sample_predictions,
        sample_reviews,
    ):
        """应从所有 4 个数据源聚合数据"""
        mock_articles.return_value = sample_today_articles
        mock_insights.return_value = sample_global_insights
        mock_clusters.return_value = sample_clusters
        mock_predictions.return_value = sample_predictions
        mock_reviews.return_value = sample_reviews

        from rss2cubox.daily_report_agent import _collect_day_data
        result = _collect_day_data("2026-05-09")

        assert "today_articles_summary" in result
        assert "today_global_insights" in result
        assert "cluster_snapshot" in result
        assert "prediction_status" in result
        assert result["report_date"] == "2026-05-09"

    @patch("rss2cubox.db_client.get_articles_by_date")
    def test_article_summary_counts_high_importance(
        self, mock_articles, sample_today_articles
    ):
        """应正确统计高重要性文章数量"""
        mock_articles.return_value = sample_today_articles

        from rss2cubox.daily_report_agent import _collect_day_data
        result = _collect_day_data("2026-05-09")

        summary = result["today_articles_summary"]
        assert summary["total_articles"] == 3
        assert summary["high_importance_count"] == 2  # score >= 4 的有 2 条

    @patch("rss2cubox.db_client.get_articles_by_date")
    def test_article_summary_includes_top_articles(
        self, mock_articles, sample_today_articles
    ):
        """应包含按重要性排序的 TOP 文章"""
        mock_articles.return_value = sample_today_articles

        from rss2cubox.daily_report_agent import _collect_day_data
        result = _collect_day_data("2026-05-09")

        top = result["today_articles_summary"]["top_articles"]
        assert len(top) > 0
        # 验证按 importance_score 降序
        scores = [a["importance_score"] for a in top]
        assert scores == sorted(scores, reverse=True)

    @patch("rss2cubox.db_client.get_articles_by_date")
    def test_handles_empty_articles(self, mock_articles):
        """空文章列表不应报错"""
        mock_articles.return_value = []

        from rss2cubox.daily_report_agent import _collect_day_data
        result = _collect_day_data("2026-05-09")

        assert result["today_articles_summary"]["total_articles"] == 0
        assert result["today_articles_summary"]["high_importance_count"] == 0

    @patch("rss2cubox.db_client.get_all_global_insights")
    def test_insights_preserves_original_data(self, mock_insights, sample_global_insights):
        """应保留原始 insights 数据不做裁剪"""
        mock_insights.return_value = sample_global_insights

        from rss2cubox.daily_report_agent import _collect_day_data
        result = _collect_day_data("2026-05-09")

        insights = result["today_global_insights"]
        assert len(insights) == 2
        assert "trends" in insights[0]["data"]

    @patch("rss2cubox.db_client.get_existing_signal_clusters")
    def test_cluster_snapshot_includes_status(self, mock_clusters, sample_clusters):
        """簇快照应包含状态信息"""
        mock_clusters.return_value = sample_clusters

        from rss2cubox.daily_report_agent import _collect_day_data
        result = _collect_day_data("2026-05-09")

        clusters = result["cluster_snapshot"]["active_clusters"]
        assert len(clusters) == 2
        assert clusters[0]["status"] == "bursting"
        assert clusters[1]["status"] == "warming"

    @patch("rss2cubox.db_client.get_fulltexts_by_eids")
    @patch("rss2cubox.db_client.get_articles_by_date")
    def test_top_articles_includes_fulltext(self, mock_articles, mock_ft, sample_today_articles):
        """top_articles 应包含 full_text 字段（从 DB 批量获取）"""
        mock_articles.return_value = sample_today_articles
        mock_ft.return_value = {"art_001": "这是 Claude 4.7 的完整正文内容...", "art_002": ""}

        from rss2cubox.daily_report_agent import _collect_day_data
        result = _collect_day_data("2026-05-09")

        top = result["today_articles_summary"]["top_articles"]
        assert len(top) >= 2
        # art_001 有全文
        art_001 = next((a for a in top if a["title"] == "Claude 4.7 发布：最强推理模型"), None)
        assert art_001 is not None
        assert art_001["full_text"] == "这是 Claude 4.7 的完整正文内容..."
        # art_002 无全文（DB 中没有）
        art_002 = next((a for a in top if a["title"] == "Agent 运行时框架对比评测"), None)
        assert art_002 is not None
        assert art_002["full_text"] == ""

    @patch("rss2cubox.db_client.get_fulltexts_by_eids")
    @patch("rss2cubox.db_client.get_articles_by_date")
    def test_top_articles_empty_when_no_fulltexts(self, mock_articles, mock_ft, sample_today_articles):
        """无全文数据时 full_text 为空字符串"""
        mock_articles.return_value = sample_today_articles
        mock_ft.return_value = {}

        from rss2cubox.daily_report_agent import _collect_day_data
        result = _collect_day_data("2026-05-09")

        top = result["today_articles_summary"]["top_articles"]
        for a in top:
            assert a.get("full_text") == ""


# ══════════════════════════════════════════════════════════
# 测试组 4: System Prompt 验证
# ══════════════════════════════════════════════════════════

class TestDailyReportSystemPrompt:
    """Test system prompt content."""

    def test_prompt_contains_role_definition(self):
        """System prompt 应定义角色"""
        from rss2cubox.daily_report_agent import SYSTEM_PROMPT
        assert len(SYSTEM_PROMPT) > 50

    def test_prompt_mentions_read_webpage_tool(self):
        """Prompt 应提及 read_webpage 工具能力"""
        from rss2cubox.daily_report_agent import SYSTEM_PROMPT
        assert "read_webpage" in SYSTEM_PROMPT or "webpage" in SYSTEM_PROMPT.lower()

    def test_prompt_requires_source_attribution(self):
        """Prompt 应要求溯源标注"""
        from rss2cubox.daily_report_agent import SYSTEM_PROMPT
        assert "source_urls" in SYSTEM_PROMPT or "溯源" in SYSTEM_PROMPT

    def test_output_format_in_prompt_context(self):
        """Prompt 应提及结构化输出要求"""
        from rss2cubox.daily_report_agent import SYSTEM_PROMPT
        assert "JSON" in SYSTEM_PROMPT or "结构化" in SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════
# 测试组 5: run_daily_report 入口函数
# ══════════════════════════════════════════════════════════

class TestRunDailyReport:
    """Test main entry point."""

    def test_run_returns_none_when_disabled(self):
        """禁用时应返回 None"""
        with patch("rss2cubox.daily_report_agent.DAILY_REPORT_ENABLED", False):
            from rss2cubox.daily_report_agent import run_daily_report
            result = run_daily_report()
            assert result is None

    @patch("rss2cubox.daily_report_agent._run_agent")
    @patch("rss2cubox.daily_report_agent._collect_day_data")
    def test_run_calls_collect_then_agent(self, mock_collect, mock_agent):
        """应先收集数据再调用 Agent"""
        mock_collect.return_value = {
            "report_date": "2026-05-09",
            "today_articles_summary": {"total_articles": 10, "high_importance_count": 3},
            "today_global_insights": [{"data": {}}],
            "cluster_snapshot": {"active_clusters": []},
            "prediction_status": {},
        }
        mock_agent.return_value = {
            "report_date": "2026-05-09",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {},
            "trends": [],
            "weak_signals": [],
            "daily_advices": [],
        }

        with patch("rss2cubox.daily_report_agent.DAILY_REPORT_ENABLED", True):
            from rss2cubox.daily_report_agent import run_daily_report
            result = run_daily_report()

        mock_collect.assert_called_once()
        mock_agent.assert_called_once()
        assert result is not None
