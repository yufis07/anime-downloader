"""AnimePahe site client: search, episode listing and stream-source scraping."""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import quote_plus, urlsplit

from .http import CloudflareChallenge, HttpClient, HttpError, is_challenge

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


@dataclass
class Anime:
    session: str
    title: str
    type: str = ""
    episodes: int = 0
    status: str = ""
    season: str = ""
    year: int | None = None
    score: float | None = None
    poster: str = ""

    @property
    def subtitle(self) -> str:
        bits = [self.type, f"{self.season} {self.year or ''}".strip(), self.status]
        if self.episodes:
            bits.append(f"{self.episodes} eps")
        if self.score:
            bits.append(f"★ {self.score}")
        return " · ".join(b for b in bits if b)


@dataclass
class Episode:
    session: str
    number: float
    title: str = ""
    snapshot: str = ""
    duration: str = ""
    audio: str = ""
    created_at: str = ""
    filler: bool = False


@dataclass
class Source:
    url: str  # kwik embed URL
    resolution: int
    audio: str = "jpn"
    fansub: str = ""
    av1: bool = False

    @property
    def label(self) -> str:
        parts = [f"{self.resolution}p", self.audio.upper()]
        if self.fansub:
            parts.append(self.fansub)
        if self.av1:
            parts.append("AV1")
        return " · ".join(parts)


class NotAnimePahe(HttpError):
    """The configured address answered, but not like AnimePahe (e.g. a look-alike site)."""


