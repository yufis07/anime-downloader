"""Download queue: resolves sources, downloads HLS streams and remuxes to MP4."""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from . import kwik
from .animepahe import AnimePahe, Episode, choose_source
from .config import Settings
from .hls import Cancelled, HlsDownloader, load_media_playlist
from .http import CloudflareChallenge
from .utils import find_ffmpeg, format_episode, sanitize_filename


class Status(str, Enum):
    QUEUED = "Queued"
    RESOLVING = "Resolving"
    DOWNLOADING = "Downloading"
    MUXING = "Converting"
    DONE = "Done"
    SKIPPED = "Already exists"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def finished(self) -> bool:
        return self in {Status.DONE, Status.SKIPPED, Status.FAILED, Status.CANCELLED}


_ids = itertools.count(1)


@dataclass
class DownloadTask:
    anime_title: str
    anime_session: str
    episode: Episode
    id: int = field(default_factory=lambda: next(_ids))
    status: Status = Status.QUEUED
    source_label: str = ""
    segments_done: int = 0
    segments_total: int = 0
    bytes_done: int = 0
    speed: float = 0.0
    message: str = ""
    output_path: str = ""
    cloudflare_blocked: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _speed_window: list[tuple[float, int]] = field(default_factory=list, repr=False)

    @property
    def progress(self) -> float:
        if self.status in {Status.DONE, Status.SKIPPED}:
            return 1.0
        return self.segments_done / self.segments_total if self.segments_total else 0.0

    @property
    def episode_label(self) -> str:
        return format_episode(self.episode.number)


def build_output_path(settings: Settings, anime_title: str, episode: Episode, resolution: int,
                      audio: str, extension: str = ".mp4") -> Path:
    values = {
        "anime": anime_title,
        "episode": format_episode(episode.number),
        "quality": f"{resolution}p",
        "audio": audio,
        "title": episode.title or "",
    }
    try:
        name = settings.filename_template.format(**values)
    except (KeyError, IndexError, ValueError):
        name = "{anime} - Episode {episode}".format(**values)
    folder = Path(settings.download_dir) / sanitize_filename(anime_title)
    return folder / (sanitize_filename(name) + extension)


def remux_to_mp4(ffmpeg: str, source: Path, target: Path) -> None:
    tmp = target.with_name(target.stem + ".converting.mp4")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
           "-map", "0:v", "-map", "0:a?", "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(tmp)]
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)  # noqa: S603
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-300:]}")
    os.replace(tmp, target)


