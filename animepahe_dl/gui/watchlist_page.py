"""'Watchlist': followed shows with "new episode" badges, one-click download of what is new."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..animepahe import Anime
from ..config import SITE_LABELS
from ..library import Followed
from ..notifications import new_episodes_text
from ..utils import format_episode
from .theme import emphasize, placeholder_poster, repolish, rounded_pixmap
from .widgets import ElidedLabel

if TYPE_CHECKING:
    from .main_window import MainWindow


def _ago(timestamp: float) -> str:
    if not timestamp:
        return "never checked"
    seconds = max(0, time.time() - timestamp)
    for unit, size in (("d", 86400), ("h", 3600), ("min", 60)):
        if seconds >= size:
            return f"checked {int(seconds // size)} {unit} ago"
    return "checked just now"


class WatchRow(QFrame):
    POSTER_W, POSTER_H = 58, 82

    def __init__(self, page: "WatchlistPage", show: Followed, new: list[float]) -> None:
        super().__init__()
        self.setObjectName("queueRow")
        self.show_ = show
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 12, 16, 12)
        outer.setSpacing(14)

        self.poster = QLabel()
        self.poster.setFixedSize(self.POSTER_W, self.POSTER_H)
        self.poster.setPixmap(placeholder_poster(show.title, self.POSTER_W, self.POSTER_H))
        outer.addWidget(self.poster)

        text = QVBoxLayout()
        text.setSpacing(3)
        title = ElidedLabel(show.title)
        title.setObjectName("sectionTitle")
        bits = [SITE_LABELS.get(show.site, show.site)]
        if show.available:
            bits.append(f"{len(show.available)} episodes")
        bits.append(_ago(show.checked_at))
        meta = QLabel("  ·  ".join(bits))
        meta.setObjectName("muted")
        text.addWidget(title)
        text.addWidget(meta)
        if show.error:
            problem = ElidedLabel("Could not check: " + show.error)
            problem.setObjectName("muted")
            text.addWidget(problem)
        elif new:
            numbers = ", ".join(format_episode(n, 1) for n in new[:8]) + ("…" if len(new) > 8 else "")
            text.addWidget(QLabel(f"New: episode {numbers}" if len(new) == 1 else f"New: episodes {numbers}"))
        text.addStretch(1)
        outer.addLayout(text, 1)

        if new:
            badge = emphasize(QLabel(f"{len(new)} new"))
            badge.setObjectName("pill")
            badge.setProperty("state", "downloading")
            repolish(badge)
            outer.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

        open_btn = QPushButton("Open")
        open_btn.clicked.connect(lambda: page.open_show(show))
        outer.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        if new:
            get = emphasize(QPushButton(f"Download {len(new)} new"))
            get.setObjectName("primary")
            get.clicked.connect(lambda: page.download_new([show]))
            outer.addWidget(get, 0, Qt.AlignmentFlag.AlignVCenter)
        unfollow = QPushButton("Unfollow")
        unfollow.setObjectName("ghost")
        unfollow.clicked.connect(lambda: page.unfollow(show))
        outer.addWidget(unfollow, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_cover(self, pixmap) -> None:  # type: ignore[no-untyped-def]
        self.poster.setPixmap(rounded_pixmap(pixmap, self.POSTER_W, self.POSTER_H, 6))


class WatchlistPage(QWidget):
    def __init__(self, ctx: "MainWindow") -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName("page")
        self._checking = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Watchlist")
        title.setObjectName("pageTitle")
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        titles.addWidget(title)
        titles.addWidget(self.summary)
        header.addLayout(titles, 1)
        self.check_btn = QPushButton("Check for new episodes")
        self.check_btn.clicked.connect(self.check)
        self.all_btn = emphasize(QPushButton("Download all new"))
        self.all_btn.setObjectName("primary")
        self.all_btn.clicked.connect(lambda: self.download_new(self.ctx.library.shows()))
        for btn in (self.check_btn, self.all_btn):
            header.addWidget(btn, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("scrollBody")
        self.list_layout = QVBoxLayout(body)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(10)
        self.empty = QLabel("You are not following any show yet.\n"
                            "Open a show in Search & Discover and click “Follow” to be told about new episodes.")
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll, 1)

    # ------------------------------------------------------------------ view
    def refresh(self) -> None:
        library = self.ctx.library
        while self.list_layout.count() > 2:  # keep the empty-state label and the trailing stretch
            item = self.list_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        shows = library.shows()
        self.empty.setVisible(not shows)
        total_new = 0
        for index, show in enumerate(shows):
            new = library.new_numbers(show)
            total_new += len(new)
            row = WatchRow(self, show, new)
            self.list_layout.insertWidget(1 + index, row)
            if show.poster:
                self.ctx.load_image(show.poster, row, row.set_cover)
        checked = max((s.checked_at for s in shows), default=0.0)
        if shows:
            self.summary.setText(f"{len(shows)} followed  ·  {total_new} new episode{'s' if total_new != 1 else ''}"
                                 f"  ·  {_ago(checked)}")
        else:
            self.summary.setText("")
        self.all_btn.setVisible(total_new > 0)
        self.all_btn.setText(f"Download all {total_new} new")
        self.check_btn.setEnabled(bool(shows) and not self._checking)
        self.ctx.update_watchlist_badge()

    # ------------------------------------------------------------------ actions
    def check(self, quiet: bool = False) -> None:
        """Ask every site for the current episode list of each followed show (in the background)."""
        if self._checking or not self.ctx.library.shows():
            return
        self._checking = True
        self.check_btn.setEnabled(False)
        self.check_btn.setText("Checking…")

        def episodes_of(site: str, session: str) -> list[float]:
            return [e.number for e in self.ctx.provider(site).episodes(session)]

        def done(total_new: int) -> None:
            self._finish_check()
            if total_new and not quiet:
                self.ctx.notify(f"{total_new} new episode(s) in your watchlist.")
            elif total_new:
                self.ctx.notify(f"Watchlist: {total_new} new episode(s) available.", 10000)
                library = self.ctx.library
                names = [s.title for s in library.shows() if library.new_numbers(s)]
                self.ctx.notify_new_episodes(*new_episodes_text(total_new, names))

        def failed(_exc: Exception) -> None:
            self._finish_check()

        self.ctx.jobs.submit(lambda: self.ctx.library.check_all(episodes_of), done, failed)

    def _finish_check(self) -> None:
        self._checking = False
        self.check_btn.setText("Check for new episodes")
        self.refresh()

    def open_show(self, show: Followed) -> None:
        self.ctx.open_anime(Anime(session=show.session, title=show.title, poster=show.poster, site=show.site))

    def unfollow(self, show: Followed) -> None:
        self.ctx.library.unfollow(show.site, show.session)
        self.refresh()

    def download_new(self, shows: list[Followed]) -> None:
        wanted = [(s, set(self.ctx.library.new_numbers(s))) for s in shows]
        wanted = [(s, nums) for s, nums in wanted if nums]
        if not wanted:
            return

        def work() -> int:
            queued = 0
            for show, numbers in wanted:
                episodes = [e for e in self.ctx.provider(show.site).episodes(show.session) if e.number in numbers]
                added = self.ctx.manager.add(show.title, show.session, episodes, site=show.site, poster=show.poster)
                self.ctx.library.acknowledge(show.site, show.session, [e.number for e in episodes])
                queued += len(added)
            return queued

        def done(queued: int) -> None:
            self.refresh()
            self.ctx.notify(f"Added {queued} new episode(s) to the queue.")
            self.ctx.show_queue()

        self.ctx.run(work, done)
