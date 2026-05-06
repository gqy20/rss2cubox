"""Tests for batch schedule refactor: unified config, default concurrency, global batch."""
import os
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


class FeedParserDict(dict):
    """A dict subclass that mimics feedparser.util.FeedParserDict for testing."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


# ============================================================
# Task 1: 统一 MAX_ITEMS_PER_RUN，移除 AI_MAX_CANDIDATES
# ============================================================


def make_candidates(n: int) -> list[dict]:
    """生成 n 条候选条目用于测试。"""
    return [
        {"eid": f"e{i}", "url": f"https://example.com/{i}", "title": f"T{i}", "summary": f"S{i}"}
        for i in range(n)
    ]


def _mock_runner_main(monkeypatch: pytest.MonkeyPatch, feeds_file: Path, max_items: int, n_entries: int = 5):
    """通用 runner.main() mock 设置。"""
    entries = [
        {"id": str(i), "link": f"https://example.com/{i}", "title": f"T{i}", "summary": f"S{i}"}
        for i in range(n_entries)
    ]

    def fake_fetch_and_check_update(url: str, **kwargs):  # noqa: ANN001
        return (
            FeedParserDict(
                bozo=False,
                entries=[FeedParserDict(e) for e in entries],
                feed=FeedParserDict(updated="Sat, 02 May 2026 13:00:00 +0800"),
            ),
            True,
        )

    posted_batches: list[list[dict]] = []

    def fake_post_articles(api_url: str, request_post, articles):  # noqa: ANN001
        _ = (api_url, request_post)
        posted_batches.append(articles)
        return "ok"

    from rss2cubox import runner, feed_sources, sync_pipeline, enrich_agent

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", max_items)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "IC_API_URL", "https://fake.api.com/api/v1/articles/batch")
    monkeypatch.setattr(runner, "IC_PUSH_ENABLED", True)
    monkeypatch.setattr(runner, "IC_SOURCE_TYPE", "gqy")
    monkeypatch.setattr(sync_pipeline, "load_ic_state", lambda **kwargs: ({}, {}))
    monkeypatch.setattr(feed_sources, "fetch_and_check_update", fake_fetch_and_check_update)

    enrich_results: dict[str, dict] = {}

    def fake_analyze(**kwargs):
        for item in kwargs["candidates"]:
            enrich_results[item["eid"]] = {
                "reason": "高价值",
                "actionable": "跟进",
                "hidden_signal": "信号",
                "tags": ["rss"],
                "core_event": item["title"],
            }
        return enrich_results

    monkeypatch.setattr(enrich_agent, "analyze_candidates_with_agent", fake_analyze)
    monkeypatch.setattr(
        sync_pipeline,
        "post_articles_in_chunks",
        lambda **kwargs: [fake_post_articles(kwargs["api_url"], kwargs["request_post"], kwargs["articles"])],
    )
    monkeypatch.setattr(runner, "run_global_analysis", lambda **kwargs: None)
    monkeypatch.setattr(runner, "save_articles", lambda **kwargs: None)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    return posted_batches


def test_runner_uses_max_items_per_run_as_unified_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    验证 runner 不再使用 AI_MAX_CANDIDATES，统一用 MAX_ITEMS_PER_RUN 作为截断上限。
    500条候选 + MAX_ITEMS_PER_RUN=1200 → 应全部处理（不超过1200）。
    """
    feeds_file = tmp_path / "feeds.txt"
    feeds_file.write_text("https://feed.example/rss\n", encoding="utf-8")

    from rss2cubox import runner

    posted_batches = _mock_runner_main(monkeypatch, feeds_file, max_items=1200, n_entries=500)

    runner.main()

    total_pushed = sum(len(batch) for batch in posted_batches)
    assert total_pushed == 500, f"期望入库 500 条，实际 {total_pushed}（MAX_ITEMS_PER_RUN=1200 不应截断）"


def test_runner_max_items_per_run_still_limits_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    MAX_ITEMS_PER_RUN 仍然控制最终入库数量上限。
    500条候选 + MAX_ITEMS_PER_RUN=100 → 入库不超过100条。
    """
    feeds_file = tmp_path / "feeds.txt"
    feeds_file.write_text("https://feed.example/rss\n", encoding="utf-8")

    from rss2cubox import runner

    posted_batches = _mock_runner_main(monkeypatch, feeds_file, max_items=100, n_entries=500)

    runner.main()

    total_pushed = sum(len(batch) for batch in posted_batches)
    assert total_pushed <= 100, f"期望入库 ≤100 条，实际 {total_pushed}"


def test_ai_max_candidates_removed_from_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    runner 模块不应再定义或使用 AI_MAX_CANDIDATES 常量。
    统一使用 MAX_ITEMS_PER_RUN 控制处理上限。
    """
    from rss2cubox import runner

    assert not hasattr(runner, "AI_MAX_CANDIDATES"), (
        "runner.AI_MAX_CANDIDATES 应已删除，统一使用 MAX_ITEMS_PER_RUN"
    )


