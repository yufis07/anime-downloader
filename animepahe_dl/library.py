"""Watchlist and download history, stored as JSON next to the settings.

* A *followed* show remembers which episode numbers were known when you last looked
  (``seen``). Episodes that appear later are "new" until you open the show again or download them.
* Every finished download is recorded, so episode lists can show a check mark and
  "select missing" works without scanning the disk.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .config import app_data_dir


def show_key(site: str, session: str) -> str:
    return f"{site}:{session}"


@dataclass
class Followed:
    site: str
    session: str
    title: str
    poster: str = ""
    seen: list[float] = field(default_factory=list)       # episode numbers known when last acknowledged
    available: list[float] = field(default_factory=list)  # episode numbers found by the latest check
    checked_at: float = 0.0
    error: str = ""

    @property
    def key(self) -> str:
        return show_key(self.site, self.session)


class Library:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else app_data_dir() / "library.json"
        self._lock = threading.RLock()
        self.followed: dict[str, Followed] = {}
        self.downloads: dict[str, dict[str, str]] = {}  # show key -> {episode number: file path}
        self.load()

    # ------------------------------------------------------------------ persistence
    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        with self._lock:
            for item in data.get("followed", []):
                try:
                    show = Followed(**{k: v for k, v in item.items() if k in Followed.__dataclass_fields__})
                except TypeError:
                    continue
                self.followed[show.key] = show
            self.downloads = {k: dict(v) for k, v in (data.get("downloads") or {}).items()}

    def save(self) -> None:
        with self._lock:
            payload = {"followed": [asdict(s) for s in self.followed.values()], "downloads": self.downloads}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)

    # ------------------------------------------------------------------ following
    def is_following(self, site: str, session: str) -> bool:
        return show_key(site, session) in self.followed

    def follow(self, site: str, session: str, title: str, poster: str, episode_numbers: Iterable[float]) -> Followed:
        """Start following; everything that exists today counts as already seen."""
        numbers = sorted(set(episode_numbers))
        with self._lock:
            show = Followed(site, session, title, poster, seen=list(numbers), available=list(numbers),
                            checked_at=time.time())
            self.followed[show.key] = show
            self.save()
            return show

    def unfollow(self, site: str, session: str) -> None:
        with self._lock:
            self.followed.pop(show_key(site, session), None)
            self.save()

    def acknowledge(self, site: str, session: str, episode_numbers: Iterable[float]) -> None:
        """The user looked at these episodes: they are no longer new."""
        with self._lock:
            show = self.followed.get(show_key(site, session))
            if show:
                show.seen = sorted(set(show.seen) | set(episode_numbers))
                show.available = sorted(set(show.available) | set(episode_numbers))
                self.save()

    def new_numbers(self, show: Followed) -> list[float]:
        with self._lock:
            have = self.downloaded_numbers(show.site, show.session)
            return sorted(set(show.available) - set(show.seen) - have)

    def total_new(self) -> int:
        with self._lock:
            return sum(len(self.new_numbers(s)) for s in self.followed.values())

    def shows(self) -> list[Followed]:
        with self._lock:
            return sorted(self.followed.values(), key=lambda s: s.title.lower())

    # ------------------------------------------------------------------ checking for new episodes
    def record_check(self, site: str, session: str, episode_numbers: Iterable[float] | None, error: str = "") -> None:
        with self._lock:
            show = self.followed.get(show_key(site, session))
            if not show:
                return
            if episode_numbers is not None:
                show.available = sorted(set(episode_numbers))
            show.checked_at = time.time()
            show.error = error
            self.save()

    def check_all(self, episodes_of: Callable[[str, str], Iterable[float]],
                  on_progress: Callable[[int, int], None] | None = None) -> int:
        """Fetch every followed show's episode numbers. ``episodes_of(site, session)`` does the
        network call; a failure for one show is recorded on it and does not stop the others.
        Returns the total number of new episodes."""
        shows = self.shows()
        for index, show in enumerate(shows, 1):
            try:
                self.record_check(show.site, show.session, list(episodes_of(show.site, show.session)))
            except Exception as exc:  # noqa: BLE001 - shown on the watchlist row
                self.record_check(show.site, show.session, None, str(exc) or exc.__class__.__name__)
            if on_progress:
                on_progress(index, len(shows))
        return self.total_new()

    # ------------------------------------------------------------------ downloads
    @staticmethod
    def _number(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:g}"

    def record_download(self, site: str, session: str, episode_number: float, path: str) -> None:
        with self._lock:
            self.downloads.setdefault(show_key(site, session), {})[self._number(episode_number)] = path
            self.save()

    def downloaded_numbers(self, site: str, session: str) -> set[float]:
        """Episodes whose recorded file still exists on disk."""
        with self._lock:
            entries = self.downloads.get(show_key(site, session), {})
            return {float(n) for n, path in entries.items() if Path(path).exists()}
