"""Show details (synopsis, genres, score, banner...) from AniList, used by the show page.

AnimePahe's and AnimeHeaven's own pages carry little more than a title and a poster, so the show
page asks AniList instead. It works for both sites and needs no key.
"""

from __future__ import annotations

import html as html_lib
import re
import threading
from dataclasses import dataclass, field

from .http import HttpClient, HttpError
from .mal import MalTitle, best_match

ANILIST_URL = "https://graphql.anilist.co"
QUERY = """query ($search: String) { Page(perPage: 8) { media(search: $search, type: ANIME) {
  siteUrl format status seasonYear episodes averageScore genres description(asHtml: false) bannerImage
  coverImage { extraLarge large } studios(isMain: true) { nodes { name } }
  title { romaji english } synonyms } } }"""

STATUS_LABELS = {
    "FINISHED": "Finished", "RELEASING": "Airing", "NOT_YET_RELEASED": "Not yet released",
    "CANCELLED": "Cancelled", "HIATUS": "On hiatus",
}
FORMAT_LABELS = {"TV": "TV", "TV_SHORT": "TV short", "MOVIE": "Movie", "SPECIAL": "Special", "OVA": "OVA",
                 "ONA": "ONA", "MUSIC": "Music"}


@dataclass
class ShowDetails:
    romaji: str
    english: str = ""
    synopsis: str = ""
    genres: list[str] = field(default_factory=list)
    score: float | None = None  # 0-10
    year: int | None = None
    episodes: int = 0
    status: str = ""
    format: str = ""
    studio: str = ""
    banner_url: str = ""
    cover_url: str = ""
    url: str = ""

    @property
    def facts(self) -> list[str]:
        """Short chips for the header, in display order."""
        bits = [f"★ {self.score:.1f}" if self.score else "", self.format, str(self.year or ""),
                f"{self.episodes} episodes" if self.episodes else "", self.status, self.studio]
        return [b for b in bits if b]


def clean_synopsis(text: str) -> str:
    """AniList descriptions contain <br>, <i> and entities; return plain paragraphs."""
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_media(item: dict) -> tuple[MalTitle, ShowDetails]:
    titles = item.get("title") or {}
    cover = item.get("coverImage") or {}
    studios = ((item.get("studios") or {}).get("nodes")) or []
    score = item.get("averageScore")
    details = ShowDetails(
        romaji=str(titles.get("romaji") or ""),
        english=str(titles.get("english") or ""),
        synopsis=clean_synopsis(item.get("description") or ""),
        genres=[str(g) for g in item.get("genres") or []],
        score=round(score / 10, 1) if score else None,
        year=item.get("seasonYear"),
        episodes=int(item.get("episodes") or 0),
        status=STATUS_LABELS.get(str(item.get("status") or ""), str(item.get("status") or "").title()),
        format=FORMAT_LABELS.get(str(item.get("format") or ""), str(item.get("format") or "")),
        studio=str(studios[0].get("name")) if studios else "",
        banner_url=str(item.get("bannerImage") or ""),
        cover_url=str(cover.get("extraLarge") or cover.get("large") or ""),
        url=str(item.get("siteUrl") or ""),
    )
    names = MalTitle(mal_id=0, title=details.romaji, title_english=details.english,
                     synonyms=[str(s) for s in item.get("synonyms") or []])
    return names, details


class DetailsClient:
    def __init__(self, http: HttpClient | None = None) -> None:
        self.http = http or HttpClient(retries=2, timeout=15.0)
        self._cache: dict[str, ShowDetails | None] = {}
        self._lock = threading.Lock()

    def fetch(self, title: str) -> ShowDetails | None:
        """Details of the show best matching ``title`` (cached); None if AniList has no match."""
        key = title.strip().lower()
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        data = self.http.post_json(ANILIST_URL, {"query": QUERY, "variables": {"search": title.strip()}})
        media = (((data or {}).get("data") or {}).get("Page") or {}).get("media") or []
        if not isinstance(media, list):
            raise HttpError("Unexpected answer from AniList.")
        parsed = [parse_media(item) for item in media]
        match = best_match(title, [names for names, _ in parsed])
        result = next((d for names, d in parsed if names is match), None) if match else None
        with self._lock:
            self._cache[key] = result
        return result
