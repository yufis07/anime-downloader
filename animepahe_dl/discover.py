"""Discover home: trending, this season and top rated anime from AniList (one request, cached).

Clicking a title in the app searches the active download site for it, so this only needs names
and cover art, and works for both AnimePahe and AnimeHeaven.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .config import app_data_dir
from .http import HttpClient, HttpError

ANILIST_URL = "https://graphql.anilist.co"
CACHE_SECONDS = 6 * 3600
PER_SECTION = 20

_FIELDS = "id title { romaji english } coverImage { extraLarge large } averageScore seasonYear format episodes status"
QUERY = f"""query ($season: MediaSeason, $year: Int, $n: Int) {{
  trending: Page(perPage: $n) {{ media(type: ANIME, isAdult: false, sort: TRENDING_DESC) {{ {_FIELDS} }} }}
  season: Page(perPage: $n) {{ media(type: ANIME, isAdult: false, season: $season, seasonYear: $year,
      sort: POPULARITY_DESC) {{ {_FIELDS} }} }}
  top: Page(perPage: $n) {{ media(type: ANIME, isAdult: false, sort: SCORE_DESC) {{ {_FIELDS} }} }}
}}"""

SECTION_TITLES = {"trending": "Trending now", "season": "This season", "top": "Top rated"}


def current_season(today: date | None = None) -> tuple[str, int]:
    """AniList season for ``today``: Jan-Mar WINTER, Apr-Jun SPRING, Jul-Sep SUMMER, Oct-Dec FALL."""
    today = today or date.today()
    names = {1: "WINTER", 2: "WINTER", 3: "WINTER", 4: "SPRING", 5: "SPRING", 6: "SPRING",
             7: "SUMMER", 8: "SUMMER", 9: "SUMMER", 10: "FALL", 11: "FALL", 12: "FALL"}
    return names[today.month], today.year


@dataclass
class DiscoverItem:
    romaji: str
    english: str = ""
    cover_url: str = ""
    score: float | None = None  # 0-10
    year: int | None = None
    format: str = ""
    episodes: int = 0
    status: str = ""

    @property
    def title(self) -> str:
        return self.english or self.romaji

    @property
    def search_titles(self) -> list[str]:
        """Names to try on the download sites, best first."""
        names = [self.english, self.romaji]
        return [n for i, n in enumerate(names) if n and n not in names[:i]]

    @property
    def info(self) -> str:
        bits = [f"★ {self.score:.1f}" if self.score else "", self.format, str(self.year or "")]
        return " · ".join(b for b in bits if b)


def parse_items(page: dict | None) -> list[DiscoverItem]:
    items = []
    for media in ((page or {}).get("media") or []):
        titles = media.get("title") or {}
        cover = media.get("coverImage") or {}
        romaji = str(titles.get("romaji") or titles.get("english") or "")
        if not romaji:
            continue
        score = media.get("averageScore")
        items.append(DiscoverItem(
            romaji=romaji, english=str(titles.get("english") or ""),
            cover_url=str(cover.get("large") or cover.get("extraLarge") or ""),
            score=round(score / 10, 1) if score else None, year=media.get("seasonYear"),
            format=str(media.get("format") or "").replace("_", " "), episodes=int(media.get("episodes") or 0),
            status=str(media.get("status") or "")))
    return items


class DiscoverClient:
    def __init__(self, http: HttpClient | None = None, cache_path: Path | None = None) -> None:
        self.http = http or HttpClient(retries=2, timeout=15.0)
        self.cache_path = Path(cache_path) if cache_path else app_data_dir() / "discover.json"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ cache
    def _read_cache(self) -> tuple[float, dict[str, list[DiscoverItem]]] | None:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            sections = {k: [DiscoverItem(**i) for i in v] for k, v in raw["sections"].items()}
            return float(raw["fetched_at"]), sections
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write_cache(self, sections: dict[str, list[DiscoverItem]]) -> None:
        payload = {"fetched_at": time.time(), "sections": {k: [asdict(i) for i in v] for k, v in sections.items()}}
        try:
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError:
            pass

    def cached(self) -> tuple[float, dict[str, list[DiscoverItem]]] | None:
        return self._read_cache()

    # ------------------------------------------------------------------ network
    def fetch(self, force: bool = False, today: date | None = None) -> tuple[float, dict[str, list[DiscoverItem]]]:
        """(fetched_at, sections). Uses the cache while it is fresh; falls back to a stale cache
        when AniList cannot be reached, and raises only when there is nothing to show."""
        with self._lock:
            cache = self._read_cache()
            if cache and not force and time.time() - cache[0] < CACHE_SECONDS:
                return cache
            season, year = current_season(today)
            try:
                data = self.http.post_json(
                    ANILIST_URL, {"query": QUERY, "variables": {"season": season, "year": year, "n": PER_SECTION}})
                body = (data or {}).get("data")
                if not isinstance(body, dict):
                    raise HttpError("Unexpected answer from AniList.")
                sections = {key: parse_items(body.get(key)) for key in SECTION_TITLES}
            except HttpError:
                if cache:
                    return cache
                raise
            self._write_cache(sections)
            return time.time(), sections
