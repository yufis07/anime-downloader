"""Main window: sidebar navigation + Search & Discover / Download Queue / Settings pages."""

from __future__ import annotations

import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from .. import __version__
from ..animeheaven import AnimeHeaven
from ..animepahe import AnimePahe
from ..config import Settings
from ..details import DetailsClient
from ..discover import DiscoverClient
from ..downloader import DownloadManager
from ..library import Library
from ..notifications import QueueWatcher
from ..updates import CHECK_INTERVAL, UpdateCheck, check_for_update, current_build
from ..http import DEFAULT_USER_AGENT, CloudflareChallenge, HttpClient
from ..utils import find_ffmpeg, format_speed, open_in_file_manager
from .queue_page import QueuePage
from .search_page import SearchPage
from .settings_page import SettingsPage
from .setup_wizard import SetupWizard
from .theme import app_icon, line_icon
from .verify_dialog import VerifyDialog
from .tray import TrayController
from .update_banner import UpdateBanner
from .watchlist_page import WatchlistPage
from .workers import JobRunner


class MainWindow(QMainWindow):
    cloudflare_needed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Anime Downloader")
        self.resize(1320, 840)
        self.setMinimumSize(980, 620)

        self.settings = Settings.load()
        self.http = HttpClient(self.settings.user_agent, self.settings.cookies)
        self.api = AnimePahe(self.http, self.settings.base_url)
        # AnimeHeaven gets its own client so it never carries AnimePahe's Cloudflare cookies.
        self.http_heaven = HttpClient()
        self.heaven = AnimeHeaven(self.http_heaven, self.settings.animeheaven_url)
        self.jobs = JobRunner(self)
        self.library = Library()
        self.http_updates = HttpClient(retries=1, timeout=15.0)
        self.build = current_build()
        self.details = DetailsClient()
        self.discover = DiscoverClient()
        self._images: dict[str, QPixmap] = {}
        self._cf_prompt_pending = False
        self._verifying = False
        self._last_verified = 0.0  # monotonic time of the last successful browser check
        self.cloudflare_needed.connect(self._cloudflare_prompt, Qt.ConnectionType.QueuedConnection)
        self.manager = DownloadManager(self.api, self.settings, on_cloudflare=self._cloudflare_from_thread,
                                    animeheaven=self.heaven, on_episode_done=self._record_download)

        self.tray = TrayController(self)  # before the pages: Settings asks whether a tray exists
        self._build_ui()
        self.watcher = QueueWatcher()
        self._quitting = False
        self._tray_hint_shown = False
        self.tray.open_requested.connect(self.bring_to_front)
        self.tray.pause_toggled.connect(self._toggle_pause_from_tray)
        self.tray.quit_requested.connect(self.quit_app)
        self.tray.message_clicked.connect(self._tray_message_clicked)
        self._apply_tray_settings()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        self._ticks = 0
        QTimer.singleShot(6000, lambda: self.check_for_updates(automatic=True))
        if self.library.shows():  # look for new episodes shortly after start-up
            QTimer.singleShot(4000, lambda: self.watchlist_page.check(quiet=True))
        if not self.settings.setup_done:
            QTimer.singleShot(300, self.run_setup)
        elif not find_ffmpeg(self.settings.ffmpeg_path):
            self.notify("Tip: install ffmpeg (winget install Gyan.FFmpeg) to get .mp4 files instead of .ts.", 0)

    # ================================================================== layout
    def _build_ui(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(276)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 20, 14, 16)
        side.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(30, 30))
        name = QLabel("Anime Downloader")
        name.setObjectName("appName")
        brand.addWidget(logo)
        brand.addWidget(name, 1)
        side.addLayout(brand)
        side.addSpacing(22)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        self.search_page = SearchPage(self)
        self.watchlist_page = WatchlistPage(self)
        self.queue_page = QueuePage(self)
        self.settings_page = SettingsPage(self)
        self.settings_page.saved.connect(self._settings_saved)

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for index, (label, icon, page) in enumerate((
            ("Search && Discover", "search", self.search_page),  # '&&' = literal '&' in Qt buttons
            ("Watchlist", "bookmark", self.watchlist_page),
            ("Download Queue", "download", self.queue_page),
            ("Settings", "settings", self.settings_page),
        )):
            self.pages.addWidget(page)
            button = QPushButton("  " + label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setIcon(line_icon(icon))
            button.setIconSize(QSize(20, 20))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _c=False, i=index: self.go_to(i))
            self.nav.addButton(button, index)
            self.nav_buttons.append(button)
            side.addWidget(button)
        side.addStretch(1)

        verify = QPushButton("  Cloudflare check")
        verify.setObjectName("navButton")
        verify.setIcon(line_icon("shield"))
        verify.setIconSize(QSize(18, 18))
        verify.setToolTip("Open the site in a browser window to pass the 'verify you are human' check")
        verify.clicked.connect(lambda: self.verify())
        side.addWidget(verify)
        version = QLabel(f"Version {__version__}" + (f" (build {self.build[:7]})" if self.build else " (source)"))
        version.setObjectName("appVersion")
        side.addWidget(version)

        layout.addWidget(sidebar)
        self.update_banner = UpdateBanner()
        self.update_banner.download_requested.connect(webbrowser.open)
        self.update_banner.dismissed.connect(self._update_dismissed)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self.update_banner)
        content.addWidget(self.pages, 1)
        layout.addLayout(content, 1)
        self.setCentralWidget(root)
        self.go_to(0)

    def go_to(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        if self.pages.currentWidget() is self.settings_page:
            self.settings_page.load()
        elif self.pages.currentWidget() is self.watchlist_page:
            self.watchlist_page.refresh()
        elif self.pages.currentWidget() is self.search_page:
            self.search_page.input.setFocus()

    def show_queue(self) -> None:
        self.go_to(self.pages.indexOf(self.queue_page))

    def open_anime(self, anime) -> None:  # type: ignore[no-untyped-def]
        """Show the episode list of ``anime`` in Search & Discover."""
        self.go_to(self.pages.indexOf(self.search_page))
        self.search_page.open_anime(anime)

    def _record_download(self, task) -> None:  # type: ignore[no-untyped-def]
        """Called from a download thread when an episode is on disk."""
        self.library.record_download(task.site, task.anime_session, task.episode.number, task.output_path)

    def check_for_updates(self, automatic: bool = False, on_result: Callable[[UpdateCheck], None] | None = None,
                          on_error: Callable[[Exception], None] | None = None) -> None:
        """Compare this build with the latest release in the background.

        ``automatic`` checks respect the setting and run at most every few hours; an update the user
        already dismissed does not show the banner again."""
        settings = self.settings
        if automatic and (not settings.check_updates or not self.build
                          or time.time() - settings.last_update_check < CHECK_INTERVAL):
            return

        def done(result: UpdateCheck) -> None:
            settings.last_update_check = time.time()
            settings.save()
            if result.status == "available" and result.info:
                if not (automatic and result.info.sha == settings.dismissed_update):
                    self.update_banner.show_update(result.info)
            else:
                self.update_banner.hide()
            if on_result:
                on_result(result)

        def failed(exc: Exception) -> None:
            if on_error:
                on_error(exc)

        self.jobs.submit(lambda: check_for_update(self.http_updates, self.build, settings.update_token), done, failed)

    # ================================================================== first-run setup
    def run_setup(self) -> None:
        """The welcome wizard (also available from Settings)."""
        SetupWizard(self).exec()
        self.settings_page.load()

    def settings_applied(self) -> None:
        """Settings changed from outside the Settings page (the wizard): refresh everything that caches them."""
        self._settings_saved()
        self.search_page.site.setCurrentIndex(max(0, self.search_page.site.findData(self.settings.site)))

    # ================================================================== tray
    def _apply_tray_settings(self) -> None:
        """Show or hide the tray icon and decide whether closing the window quits the app."""
        self.tray.set_enabled(self.settings.tray_icon)
        to_tray = self.settings.close_to_tray and self.tray.visible
        QApplication.instance().setQuitOnLastWindowClosed(not to_tray)

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_message_clicked(self, target: str) -> None:
        self.bring_to_front()
        self.go_to(self.pages.indexOf(self.watchlist_page if target == "watchlist" else self.queue_page))

    def _toggle_pause_from_tray(self) -> None:
        if self.manager.paused:
            self.manager.resume_all()
        else:
            self.manager.pause_all()
        self.queue_page.refresh()

    def quit_app(self) -> None:
        self._quitting = True
        self.bring_to_front()
        self.close()
        self._quitting = False  # the user declined the "downloads in progress" question

    def notify_new_episodes(self, title: str, message: str) -> None:
        if self.settings.notify_new_episodes and not self.isActiveWindow():
            self.tray.notify(title, message, target="watchlist")

    def _update_dismissed(self, sha: str) -> None:
        self.settings.dismissed_update = sha
        self.settings.save()

    def update_watchlist_badge(self) -> None:
        new = self.library.total_new()
        index = self.pages.indexOf(self.watchlist_page)
        self.nav_buttons[index].setText(f"  Watchlist ({new} new)" if new else "  Watchlist")

    def _tick(self) -> None:
        active = self.queue_page.refresh()
        index = self.pages.indexOf(self.queue_page)
        self.nav_buttons[index].setText(f"  Download Queue ({active})" if active else "  Download Queue")
        tasks = self.manager.snapshot()
        speed = 0.0 if self.manager.paused else sum(t.speed for t in tasks)
        self.tray.set_status(active, format_speed(speed), self.manager.paused)
        summary = self.watcher.update(tasks)
        if summary and self.settings.notify_finished and not self.isActiveWindow():
            self.tray.notify(*summary.text(), target="queue")
        self._ticks += 1
        if self._ticks % 20 == 0:  # downloads are recorded from other threads, so refresh now and then
            self.update_watchlist_badge()

    # ================================================================== services used by pages
    def notify(self, message: str, timeout_ms: int = 6000) -> None:
        self.statusBar().showMessage(message, timeout_ms)

    def run(self, fn: Callable[[], Any], on_success: Callable[[Any], None], retry: Callable[[], None] | None = None,
            on_error: Callable[[], None] | None = None) -> None:
        """Run ``fn`` in the background; on a Cloudflare block, verify and call ``retry``."""

        def failed(exc: Exception) -> None:
            if on_error:
                on_error()
            if isinstance(exc, CloudflareChallenge):
                if self._verify_after_block() and retry:
                    retry()
                return
            QMessageBox.warning(self, "Something went wrong", str(exc) or exc.__class__.__name__)

        self.jobs.submit(fn, on_success, failed)

    def load_image(self, url: str, owner: QWidget, callback: Callable[[QPixmap], None]) -> None:
        """Fetch an image (cached) and hand it to ``callback`` if ``owner`` still exists."""
        if url in self._images:
            callback(self._images[url])
            return

        def done(data: bytes) -> None:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self._images[url] = pixmap
                if isValid(owner):
                    callback(pixmap)

        client, referer = ((self.http_heaven, self.heaven.referer) if url.startswith(self.heaven.base_url)
                           else (self.http, self.api.referer))
        self.jobs.submit(lambda: client.get_bytes(url, referer=referer, retries=1), done,
                         lambda _exc: None)

    def provider(self, site: str):  # type: ignore[no-untyped-def]
        """The site client (AnimePahe or AnimeHeaven) for an ``Anime.site`` value."""
        return self.heaven if site == "animeheaven" else self.api

    def open_download_folder(self) -> None:
        path = Path(self.settings.download_dir)
        path.mkdir(parents=True, exist_ok=True)
        open_in_file_manager(path)

    # ================================================================== Cloudflare
    def _cloudflare_from_thread(self) -> None:
        if not self._cf_prompt_pending:  # called from a download thread
            self._cf_prompt_pending = True
            self.cloudflare_needed.emit()

    def _cloudflare_prompt(self) -> None:
        self._cf_prompt_pending = False
        if self._verify_after_block():
            self.manager.retry_failed(only_cloudflare=True)

    def _verify_after_block(self) -> bool:
        """Open the check window after a block, but never straight after a check that just 'passed'.

        If the site blocks the app again within a minute of a successful check, reopening the window
        would only loop. Explain what to try instead.
        """
        if time.monotonic() - self._last_verified < 60:
            QMessageBox.warning(
                self, "Cloudflare is still blocking the app",
                "The browser check passed, but the site still refuses the app's requests.\n\n"
                "Try this:\n"
                "1. Click Cloudflare check in the sidebar, then Reset browser data, and pass the check again.\n"
                "2. Turn off any VPN or proxy.\n"
                "3. In the check window, use Enter cookie manually with the cookie and User-Agent from "
                "Chrome or Edge.\n\n"
                "If the check also loops in your normal browser, the site is under heavy protection right "
                "now. Wait a while and try again.",
            )
            return False
        return self.verify()

    def verify(self) -> bool:
        if self._verifying:
            return False
        self._verifying = True
        try:
            dialog = VerifyDialog(self.settings.base_url, self)
            accepted = dialog.exec()
            dialog.deleteLater()
            if not accepted:
                return False
            if getattr(dialog, "reset_requested", False):
                self.settings.cookies = {}
                self.http.cookies = {}
            self.settings.cookies.update(dialog.cookies)
            if dialog.user_agent:
                self.settings.user_agent = dialog.user_agent
            self.settings.save()
            self.http.set_identity(self.settings.user_agent, self.settings.cookies)
            self._last_verified = time.monotonic()
            self.notify("Browser check saved.")
            return True
        finally:
            self._verifying = False

    def reset_identity(self) -> None:
        self.http.cookies = {}
        self.http.user_agent = DEFAULT_USER_AGENT
        self.http.set_identity(self.settings.user_agent or None, self.settings.cookies)
        self.notify("Cloudflare cookies cleared.")

    # ================================================================== settings / lifecycle
    def _settings_saved(self) -> None:
        if self.api.base_url != self.settings.base_url:
            self.api.set_base_url(self.settings.base_url)
        if self.heaven.base_url != self.settings.animeheaven_url:
            self.heaven.set_base_url(self.settings.animeheaven_url)
        self.http.set_identity(self.settings.user_agent or None, self.settings.cookies)
        self._apply_tray_settings()
        self.notify("Settings saved.")

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if not self._quitting and self.settings.close_to_tray and self.tray.visible:
            self.hide()  # keep downloading; "Quit" in the tray menu really exits
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify("Still running", "Anime Downloader keeps working in the tray. "
                                                  "Right-click the icon to quit.")
            event.ignore()
            return
        if self.manager.is_busy():
            answer = QMessageBox.question(
                self, "Downloads in progress",
                "Downloads are still running. Quit anyway? Finished pieces are kept and resume next time.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.manager.shutdown()
        self.settings.save()
        self.tray.set_enabled(False)
        event.accept()
        QApplication.instance().quit()
