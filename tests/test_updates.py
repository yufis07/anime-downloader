import pytest

from animepahe_dl import updates
from animepahe_dl.http import HttpError
from animepahe_dl.updates import check_for_update, parse_release

OLD = "a" * 40
NEW = "b" * 40
RELEASE = {
    "html_url": "https://github.com/yufis07/anime-downloader/releases/tag/latest",
    "published_at": "2026-10-10T12:34:56Z", "target_commitish": NEW,
    "body": f"Windows build of commit {NEW}. Unzip and run AnimePaheDL.exe.",
    "assets": [{"name": "AnimePaheDL-windows-x64.zip", "size": 211198579}],
}


class Http:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.headers = payload, error, None

    def get_json(self, url, **kwargs):
        self.headers = kwargs.get("headers")
        if self.error:
            raise self.error
        return self.payload


def test_parse_release():
    info = parse_release(RELEASE)
    assert (info.sha, info.published, info.size) == (NEW, "2026-10-10", 211198579)
    assert parse_release({"body": "no sha here", "target_commitish": "main"}) is None
    assert parse_release(None) is None
    # falls back to target_commitish when the notes carry no commit
    assert parse_release({"body": "", "target_commitish": NEW}).sha == NEW


def test_update_available_current_and_dev():
    assert check_for_update(Http(RELEASE), OLD).status == "available"
    assert check_for_update(Http(RELEASE), NEW).status == "current"
    http = Http(RELEASE)
    assert check_for_update(http, "").status == "dev" and http.headers is None  # no request from source


def test_token_is_sent_only_when_given():
    http = Http(RELEASE)
    check_for_update(http, OLD)
    assert "Authorization" not in http.headers
    check_for_update(http, OLD, token="  ghp_abc  ")
    assert http.headers["Authorization"] == "Bearer ghp_abc"


def test_private_repository_gives_a_hint_not_an_error():
    result = check_for_update(Http(error=HttpError("HTTP 404", 404)), OLD)
    assert result.status == "unavailable" and "token" in result.message
    rejected = check_for_update(Http(error=HttpError("HTTP 401", 401)), OLD, token="bad")
    assert rejected.status == "unavailable" and "did not accept" in rejected.message


def test_other_errors_propagate():
    with pytest.raises(HttpError):
        check_for_update(Http(error=HttpError("HTTP 502", 502)), OLD)


def test_current_build_reads_the_stamp_and_is_empty_without_one(monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "animepahe_dl._build", None)  # an import of it fails: running from source
    assert updates.current_build() == ""
    stamp = types.ModuleType("animepahe_dl._build")
    stamp.BUILD_SHA = "c" * 40
    monkeypatch.setitem(sys.modules, "animepahe_dl._build", stamp)  # what the CI build writes
    assert updates.current_build() == "c" * 40
