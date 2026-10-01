"""MyAnimeList lookup: turn an English anime title into the Japanese (romaji) title.

MyAnimeList's default title is the romaji one, e.g. "Sousou no Frieren" for "Frieren: Beyond
Journey's End". ``MalTitle.title`` is that name.

MyAnimeList's own API needs a client id, so this uses Jikan (https://jikan.moe), the public
read-only API that mirrors MyAnimeList's data and needs no key. Jikan is often down when
MyAnimeList itself is slow (HTTP 504), so AniList (same romaji titles) is the fallback.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from .http import HttpClient, HttpError

JIKAN_SEARCH_URL = "https://api.jikan.moe/v4/anime?q={query}&limit=10&sfw=false"
ANILIST_URL = "https://graphql.anilist.co"
ANILIST_QUERY = """query ($search: String) { Page(perPage: 10) { media(search: $search, type: ANIME) {
  idMal siteUrl format seasonYear title { romaji english } synonyms } } }"""
MIN_SIMILARITY = 0.6  # a non-exact top hit must at least look like the title that was searched


@dataclass
class MalTitle:
    mal_id: int
    title: str  # MyAnimeList's default (romaji) title
    title_english: str = ""
    synonyms: list[str] = field(default_factory=list)
    type: str = ""
    year: int | None = None
    url: str = ""

    @property
    def names(self) -> list[str]:
        return [n for n in (self.title_english, self.title, *self.synonyms) if n]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w]+", " ", text).strip()


def _parse_entry(item: dict) -> MalTitle:
    titles = item.get("titles") or []
    synonyms = [str(t.get("title")) for t in titles if t.get("type") == "Synonym" and t.get("title")]
    return MalTitle(
        mal_id=int(item.get("mal_id") or 0),
        title=str(item.get("title") or ""),
        title_english=str(item.get("title_english") or ""),
        synonyms=synonyms,
        type=str(item.get("type") or ""),
        year=item.get("year"),
        url=str(item.get("url") or ""),
    )


def _parse_anilist(item: dict) -> MalTitle:
    titles = item.get("title") or {}
    return MalTitle(
        mal_id=int(item.get("idMal") or 0),
        title=str(titles.get("romaji") or ""),
        title_english=str(titles.get("english") or ""),
        synonyms=[str(s) for s in item.get("synonyms") or []],
        type=str(item.get("format") or ""),
        year=item.get("seasonYear"),
        url=str(item.get("siteUrl") or ""),
    )


def best_match(query: str, candidates: list[MalTitle]) -> MalTitle | None:
    """Pick the candidate whose English/romaji/synonym title equals the query. Otherwise take the
    top hit, but only when one of its names is similar to the query (never rename to an unrelated show)."""
    wanted = _normalize(query)
    usable = [c for c in candidates if c.title]
    for candidate in usable:
        if wanted in {_normalize(n) for n in candidate.names}:
            return candidate
    if usable:
        top = usable[0]
        if any(difflib.SequenceMatcher(None, wanted, _normalize(n)).ratio() >= MIN_SIMILARITY for n in top.names):
            return top
    return None


class MalLookup:
    def __init__(self, http: HttpClient | None = None) -> None:
        # A dedicated client: the app's main one carries AnimePahe/Cloudflare cookies.
        self.http = http or HttpClient(retries=2, timeout=15.0)

    def search(self, query: str) -> list[MalTitle]:
        query = query.strip()
        if not query:
            return []
        data = self.http.get_json(JIKAN_SEARCH_URL.format(query=quote_plus(query)), check_challenge=False)
        if not isinstance(data, dict):
            raise HttpError("Unexpected answer from MyAnimeList lookup (Jikan).")
        return [_parse_entry(item) for item in data.get("data") or []]

    def search_anilist(self, query: str) -> list[MalTitle]:
        query = query.strip()
        if not query:
            return []
        data = self.http.post_json(ANILIST_URL, {"query": ANILIST_QUERY, "variables": {"search": query}})
        media = (((data or {}).get("data") or {}).get("Page") or {}).get("media") or []
        return [_parse_anilist(item) for item in media]

    def japanese_title(self, english_title: str) -> MalTitle | None:
        """Look ``english_title`` up on MyAnimeList (Jikan), falling back to AniList when Jikan is
        down or has no match. The result's ``title`` is the romaji title."""
        jikan_error: Exception | None = None
        try:
            match = best_match(english_title, self.search(english_title))
            if match:
                return match
        except HttpError as exc:
            jikan_error = exc
        try:
            return best_match(english_title, self.search_anilist(english_title))
        except HttpError as exc:
            if jikan_error:
                raise HttpError(f"MyAnimeList (Jikan): {jikan_error}; AniList: {exc}") from exc
            raise
