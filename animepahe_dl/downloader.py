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
from .mal import MalLookup
from .utils import find_ffmpeg, format_episode, sanitize_filename


class Status(str, Enum):
    QUEUED = "Queued"
    RESOLVING = "Resolving"
    DOWNLOADING = "Downloading"
    MUXING = "Stitching via FFmpeg"
    DONE = "Completed"
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
    message: str = ""
    output_path: str = ""
    cloudflare_blocked: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _speed_window: list[tuple[float, int]] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    SPEED_WINDOW = 5.0  # seconds

    def record_bytes(self, count: int) -> None:
        now = time.monotonic()
        with self._lock:
            self.bytes_done += count
            self._speed_window.append((now, count))
            self._trim(now)

    def _trim(self, now: float) -> None:
        while self._speed_window and now - self._speed_window[0][0] > self.SPEED_WINDOW:
            self._speed_window.pop(0)

    @property
    def speed(self) -> float:
        """Average bytes/second over the last few seconds (0 when nothing is flowing)."""
        if self.status != Status.DOWNLOADING:
            return 0.0
        now = time.monotonic()
        with self._lock:
            self._trim(now)
            if not self._speed_window:
                return 0.0
            span = max(now - self._speed_window[0][0], 1.0)
            return sum(b for _, b in self._speed_window) / span

    def reset_progress(self) -> None:
        with self._lock:
            self.bytes_done = 0
            self.segments_done = 0
            self._speed_window.clear()

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


def move_target(settings: Settings, japanese_title: str, episode: Episode, resolution: int,
                audio: str, current: Path) -> Path:
    return build_output_path(settings, japanese_title, episode, resolution, audio, current.suffix)


def move_to_japanese_name(settings: Settings, japanese_title: str, episode: Episode, resolution: int,
                          audio: str, current: Path) -> Path:
    """Move a finished download to the folder/file name built from the Japanese (romaji) title.

    Files are moved one by one (not the whole folder) so episodes still downloading into the
    old folder are not disturbed; the old folder is removed once it is empty. An existing file
    at the destination is never overwritten.
    """
    target = move_target(settings, japanese_title, episode, resolution, audio, current)
    if target == current:
        return current
    if target.exists():
        raise FileExistsError(f"{target.name} already exists in the Japanese-named folder")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(current, target)
    try:
        current.parent.rmdir()
    except OSError:
        pass  # other episodes are still in the old folder
    return target


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
        lines = [line.strip() for line in proc.stderr.splitlines() if line.strip()]
        raise RuntimeError(f"ffmpeg failed: {lines[-1][:200] if lines else f'exit code {proc.returncode}'}")
    os.replace(tmp, target)


class DownloadManager:
    """Thread-based download queue. The GUI polls :meth:`snapshot` to render progress."""

    def __init__(self, api: AnimePahe, settings: Settings,
                 on_cloudflare: Callable[[], None] | None = None, mal: MalLookup | None = None) -> None:
        self.api = api
        self.settings = settings
        self._mal = mal
        self._japanese_cache: dict[str, str | None] = {}
        self._japanese_error = ""  # reason of the last failed lookup, shown on the task
        self._mal_lock = threading.Lock()  # also keeps Jikan requests to one at a time
        self.on_cloudflare = on_cloudflare
        self._tasks: list[DownloadTask] = []
        self._cond = threading.Condition()
        self._active = 0
        self._stopping = False
        self._run_gate = threading.Event()  # cleared while paused
        self._run_gate.set()
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

    @property
    def paused(self) -> bool:
        return not self._run_gate.is_set()

    def pause_all(self) -> None:
        """Stop starting new episodes and hold running ones between segments."""
        self._run_gate.clear()

    def resume_all(self) -> None:
        self._run_gate.set()
        with self._cond:
            self._cond.notify_all()

    def is_busy(self) -> bool:
        with self._cond:
            return any(not t.status.finished for t in self._tasks)

    def wait_all(self, poll: float = 0.5) -> None:
        while self.is_busy():
            time.sleep(poll)

    def shutdown(self) -> None:
        self.cancel_all()
        self._run_gate.set()  # release anything waiting on pause
        with self._cond:
            self._stopping = True
            self._cond.notify_all()

    # ---------------------------------------------------------------- internals
    @staticmethod
    def _reset(task: DownloadTask) -> None:
        task.status = Status.QUEUED
        task.message = ""
        task.reset_progress()
        task.cloudflare_blocked = False
        task.cancel_event = threading.Event()

    def _dispatch_loop(self) -> None:
        while True:
            with self._cond:
                while not self._stopping and (
                    self.paused
                    or self._active >= self.settings.max_parallel_episodes
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
            with self._cond:
                self._active -= 1
                self._cond.notify_all()

    def japanese_title(self, anime_title: str) -> str | None:
        """Japanese (romaji) title from MyAnimeList (cached per anime); None when unavailable."""
        with self._mal_lock:
            if anime_title in self._japanese_cache:
                return self._japanese_cache[anime_title]
            try:
                if self._mal is None:
                    self._mal = MalLookup()
                match = self._mal.japanese_title(anime_title)
            except Exception as exc:  # noqa: BLE001 - lookup is optional; keep the English name
                self._japanese_error = str(exc)
                return None  # not cached, so the next episode tries again
            self._japanese_error = ""
            title = match.title if match else None
            self._japanese_cache[anime_title] = title
            return title

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
        japanese = self.japanese_title(task.anime_title) if settings.rename_japanese else None
        candidates = [final_mp4, final_ts]
        if japanese:
            jp_mp4 = build_output_path(settings, japanese, task.episode, source.resolution, source.audio)
            candidates += [jp_mp4, jp_mp4.with_suffix(".ts")]
        for existing in candidates:
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
            task.segments_done, task.segments_total = done, total
            if added:
                task.record_bytes(added)

        task.status = Status.DOWNLOADING
        task.message = ""
        combined = work_dir / "combined.ts"
        HlsDownloader(
            self.api.http, segments, stream.referer, work_dir,
            workers=settings.segment_workers, cancel_event=task.cancel_event, progress=on_progress,
            pause_gate=self._run_gate,
        ).download(combined)

        self._check_cancel(task)
        task.status = Status.MUXING
        final_mp4.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = find_ffmpeg(settings.ffmpeg_path)
        output = final_mp4
        if ffmpeg:
            task.message = "Joining segments into MP4"
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
        if output == final_mp4:
            task.message = ""
        if settings.rename_japanese:
            japanese = japanese or self.japanese_title(task.anime_title)
            if japanese:
                if output == move_target(settings, japanese, task.episode, source.resolution, source.audio, output):
                    task.message = f"Name already matches MyAnimeList title ({japanese})"
                try:
                    output = move_to_japanese_name(settings, japanese, task.episode, source.resolution,
                                                   source.audio, output)
                except OSError as exc:
                    task.message = f"Kept English name ({exc})"
            else:
                reason = (f"MyAnimeList lookup failed: {self._japanese_error}" if self._japanese_error
                          else "no match found on MyAnimeList")
                task.message = f"Kept original name ({reason})"
        task.output_path = str(output)
        task.status = Status.DONE
