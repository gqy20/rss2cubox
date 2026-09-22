"""科技链路 Jev 预筛（影子模式）单测：全 mock，不调外部 API、不连库。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from rss2cubox import tech_triage


def _env(monkeypatch, enabled="true", base="https://api.typesafe.ai", key="k"):
    monkeypatch.setenv("TECH_TRIAGE_ENABLED", enabled)
    monkeypatch.setenv("JEV_BASE_URL", base)
    monkeypatch.setenv("JEV_API_KEY", key)


def _fake_jev_response(imp=3.0, rel=0.9):
    return {
        "model": "jev-test",
        "answers": {
            "importance": {"type": "score", "score": imp, "probabilities": {}},
            "relevance": {"type": "noul", "noul": rel},
        },
        "usage": {"input_tokens": 700, "output_tokens": 136},
    }


class TestEnabled:
    def test_disabled_by_flag(self, monkeypatch):
        _env(monkeypatch, enabled="false")
        assert not tech_triage.tech_triage_enabled()

    def test_disabled_without_jev(self, monkeypatch):
        monkeypatch.delenv("JEV_BASE_URL", raising=False)
        monkeypatch.delenv("JEV_API_KEY", raising=False)
        monkeypatch.setenv("TECH_TRIAGE_ENABLED", "true")
        assert not tech_triage.tech_triage_enabled()


class _FakeCur:
    def __init__(self, saved):
        self._saved = saved

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def executemany(self, sql, rows):
        self._saved["rows"] = list(rows)


class _FakeConn:
    def __init__(self, saved):
        self._saved = saved

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, ddl):
        pass

    def cursor(self):
        return _FakeCur(self._saved)

    def commit(self):
        pass


class TestScoreCandidates:
    def _candidates(self, n=3):
        return [
            {"eid": f"e{i}", "title": f"标题{i}", "summary": f"摘要{i}"}
            for i in range(n)
        ]

    def test_scores_persisted_and_counted(self, monkeypatch):
        _env(monkeypatch)
        saved = {}
        with (
            patch("rss2cubox.tech_triage.jev_systemone", side_effect=lambda *a, **k: _fake_jev_response()),
            patch("rss2cubox.tech_triage.psycopg.connect", return_value=_FakeConn(saved)),
        ):
            n = tech_triage.score_candidates(
                self._candidates(), run_id="r1", db_url="postgres://x",
            )
        assert n == 3
        assert len(saved["rows"]) == 3
        assert saved["rows"][0]["importance"] == 3.0
        assert saved["rows"][0]["relevance"] == 0.9

    def test_item_failure_skipped_not_fatal(self, monkeypatch):
        _env(monkeypatch)
        saved = {}
        calls = {"i": 0}

        def flaky(state, questions, **kw):
            calls["i"] += 1
            return _fake_jev_response() if calls["i"] == 1 else None

        with (
            patch("rss2cubox.tech_triage.jev_systemone", side_effect=flaky),
            patch("rss2cubox.tech_triage.psycopg.connect", return_value=_FakeConn(saved)),
        ):
            n = tech_triage.score_candidates(
                self._candidates(), run_id="r1", db_url="postgres://x",
            )
        assert n == 1
        assert len(saved["rows"]) == 1

    def test_no_db_url_is_noop(self, monkeypatch):
        _env(monkeypatch)
        with patch("rss2cubox.tech_triage.jev_systemone") as m:
            assert tech_triage.score_candidates(self._candidates(), run_id="r", db_url=None) == 0
        m.assert_not_called()

    def test_state_includes_summary_capped(self):
        item = {"eid": "e", "title": "T", "summary": "x" * 900}
        state = tech_triage._state_for(item)
        assert state.startswith("标题：T")
        assert len(state) < 600