def _page_title(page: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    return html_lib.unescape(" ".join(match.group(1).split()))[:80] if match else ""


class _SourceParser(HTMLParser):
    """Collects every element that carries a ``data-src`` kwik link."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[Source] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k.lower(): (v or "") for k, v in attrs}
        src = data.get("data-src", "")
        if not src or "kwik" not in src:
            return
        try:
            resolution = int(re.sub(r"\D", "", data.get("data-resolution", "")) or 0)
        except ValueError:
            resolution = 0
        self.sources.append(
            Source(
                url=html_lib.unescape(src),
                resolution=resolution,
                audio=(data.get("data-audio") or "jpn").lower(),
                fansub=data.get("data-fansub", ""),
                av1=data.get("data-av1", "0") in {"1", "true"},
            )
        )


def parse_sources(page_html: str) -> list[Source]:
    parser = _SourceParser()
    parser.feed(page_html)
    seen: set[str] = set()
    unique = []
    for source in parser.sources:
        if source.url not in seen:
            seen.add(source.url)
            unique.append(source)
    return unique


def choose_source(
    sources: list[Source], quality: int = 1080, audio: str = "jpn", prefer_non_av1: bool = True
) -> Source | None:
    """Pick the best source: wanted audio (falls back to any), then highest res <= quality."""
    if not sources:
        return None
    pool = sources
    if audio and audio != "any":
        matching = [s for s in sources if s.audio == audio]
        pool = matching or sources
    if prefer_non_av1 and any(not s.av1 for s in pool):
        pool = [s for s in pool if not s.av1]
    at_or_below = [s for s in pool if s.resolution <= quality]
    if at_or_below:
        return max(at_or_below, key=lambda s: s.resolution)
    return min(pool, key=lambda s: s.resolution)


def parse_anime_session(text: str) -> str | None:
    """Extract an anime session id from a URL such as https://animepahe.pw/anime/<uuid>."""
    text = (text or "").strip()
    match = re.search(rf"/(?:anime|play)/({_UUID})", text)
    if match:
        return match.group(1)
    if re.fullmatch(_UUID, text):
        return text
    return None


def _to_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


class AnimePahe:
    def __init__(self, http: HttpClient, base_url: str) -> None:
        self.http = http
        self.set_base_url(base_url)

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.http.set_cookie_host(urlsplit(self.base_url).hostname or "")

    @property
    def referer(self) -> str:
        return self.base_url + "/"

    def _api(self, query: str) -> dict:
        url = f"{self.base_url}/api?{query}"
        resp = self.http.get(
            url,
            referer=self.referer,
            headers={"Accept": "application/json, text/javascript, */*; q=0.01",
                     "X-Requested-With": "XMLHttpRequest"},
        )
        try:
            data = resp.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            return data
        if is_challenge(403, resp.headers, resp.content):
            raise CloudflareChallenge("Cloudflare challenge page returned instead of search data.")
        host = urlsplit(self.base_url).hostname or self.base_url
        final_host = urlsplit(resp.url).hostname or host
        title = _page_title(resp.text)
        detail = f"a web page titled \u201c{title}\u201d" if title else "a normal web page"
        if final_host != host:
            detail += f" (after redirecting to {final_host})"
        raise NotAnimePahe(
            f"{host} answered with {detail} instead of AnimePahe search data, so it is probably not the "
            f"real AnimePahe site. Open Settings and set Site address to the current AnimePahe address, "
            f"for example https://animepahe.pw."
        )

    def check_site(self) -> int:
        """Run a small search to confirm the address is a working AnimePahe site; returns result count."""
        return len(self.search("naruto"))

    # ----------------------------------------------------------------- search
    def search(self, query: str) -> list[Anime]:
        data = self._api(f"m=search&q={quote_plus(query)}")
        results = []
        for item in data.get("data") or []:
            results.append(
                Anime(
                    session=str(item.get("session", "")),
                    title=html_lib.unescape(str(item.get("title", ""))),
                    type=str(item.get("type") or ""),
                    episodes=int(item.get("episodes") or 0),
                    status=str(item.get("status") or ""),
                    season=str(item.get("season") or ""),
                    year=item.get("year"),
                    score=item.get("score"),
                    poster=str(item.get("poster") or ""),
                )
            )
        return results

    # --------------------------------------------------------------- episodes
    def episodes(
        self, anime_session: str, progress: Callable[[int, int], None] | None = None
    ) -> list[Episode]:
        episodes: list[Episode] = []
        page, last_page = 1, 1
        while page <= last_page:
            data = self._api(f"m=release&id={anime_session}&sort=episode_asc&page={page}")
            last_page = int(data.get("last_page") or 1)
            for item in data.get("data") or []:
                number = _to_float(item.get("episode"))
                episodes.append(
                    Episode(
                        session=str(item.get("session", "")),
                        number=number,
                        title=html_lib.unescape(str(item.get("title") or "")),
                        snapshot=str(item.get("snapshot") or ""),
                        duration=str(item.get("duration") or ""),
                        audio=str(item.get("audio") or ""),
                        created_at=str(item.get("created_at") or ""),
                        filler=bool(item.get("filler")),
                    )
                )
            if progress:
                progress(page, last_page)
            page += 1
        # De-duplicate (same number can appear twice when both sub & dub are listed).
        by_number: dict[float, Episode] = {}
        for ep in episodes:
            by_number.setdefault(ep.number, ep)
        return [by_number[n] for n in sorted(by_number)]

    def anime_title(self, anime_session: str) -> str:
        page = self.http.get_text(f"{self.base_url}/anime/{anime_session}", referer=self.referer)
        for pattern in (
            r"<h1[^>]*>\s*(?:<span[^>]*>)?([^<]+)",
            r"<title>\s*([^<]+?)\s*(?:::|\||-)\s*animepahe",
            r"<title>\s*([^<]+)</title>",
        ):
            match = re.search(pattern, page, re.I)
            if match and match.group(1).strip():
                return html_lib.unescape(match.group(1).strip())
        return f"Anime {anime_session[:8]}"

    # ---------------------------------------------------------------- sources
    def play_url(self, anime_session: str, episode_session: str) -> str:
        return f"{self.base_url}/play/{anime_session}/{episode_session}"

    def sources(self, anime_session: str, episode_session: str) -> list[Source]:
        page = self.http.get_text(self.play_url(anime_session, episode_session), referer=self.referer)
        sources = parse_sources(page)
        if not sources:
            raise HttpError("No video sources found on the episode page (site layout may have changed).")
        return sources