class DownloadManager:
    """Thread-based download queue. The GUI polls :meth:`snapshot` to render progress."""

    def __init__(self, api: AnimePahe, settings: Settings,
                 on_cloudflare: Callable[[], None] | None = None) -> None:
        self.api = api
        self.settings = settings
        self.on_cloudflare = on_cloudflare
        self._tasks: list[DownloadTask] = []
        self._cond = threading.Condition()
        self._active = 0
        self._stopping = False
        self._dispatcher = threading.Thread(target=self._dispatch_loop, name="dispatcher", daemon=True)
        self._dispatcher.start()

    # ---------------------------------------------------------------- public API
    def add(self, anime_title: str, anime_session: str, episodes: list[Episode]) -> list[DownloadTask]:
        new = [DownloadTask(anime_title, anime_session, ep) for ep in episodes]
        with self._cond:
            existing = {(t.anime_session, t.episode.session) for t in self._tasks if not t.status.finished}
            new = [t for t in new if (t.anime_session, t.episode.session) not in existing]
            self._tasks.extend(new)
            self._cond.notify_all()
        return new

    def snapshot(self) -> list[DownloadTask]:
        with self._cond:
            return list(self._tasks)

    def cancel(self, task_id: int) -> None:
        with self._cond:
            for task in self._tasks:
                if task.id == task_id and not task.status.finished:
                    task.cancel_event.set()
                    if task.status == Status.QUEUED:
                        task.status = Status.CANCELLED
            self._cond.notify_all()

    def cancel_all(self) -> None:
        for task in self.snapshot():
            self.cancel(task.id)

    def retry(self, task_id: int) -> None:
        with self._cond:
            for task in self._tasks:
                if task.id == task_id and task.status in {Status.FAILED, Status.CANCELLED}:
                    self._reset(task)
            self._cond.notify_all()

    def retry_failed(self, only_cloudflare: bool = False) -> int:
        count = 0
        with self._cond:
            for task in self._tasks:
                if task.status == Status.FAILED and (task.cloudflare_blocked or not only_cloudflare):
                    self._reset(task)
                    count += 1
            self._cond.notify_all()
        return count

    def clear_finished(self) -> None:
        with self._cond:
            self._tasks = [t for t in self._tasks if not t.status.finished]

    def is_busy(self) -> bool:
        with self._cond:
            return any(not t.status.finished for t in self._tasks)

    def wait_all(self, poll: float = 0.5) -> None:
        while self.is_busy():
            time.sleep(poll)

    def shutdown(self) -> None:
        self.cancel_all()
        with self._cond:
            self._stopping = True
            self._cond.notify_all()

    # ---------------------------------------------------------------- internals
    @staticmethod
    def _reset(task: DownloadTask) -> None:
        task.status = Status.QUEUED
        task.message = ""
        task.speed = 0.0
        task.bytes_done = 0
        task.segments_done = 0
        task._speed_window.clear()
        task.cloudflare_blocked = False
        task.cancel_event = threading.Event()

    def _dispatch_loop(self) -> None:
        while True:
            with self._cond:
                while not self._stopping and (
                    self._active >= self.settings.max_parallel_episodes
                    or not any(t.status == Status.QUEUED for t in self._tasks)
                ):
                    self._cond.wait(timeout=1.0)
                if self._stopping:
                    return
                task = next(t for t in self._tasks if t.status == Status.QUEUED)
                task.status = Status.RESOLVING
                self._active += 1
            threading.Thread(target=self._run_task, args=(task,), name=f"task-{task.id}", daemon=True).start()

    def _run_task(self, task: DownloadTask) -> None:
        try:
            self._process(task)
        except Cancelled:
            task.status = Status.CANCELLED
            task.message = "Cancelled"
        except CloudflareChallenge as exc:
            task.status = Status.FAILED
            task.cloudflare_blocked = True
            task.message = str(exc)
            if self.on_cloudflare:
                self.on_cloudflare()
        except Exception as exc:  # noqa: BLE001 - surface every failure in the UI
            task.status = Status.CANCELLED if task.cancel_event.is_set() else Status.FAILED
            task.message = "Cancelled" if task.cancel_event.is_set() else str(exc)
        finally:
            task.speed = 0.0
            with self._cond:
                self._active -= 1
                self._cond.notify_all()

    def _check_cancel(self, task: DownloadTask) -> None:
        if task.cancel_event.is_set():
            raise Cancelled()

    def _process(self, task: DownloadTask) -> None:
        settings = self.settings
        task.status = Status.RESOLVING
        task.message = "Reading episode page"
        sources = self.api.sources(task.anime_session, task.episode.session)
        source = choose_source(sources, settings.quality, settings.audio, settings.prefer_non_av1)
        if source is None:
            raise RuntimeError("No playable source found")
        task.source_label = source.label

        final_mp4 = build_output_path(settings, task.anime_title, task.episode, source.resolution, source.audio)
        final_ts = final_mp4.with_suffix(".ts")
        for existing in (final_mp4, final_ts):
            if existing.exists() and existing.stat().st_size > 0:
                task.status = Status.SKIPPED
                task.output_path = str(existing)
                task.message = ""
                return

        self._check_cancel(task)
        task.message = "Resolving stream"
        stream = kwik.resolve(self.api.http, source.url, self.api.referer)
        segments = load_media_playlist(self.api.http, stream.playlist_url, stream.referer)
        task.segments_total = len(segments)

        work_dir = Path(settings.download_dir) / ".parts" / sanitize_filename(
            f"{task.anime_session[:8]}-{task.episode.session[:12]}-{source.resolution}-{source.audio}"
        )

        def on_progress(done: int, total: int, added: int) -> None:
            now = time.monotonic()
            task.segments_done, task.segments_total = done, total
            if added:
                task.bytes_done += added
                window = task._speed_window
                window.append((now, added))
                while window and now - window[0][0] > 5:
                    window.pop(0)
                span = max(now - window[0][0], 1.0)
                task.speed = sum(b for _, b in window) / span

        task.status = Status.DOWNLOADING
        task.message = ""
        combined = work_dir / "combined.ts"
        HlsDownloader(
            self.api.http, segments, stream.referer, work_dir,
            workers=settings.segment_workers, cancel_event=task.cancel_event, progress=on_progress,
        ).download(combined)

        self._check_cancel(task)
        task.status = Status.MUXING
        task.speed = 0.0
        final_mp4.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = find_ffmpeg(settings.ffmpeg_path)
        output = final_mp4
        if ffmpeg:
            task.message = "Converting to MP4"
            try:
                remux_to_mp4(ffmpeg, combined, final_mp4)
            except RuntimeError as exc:
                output = final_ts
                shutil.move(str(combined), output)
                task.message = f"Saved as .ts ({exc})"
        else:
            output = final_ts
            shutil.move(str(combined), output)
            task.message = "Saved as .ts (install ffmpeg for .mp4)"
        shutil.rmtree(work_dir, ignore_errors=True)
        try:
            (Path(settings.download_dir) / ".parts").rmdir()
        except OSError:
            pass
        task.output_path = str(output)
        task.status = Status.DONE
        if output == final_mp4:
            task.message = ""
