"""AnimeHeaven (animeheaven.me) client: search, episode list and direct video link.

The site serves plain HTML and plain ``.mp4`` files (no HLS, no packed JavaScript):

* ``search.php?s=<text>`` lists shows as links to ``anime.php?<id>``.
* ``anime.php?<id>`` shows the title, the romaji title (``infotitlejp``) and one ``gate.php`` link
  per episode; the link's ``id`` attribute is the episode key.
* Opening an episode sets a ``key`` cookie to that id and loads ``gate.php``, whose player page
  holds the ``.mp4`` address.
"""

from __future__ import annotations

import html as html_lib
import re
import threading
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlsplit

from .animepahe import Anime, Episode
from .http import HttpClient, HttpError

DEFAULT_BASE_URL = "https://animeheaven.me"
_ID = r"[0-9a-z]{4,12}"


@dataclass
class ShowInfo:
    title: str
    japanese_title: str = ""  # romaji, e.g. "Sousou no Frieren"
    episodes: int = 0


def parse_anime_id(text: str) -> str | None:
    """Accept an ``anime.php?<id>`` link and return the id."""
    match = re.search(rf"animeheaven\.[a-z]+/anime\.php\?({_ID})\b", text or "", re.I)
    return match.group(1) if match else None


def _strip(text: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", text))).strip()


class _SearchParser(HTMLParser):
    """Collects ``<a href=".../anime.php?id"><img alt="Title" src="poster">`` cards."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.results: dict[str, Anime] = {}
        self._current: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "a":
            match = re.search(rf"anime\.php\?({_ID})$", a.get("href", ""))
            self._current = match.group(1) if match else None
        elif tag == "img" and self._current and "coverimg" in a.get("class", ""):
            title = html_lib.unescape(a.get("alt", "")).strip()
            if title and self._current not in self.results:
                self.results[self._current] = Anime(
                    session=self._current, title=title,
                    poster=urljoin(self.base_url + "/", a.get("src", "")), site="animeheaven")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._current = None


def parse_search(page: str, base_url: str = DEFAULT_BASE_URL) -> list[Anime]:
    parser = _SearchParser(base_url)
    parser.feed(page)
    return list(parser.results.values())


def parse_show(page: str) -> ShowInfo:
    def grab(css_class: str) -> str:
        match = re.search(rf'class="{css_class}[^"]*"[^>]*>(.*?)</div>', page, re.S)
        return _strip(match.group(1)) if match else ""

    count = re.search(r"Episodes:\s*<div[^>]*>\s*(\d+)", page)
    return ShowInfo(title=grab("infotitle"), japanese_title=grab("infotitlejp"),
                    episodes=int(count.group(1)) if count else 0)


def parse_episodes(page: str) -> list[Episode]:
    """One ``<a id="<key>" href=".../gate.php">…<div class="watch2 …">N</div>…</a>`` per episode."""
    episodes: dict[str, Episode] = {}
    for match in re.finditer(r'<a\b[^>]*\bid="([0-9a-f]{16,64})"[^>]*href="[^"]*gate\.php"[^>]*>(.*?)</a>',
                             page, re.S):
        key, body = match.groups()
        number = re.search(r'class="[^"]*watch2[^"]*"[^>]*>\s*([\d.]+)\s*<', body)
        if number:
            episodes[key] = Episode(session=key, number=float(number.group(1)))
    return sorted(episodes.values(), key=lambda e: e.number)


_MEDIA = re.compile(r"""https?:(?:\\?/){2}[^\s"'<>\\]+?\.(?:mp4|m3u8)[^\s"'<>\\]*""", re.I)


def parse_video_urls(page: str) -> list[str]:
    """Every .mp4/.m3u8 address on the player page (``<source src>``, links, inline scripts)."""
    urls: list[str] = []
    for raw in _MEDIA.findall(page):
        url = html_lib.unescape(raw).replace("\\/", "/")
        if url not in urls:
            urls.append(url)
    return urls


class AnimeHeaven:
    site = "animeheaven"

    def __init__(self, http: HttpClient, base_url: str = DEFAULT_BASE_URL) -> None:
        self.http = http
        self.set_base_url(base_url)
        self._info: dict[str, ShowInfo] = {}
        self._gate_lock = threading.Lock()  # the "key" cookie is shared, so open one episode at a time

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.http.set_cookie_host(urlsplit(self.base_url).hostname or "")

    @property
    def referer(self) -> str:
        return self.base_url + "/"

    def _page(self, path: str) -> str:
        return self.http.get_text(f"{self.base_url}/{path}", referer=self.referer)

    def check_site(self) -> int:
        return len(self.search("naruto"))

    def search(self, query: str) -> list[Anime]:
        return parse_search(self._page(f"search.php?s={quote_plus(query)}"), self.base_url)

    def show_info(self, anime_id: str) -> ShowInfo:
        if anime_id not in self._info:
            self._info[anime_id] = parse_show(self._page(f"anime.php?{anime_id}"))
        return self._info[anime_id]

    def anime_title(self, anime_id: str) -> str:
        return self.show_info(anime_id).title or f"Anime {anime_id}"

    def japanese_title(self, anime_id: str) -> str:
        return self.show_info(anime_id).japanese_title

    def episodes(self, anime_id: str, progress=None) -> list[Episode]:  # noqa: ANN001
        page = self._page(f"anime.php?{anime_id}")
        self._info[anime_id] = parse_show(page)
        episodes = parse_episodes(page)
        if not episodes:
            raise HttpError("No episodes found on the AnimeHeaven page (site layout may have changed).")
        return episodes

    def video_url(self, episode_key: str) -> str:
        """Open the episode the way the browser does (``key`` cookie, then ``gate.php``)."""
        with self._gate_lock:
            self.http.cookies["key"] = episode_key
            page = self._page("gate.php")
        urls = parse_video_urls(page)
        if not urls:
            raise HttpError("No video link found on the AnimeHeaven player page (site layout may have changed).")
        return next((u for u in urls if ".mp4" in u.lower()), urls[0])
