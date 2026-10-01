"""Congress 适配器单测：全 mock，不调外部 API、不连库。"""
from __future__ import annotations

from unittest.mock import patch

from rss2cubox import congress_fetcher


def _bill(n: int, title: str, action: str = "Introduced") -> dict:
    return {
        "type": "S",
        "number": n,
        "title": title,
        "url": f"/v3/bill/119th-congress/s/{n}",
        "latestAction": {"actionDate": "2026-09-28", "text": action},
    }


class TestFilter:
    def test_ai_titles_kept(self):
        bills = [
            _bill(1, "A bill to establish the Artificial Intelligence Safety Bureau"),
            _bill(2, "Wildland Firefighter Health and Safety Act"),
            _bill(3, "Deepfake accountability amendments"),
            _bill(4, "Semiconductor supply chain review"),
        ]
        fake = {"bills": bills}
        with (
            patch.object(congress_fetcher.requests, "get") as get,
            patch.dict("os.environ", {"CONGRESS_API_KEY": "k"}),
        ):
            get.return_value.status_code = 200
            get.return_value.json.return_value = fake
            get.return_value.raise_for_status.return_value = None
            out = congress_fetcher.fetch_ai_bills()
        assert [c["source_article_id"] for c in out] == ["S-1", "S-3", "S-4"]

    def test_word_boundary_ai(self):
        # " ai " 词边界：标题含 "aim"/"maintain" 不应命中
        bills = [_bill(1, "Maintaining harbor infrastructure")]
        with (
            patch.object(congress_fetcher.requests, "get") as get,
            patch.dict("os.environ", {"CONGRESS_API_KEY": "k"}),
        ):
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"bills": bills}
            get.return_value.raise_for_status.return_value = None
            assert congress_fetcher.fetch_ai_bills() == []

    def test_no_key_returns_empty(self):
        with patch.dict("os.environ", {"CONGRESS_API_KEY": ""}):
            assert congress_fetcher.fetch_ai_bills() == []

    def test_candidate_shape(self):
        with (
            patch.object(congress_fetcher.requests, "get") as get,
            patch.dict("os.environ", {"CONGRESS_API_KEY": "k"}),
        ):
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"bills": [_bill(9, "AI Safety Bureau Act")]}
            get.return_value.raise_for_status.return_value = None
            out = congress_fetcher.fetch_ai_bills()
        c = out[0]
        assert c["url"] == "https://www.congress.gov/bill/119th-congress/s/9"
        assert c["source_feed_id"] == "us-congress"
        assert c["id"] == congress_fetcher._stable_id(c["url"])
        assert c["publish_time"] == "2026-09-28"

    def test_request_error_swallowed(self):
        import requests as _r

        with (
            patch.object(congress_fetcher.requests, "get", side_effect=_r.exceptions.Timeout("t")),
            patch.dict("os.environ", {"CONGRESS_API_KEY": "k"}),
        ):
            assert congress_fetcher.fetch_ai_bills() == []
