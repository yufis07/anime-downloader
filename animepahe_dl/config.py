"""Persistent application settings stored as JSON in the user's app-data folder."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "AnimePaheDL"
DEFAULT_BASE_URL = "https://animepahe.pw"
QUALITIES = (1080, 720, 480, 360)
AUDIO_CHOICES = ("jpn", "eng", "any")


def app_data_dir() -> Path:
    """%APPDATA%\\AnimePaheDL on Windows, ~/.config/AnimePaheDL elsewhere."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_download_dir() -> Path:
    if sys.platform == "win32":
        return Path.home() / "Videos" / "Anime"
    return Path.home() / "Downloads" / "Anime"


@dataclass
class Settings:
    base_url: str = DEFAULT_BASE_URL
    download_dir: str = field(default_factory=lambda: str(default_download_dir()))
    quality: int = 1080
    audio: str = "jpn"
    prefer_non_av1: bool = True
    max_parallel_episodes: int = 2
    segment_workers: int = 8
    ffmpeg_path: str = ""
    filename_template: str = "{anime} - Episode {episode}"
    # Identity captured from the Cloudflare verification browser. Cloudflare binds
    # the cf_clearance cookie to the browser's User-Agent, so both must be reused.
    user_agent: str = ""
    cookies: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def default_path() -> Path:
        return app_data_dir() / "settings.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or cls.default_path()
        settings = cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                setattr(settings, key, value)
        settings.normalize()
        return settings

    def save(self, path: Path | None = None) -> None:
        path = Path(path or self.default_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def normalize(self) -> None:
        self.base_url = (self.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            self.base_url = "https://" + self.base_url
        try:
            self.quality = int(self.quality)
        except (TypeError, ValueError):
            self.quality = 1080
        if self.audio not in AUDIO_CHOICES:
            self.audio = "jpn"
        self.max_parallel_episodes = max(1, min(6, int(self.max_parallel_episodes or 1)))
        self.segment_workers = max(1, min(32, int(self.segment_workers or 8)))
        if not isinstance(self.cookies, dict):
            self.cookies = {}
        if not self.filename_template.strip():
            self.filename_template = "{anime} - Episode {episode}"
