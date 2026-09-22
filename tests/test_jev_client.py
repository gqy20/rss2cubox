"""Jev 客户端与 lineage 交叉校验。

不真实调用外部 API：requests.post 全部 mock，验证协议形状、未配置跳过、
失败静默、以及 criteria 与 POLICY_LINEAGES 的同步。
"""
from __future__ import annotations

import os
from unittest.mock import patch

from rss2cubox.jev_client import jev_configured, jev_systemone
from rss2cubox.policy.enrich_agent import LINEAGE_CHOICE_CRITERIA, POLICY_LINEAGES, _jev_lineage_check


def _set_env(monkeypatch, base="https://api.typesafe.ai", key="k-test"):
    monkeypatch.setenv("JEV_BASE_URL", base)
    monkeypatch.setenv("JEV_API_KEY", key)


class TestClient:
    def test_unconfigured_returns_none(self, monkeypatch):
        monkeypatch.delenv("JEV_BASE_URL", raising=False)
        monkeypatch.delenv("JEV_API_KEY", raising=False)
        assert not jev_configured()
        assert jev_systemone("标题", {"q": {"type": "noul", "instructions": "x"}}) is None

    def test_posts_systemone_shape_and_parses_response(self, monkeypatch):
        _set_env(monkeypatch)
        sent = {}

        class Resp:
            status_code = 200
            text = ""

            def json(self):
                return {
                    "model": "jev-test",
                    "answers": {"lineage": {"type": "choice", "choice": "人工智能+行动", "confidence": 0.9, "probabilities": {}}},
                    "usage": {"input_tokens": 700, "output_tokens": 136},
                }

        def fake_post(url, json=None, headers=None, timeout=None):
            sent.update(url=url, json=json, headers=headers)
            return Resp()

        with patch("rss2cubox.jev_client.requests.post", side_effect=fake_post):
            data = jev_systemone("标题：X", {"lineage": {"type": "choice", "instructions": "i", "criteria": {}}})

        assert sent["url"] == "https://api.typesafe.ai/v1/systemone"
        assert sent["json"]["model"] == "jev-latest"
        assert sent["json"]["state"] == "标题：X"
        assert data["answers"]["lineage"]["choice"] == "人工智能+行动"

    def test_non_200_returns_none_and_logs(self, monkeypatch):
        _set_env(monkeypatch)
        logs = []

        class Resp:
            status_code = 503
            text = "unavailable"

            def json(self):
                return {}

        with patch("rss2cubox.jev_client.requests.post", return_value=Resp()):
            out = jev_systemone("s", {}, log_event=lambda lvl, ev, **kw: logs.append((lvl, ev)))

        assert out is None
        assert logs and logs[0][1] == "jev_call_failed"

    def test_request_exception_returns_none(self, monkeypatch):
        import requests as _r

        _set_env(monkeypatch)
        with patch("rss2cubox.jev_client.requests.post", side_effect=_r.exceptions.Timeout("t")):
            assert jev_systemone("s", {}) is None


class TestLineageCheck:
    def test_criteria_keys_match_lineage_constants(self):
        assert list(LINEAGE_CHOICE_CRITERIA)[: len(POLICY_LINEAGES)] == POLICY_LINEAGES
        assert "不属于任何主线" in LINEAGE_CHOICE_CRITERIA

    def _check(self, monkeypatch, deep, jev_pick):
        _set_env(monkeypatch)
        doc = {"id": "d1", "title": "某政策"}
        enriched = {"summary": "摘要", "policy_lineage": deep}

        def fake_call(state, questions, **kw):
            return {"model": "jev-test", "answers": {"lineage": {"type": "choice", "choice": jev_pick, "confidence": 0.8}}, "usage": {}}

        with patch("rss2cubox.jev_client.jev_systemone", side_effect=fake_call):
            _jev_lineage_check(doc, enriched, log_event=None)
        return enriched["enrich_meta"]["jev_lineage"]

    def test_agree_when_same_pick(self, monkeypatch):
        m = self._check(monkeypatch, "人工智能+行动", "人工智能+行动")
        assert m["agree"] is True

    def test_disagreement_recorded_not_fatal(self, monkeypatch):
        m = self._check(monkeypatch, "十五五规划体系", "不属于任何主线")
        assert m["agree"] is False
        assert m["choice"] == "不属于任何主线"

    def test_deep_none_and_jev_none_line_counts_agree(self, monkeypatch):
        m = self._check(monkeypatch, None, "不属于任何主线")
        assert m["agree"] is True

    def test_jev_unavailable_leaves_meta_untouched(self, monkeypatch):
        _set_env(monkeypatch)
        enriched = {"summary": "s", "policy_lineage": "AI安全与监管"}
        with patch("rss2cubox.jev_client.jev_systemone", return_value=None):
            _jev_lineage_check({"id": "d", "title": "t"}, enriched, log_event=None)
        assert "enrich_meta" not in enriched or "jev_lineage" not in enriched.get("enrich_meta", {})
