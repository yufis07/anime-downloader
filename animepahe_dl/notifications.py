"""When to tell the user something happened (no GUI code, so it can be tested)."""

from __future__ import annotations

from dataclasses import dataclass

from .downloader import DownloadTask, Status
from .utils import format_episode


@dataclass
class QueueSummary:
    done: int = 0
    skipped: int = 0
    failed: int = 0
    title: str = ""  # "Show - Episode 03" when exactly one episode was downloaded
    error: str = ""  # the message of the failure when exactly one episode failed

    @property
    def worth_telling(self) -> bool:
        return self.done + self.failed > 0

    def text(self) -> tuple[str, str]:
        """(notification title, notification message)."""
        total = self.done + self.failed
        if total == 1 and self.title:
            if self.failed:
                return "Download failed", f"{self.title}\n{self.error}".strip()
            return "Download finished", self.title
        bits = []
        if self.done:
            bits.append(f"{self.done} completed")
        if self.failed:
            bits.append(f"{self.failed} failed")
        if self.skipped:
            bits.append(f"{self.skipped} already downloaded")
        return ("Downloads finished" if not self.failed else "Downloads finished with errors"), ", ".join(bits)


class QueueWatcher:
    """Reports once each time the download queue goes from busy to idle."""

    def __init__(self) -> None:
        self._tracked: dict[int, DownloadTask] = {}

    def update(self, tasks: list[DownloadTask]) -> QueueSummary | None:
        for task in tasks:
            if not task.status.finished:
                self._tracked[task.id] = task
        if not self._tracked or any(not t.status.finished for t in tasks):
            return None
        summary = QueueSummary()
        for task in self._tracked.values():
            if task.status == Status.DONE:
                summary.done += 1
            elif task.status == Status.SKIPPED:
                summary.skipped += 1
            elif task.status == Status.FAILED:
                summary.failed += 1  # cancelled downloads are not reported
        if len(self._tracked) == 1:
            only = next(iter(self._tracked.values()))
            summary.title = f"{only.anime_title} — Episode {format_episode(only.episode.number)}"
            summary.error = only.message if only.status == Status.FAILED else ""
        self._tracked.clear()
        return summary if summary.worth_telling else None


def new_episodes_text(total_new: int, followed_with_new: list[str]) -> tuple[str, str]:
    """Notification for the start-up watchlist check."""
    title = "New episodes" if total_new != 1 else "New episode"
    names = ", ".join(followed_with_new[:3]) + (f" and {len(followed_with_new) - 3} more"
                                                 if len(followed_with_new) > 3 else "")
    return title, f"{total_new} new in your watchlist: {names}" if names else f"{total_new} new in your watchlist"
