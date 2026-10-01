"""Congress 立法适配器（政策管线版）单测：全 mock。"""
from __future__ import annotations

from unittest.mock import patch

from rss2cubox.policy import congress_fetcher
from rss2cubox.policy.engine import stable_policy_id


def _bill(n: int, title: str, action: str = "Introduced") -> dict:
    return {
        "type": "S",
        "number": n,
        "title": title,
        "url": f"/v3/bill/119th-congress/s/{n}",
        "latestAction": {"actionDate": "2026-09-28", "text": action},
    }


def _mock_api(bills):
    get = patch.object(congress_fetcher.requests, "get")
    env = patch.dict("os.environ", {"CONGRESS_API_KEY": "k"})
    return get, env, bills


class TestFetch:
    def test_ai_titles_kept_as_policy_items(self):
        with _mock_api(None)[0] as get, _mock_api(None)[1]:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"bills": [
                _bill(1, "A bill to establish the Artificial Intelligence Safety Bureau"),
                _bill(2, "Wildland Firefighter Health and Safety Act"),
                _bill(3, "Deepfake accountability amendments"),
            ]}
            get.return_value.raise_for_status.return_value = None
            items = congress_fetcher.fetch_ai_bills()
        assert [i.title.split(" ·")[0] for i in items] == ["S 1", "S 3"]
        assert all(i.site_key == "us_congress" for i in items)
        assert items[0].doc_id == stable_policy_id(items[0].url)
        assert items[0].published_at is not None

    def test_word_boundary_ai(self):
        with _mock_api(None)[0] as get, _mock_api(None)[1]:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"bills": [_bill(1, "Maintaining harbor infrastructure")]}
            get.return_value.raise_for_status.return_value = None
            assert congress_fetcher.fetch_ai_bills() == []

    def test_no_key_returns_empty(self):
        with patch.dict("os.environ", {"CONGRESS_API_KEY": ""}):
            assert congress_fetcher.fetch_ai_bills() == []

    def test_url_strips_format_json(self):
        with _mock_api(None)[0] as get, _mock_api(None)[1]:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"bills": [
                {"type": "S", "number": 9, "title": "AI Safety Bureau Act",
                 "url": "/v3/bill/119th-congress/s/9?format=json",
                 "latestAction": {"actionDate": "2026-09-28", "text": "Read twice"}}
            ]}
            get.return_value.raise_for_status.return_value = None
            items = congress_fetcher.fetch_ai_bills()
        assert items[0].url == "https://www.congress.gov/bill/119th-congress/s/9"

    def test_request_error_swallowed(self):
        import requests as _r

        with (
            patch.object(congress_fetcher.requests, "get", side_effect=_r.exceptions.Timeout("t")),
            patch.dict("os.environ", {"CONGRESS_API_KEY": "k"}),
        ):
            assert congress_fetcher.fetch_ai_bills() == []


class TestRun:
    def test_run_saves_via_policy_store(self):
        saved = {}
        with (
            patch.object(congress_fetcher, "fetch_ai_bills") as fetch,
            patch.object(congress_fetcher, "save_policy_documents") as save,
        ):
            fetch.return_value = [object()]
            save.side_effect = lambda items, **kw: saved.update(kw) or {"inserted": 1, "updated": 0}
            n = congress_fetcher.run()
        assert n == 1
        assert saved["site_name"] == "US Congress 国会立法"
        assert saved["region"] == "美国"

    def test_run_skips_silently_without_candidates(self):
        with patch.object(congress_fetcher, "fetch_ai_bills", return_value=[]):
            with patch.object(congress_fetcher, "save_policy_documents") as save:
                assert congress_fetcher.run() == 0
            save.assert_not_called()