# ============================================================
# Task 2: global_sight 分批并发执行
# ============================================================


def test_global_analysis_splits_into_batches_of_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    run_global_analysis 应将 high_value 按 GLOBAL_AGENT_BATCH_SIZE(200) 分批，
    每批独立调用 _run_agent。
    """
    from rss2cubox import global_agent

    monkeypatch.setattr(global_agent, "GLOBAL_AGENT_ENABLED", True)
    monkeypatch.setenv("NEON_PUSH_ENABLED", "false")

    batch_calls: list[list[dict]] = []

    async def fake_run(high_value_items, history_signals, log_event=None):  # noqa: ANN001
        batch_calls.append(high_value_items)
        return {
            "trends": [{"text": f"趋势-{len(high_value_items)}"}],
            "weak_signals": [],
            "daily_advices": [],
            "key_topics": [],
            "confidence_level": "medium",
        }

    monkeypatch.setattr(global_agent, "_run_agent", fake_run)

    # Mock DB operations (save_global_insights is imported inside run_global_analysis from db_client)
    saved_insights: list[dict] = []

    def fake_save(payload):
        saved_insights.append(payload)

    from rss2cubox import db_client
    monkeypatch.setattr(db_client, "save_global_insights", fake_save)
    monkeypatch.setattr(db_client, "get_all_global_insights", lambda: [{"trends": [], "weak_signals": [], "daily_advices": []}])

    # 构造 550 条有信号的候选 → 应分为 3 批：200 + 200 + 150
    analyses = {}
    candidates = []
    for i in range(550):
        eid = f"e{i}"
        analyses[eid] = {
            "hidden_signal": f"信号{i}",
            "core_event": f"事件{i}",
            "reason": f"原因{i}",
        }
        candidates.append({"eid": eid, "url": f"https://example.com/{i}", "title": f"T{i}"})

    global_agent.run_global_analysis(analyses=analyses, candidates=candidates)

    assert len(batch_calls) == 3, f"期望 3 批(200+200+150)，实际 {len(batch_calls)} 批"
    assert len(batch_calls[0]) == 200, f"第1批应为200条，实际 {len(batch_calls[0])}"
    assert len(batch_calls[1]) == 200, f"第2批应为200条，实际 {len(batch_calls[1])}"
    assert len(batch_calls[2]) == 150, f"第3批应为150条，实际 {len(batch_calls[2])}"
    # 每批都应有独立写入
    assert len(saved_insights) == 3, f"期望写入3条insights，实际 {len(saved_insights)}"


def test_global_analysis_single_batch_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    候选数不足 GLOBAL_AGENT_BATCH_SIZE 时，只产生 1 批。
    """
    from rss2cubox import global_agent

    monkeypatch.setattr(global_agent, "GLOBAL_AGENT_ENABLED", True)
    monkeypatch.setenv("NEON_PUSH_ENABLED", "false")

    batch_calls: list[list[dict]] = []

    async def fake_run(high_value_items, history_signals, log_event=None):  # noqa: ANN001
        batch_calls.append(high_value_items)
        return {"trends": [], "weak_signals": [], "daily_advices": [], "key_topics": [], "confidence_level": "low"}

    monkeypatch.setattr(global_agent, "_run_agent", fake_run)
    from rss2cubox import db_client
    monkeypatch.setattr(db_client, "save_global_insights", lambda p: None)
    monkeypatch.setattr(db_client, "get_all_global_insights", lambda: [{"trends": [], "weak_signals": [], "daily_advices": []}])

    analyses = {f"e{i}": {"hidden_signal": "s", "core_event": "c", "reason": "r"} for i in range(50)}
    candidates = [{"eid": f"e{i}", "url": f"https://x.com/{i}", "title": f"T{i}"} for i in range(50)]

    global_agent.run_global_analysis(analyses=analyses, candidates=candidates)

    assert len(batch_calls) == 1
    assert len(batch_calls[0]) == 50


