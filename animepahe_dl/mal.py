"""MyAnimeList lookup: turn an English anime title into the Japanese (romaji) title.

MyAnimeList's default title is the romaji one, e.g. "Sousou no Frieren" for "Frieren: Beyond
Journey's End". ``MalTitle.title`` is that name; ``title_japanese`` is the kanji/kana version.

MyAnimeList's own API needs a client id, so this uses Jikan (https://jikan.moe), the public
read-only API that mirrors MyAnimeList's data and needs no key.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from .http import HttpClient, HttpError

JIKAN_SEARCH_URL = "https://api.jikan.moe/v4/anime?q={query}&limit=10&sfw=false"


@dataclass
class MalTitle:
    mal_id: int
    title: str  # MyAnimeList's default (romaji) title
    title_english: str = ""
    title_japanese: str = ""
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
        title_japanese=str(item.get("title_japanese") or ""),
        synonyms=synonyms,
        type=str(item.get("type") or ""),
        year=item.get("year"),
        url=str(item.get("url") or ""),
    )


def best_match(query: str, candidates: list[MalTitle]) -> MalTitle | None:
    """Pick the candidate whose English/romaji/synonym title equals the query, else the top hit."""
    wanted = _normalize(query)
    usable = [c for c in candidates if c.title]
    for candidate in usable:
        if wanted in {_normalize(n) for n in candidate.names}:
            return candidate
    return usable[0] if usable else None


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

    def japanese_title(self, english_title: str) -> MalTitle | None:
        """Look ``english_title`` up on MyAnimeList; the result's ``title`` is the romaji title."""
        return best_match(english_title, self.search(english_title))
