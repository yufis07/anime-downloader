import json
import time
from datetime import date

import pytest

from animepahe_dl import discover
from animepahe_dl.discover import DiscoverClient, current_season, parse_items
from animepahe_dl.http import HttpError

MEDIA = {"id": 1, "title": {"romaji": "Super no Ura de Yani Suu Futari", "english": "Smoking Behind the Supermarket with You"},
         "coverImage": {"large": "https://s4.anilist.co/l.jpg", "extraLarge": "https://s4.anilist.co/xl.jpg"},
         "averageScore": 78, "seasonYear": 2026, "format": "TV_SHORT", "episodes": 12, "status": "RELEASING"}
NO_ENGLISH = {"title": {"romaji": "Only Romaji", "english": None}, "coverImage": None, "averageScore": None}


class Http:
    def __init__(self, fail=False):
        self.fail, self.calls, self.variables = fail, 0, None

    def post_json(self, url, payload, **kwargs):
        self.calls += 1
        self.variables = payload["variables"]
        if self.fail:
            raise HttpError("HTTP 502", 502)
        page = {"media": [MEDIA, NO_ENGLISH, {"title": {}}]}
        return {"data": {"trending": page, "season": page, "top": {"media": []}}}


def test_current_season():
    assert current_season(date(2026, 1, 15)) == ("WINTER", 2026)
    assert current_season(date(2026, 4, 1)) == ("SPRING", 2026)
    assert current_season(date(2026, 8, 31)) == ("SUMMER", 2026)
    assert current_season(date(2026, 12, 1)) == ("FALL", 2026)


def test_parse_items_and_titles():
    items = parse_items({"media": [MEDIA, NO_ENGLISH, {"title": {}}]})
    assert [i.romaji for i in items] == ["Super no Ura de Yani Suu Futari", "Only Romaji"]  # nameless one dropped
    first, second = items
    assert first.title == "Smoking Behind the Supermarket with You"
    assert first.search_titles == ["Smoking Behind the Supermarket with You", "Super no Ura de Yani Suu Futari"]
    assert first.info == "★ 7.8 · TV SHORT · 2026"
    assert second.search_titles == ["Only Romaji"] and second.score is None and second.cover_url == ""


def test_fetch_uses_fresh_cache_and_refreshes_when_forced(tmp_path):
    http = Http()
    client = DiscoverClient(http, tmp_path / "discover.json")
    _, sections = client.fetch(today=date(2026, 10, 10))
    assert http.variables == {"season": "FALL", "year": 2026, "n": discover.PER_SECTION}
    assert len(sections["trending"]) == 2 and sections["top"] == []
    client.fetch()
    assert http.calls == 1  # second call came from the cache
    client.fetch(force=True)
    assert http.calls == 2


def test_stale_cache_is_used_when_anilist_is_down(tmp_path):
    path = tmp_path / "discover.json"
    DiscoverClient(Http(), path).fetch()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["fetched_at"] = time.time() - 10 * 3600
    path.write_text(json.dumps(data), encoding="utf-8")
    fetched_at, sections = DiscoverClient(Http(fail=True), path).fetch()
    assert sections["trending"] and time.time() - fetched_at > 9 * 3600


def test_error_without_any_cache(tmp_path):
    with pytest.raises(HttpError):
        DiscoverClient(Http(fail=True), tmp_path / "none.json").fetch()