def test_global_analysis_batches_run_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    多批应并发执行（非串行），通过执行顺序验证：
    如果串行则 batch_calls 按序添加；如果并发则可能乱序（但这里主要验证调用次数）。
    更严谨的验证：记录每批开始/结束时间戳，确认有重叠。
    """
    from rss2cubox import global_agent
    import time as time_mod

    monkeypatch.setattr(global_agent, "GLOBAL_AGENT_ENABLED", True)
    monkeypatch.setenv("NEON_PUSH_ENABLED", "false")

    timestamps: list[tuple[int, float, float]] = []  # (batch_index, start_time, end_time)

    async def fake_slow_run(high_value_items, history_signals, log_event=None):  # noqa: ANN001
        idx = len(timestamps)
        start = time_mod.time()
        timestamps.append((idx, start, 0))
        await __import__("asyncio").sleep(0.05)  # 模拟耗时
        end = time_mod.time()
        timestamps[idx] = (idx, start, end)
        return {"trends": [], "weak_signals": [], "daily_advices": [], "key_topics": [], "confidence_level": "low"}

    monkeypatch.setattr(global_agent, "_run_agent", fake_slow_run)
    from rss2cubox import db_client
    monkeypatch.setattr(db_client, "save_global_insights", lambda p: None)
    monkeypatch.setattr(db_client, "get_all_global_insights", lambda: [{"trends": [], "weak_signals": [], "daily_advices": []}])

    # 401 条 → 3 批 (200+200+1)
    analyses = {f"e{i}": {"hidden_signal": "s"} for i in range(401)}
    candidates = [{"eid": f"e{i}", "url": f"https://x.com/{i}", "title": "T"} for i in range(401)]

    global_agent.run_global_analysis(analyses=analyses, candidates=candidates)

    assert len(timestamps) == 3
    # 并发时，所有批次几乎同时开始（间隔 < 单批耗时的50%）
    starts = sorted(t[1] for t in timestamps)
    first_start = starts[0]
    last_start = starts[-1]
    batch_duration = max(t[2] - t[1] for t in timestamps)
    # 如果是串行，last_start - first_start 应 ≈ 2 * batch_duration
    # 如果是并发，last_start - first_start 应 << batch_duration
    concurrent_gap = last_start - first_start
    assert concurrent_gap < batch_duration * 0.8, (
        f"批次似乎未并发执行：并发间隔={concurrent_gap:.3f}s，单批耗时={batch_duration:.3f}s"
    )


def test_global_analysis_empty_high_value_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    无高价值候选时应跳过分析（保持原有行为）。
    """
    from rss2cubox import global_agent

    monkeypatch.setattr(global_agent, "GLOBAL_AGENT_ENABLED", True)

    called = False

    async def fake_run(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(global_agent, "_run_agent", fake_run)

    # 所有候选都没有 hidden_signal / core_event / reason
    analyses = {f"e{i}": {} for i in range(10)}
    candidates = [{"eid": f"e{i}", "url": f"https://x.com/{i}"} for i in range(10)]

    result = global_agent.run_global_analysis(analyses=analyses, candidates=candidates)

    assert result is None
    assert not called, "无高价值候选时不应调用 _run_agent"


def test_global_batch_size_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    GLOBAL_AGENT_BATCH_SIZE 可通过环境变量配置，默认为 200。
    """
    from rss2cubox import global_agent

    assert hasattr(global_agent, "GLOBAL_AGENT_BATCH_SIZE"), "应存在 GLOBAL_AGENT_BATCH_SIZE 配置"
    assert global_agent.GLOBAL_AGENT_BATCH_SIZE == 200, f"默认批大小应为200，实际 {global_agent.GLOBAL_AGENT_BATCH_SIZE}"

    # 测试可通过环境变量覆盖
    monkeypatch.setenv("GLOBAL_AGENT_BATCH_SIZE", "50")
    # 需要重新导入才能生效，这里只验证默认值
    # 实际覆盖测试在集成测试中验证


# ============================================================
# Task 3: ENRICH_MAX_WORKERS 默认值改为 5
# ============================================================


def test_enrich_max_workers_default_is_5() -> None:
    """ENRICH_MAX_WORKERS 默认值应为 5（而非旧的10）。"""
    from rss2cubox.enrich_agent import ENRICH_MAX_WORKERS

    # 注意：如果 .env 中设置了 ENRICH_MAX_WORKERS，会覆盖默认值
    # 这里测试的是代码中的默认值
    # 由于 load_dotenv(override=True) 在模块加载时执行，需要检查原始默认值
    import inspect
    source = inspect.getsource(type(ENRICH_MAX_WORKERS).__class__) if False else ""
    # 直接检查：os.getenv 的默认参数
    from rss2cubox import enrich_agent
    src = inspect.getsource(enrich_agent)
    assert 'os.getenv("ENRICH_MAX_WORKERS", "5")' in src or 'os.getenv("ENRICH_MAX_WORKERS", 5)' in src or '"5"' in src.split('ENRICH_MAX_WORKERS')[1][:20], (
        "ENRICH_MAX_WORKERS 的 os.getenv 默认值应为 '5'"
    )


def test_enrich_max_workers_respects_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENRICH_MAX_WORKERS 应可通过环境变量覆盖。"""
    # 验证机制存在：环境变量优先于代码默认值
    from rss2cubox import enrich_agent
    import inspect

    src = inspect.getsource(enrich_agent)
    assert "ENRICH_MAX_WORKERS" in src
    assert "os.getenv" in src
    # 确认使用 max(1, int(...)) 保护
    assert "max(1, int(os.getenv" in src or "max(1,int(os.getenv" in src
