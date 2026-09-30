"""Main window: sidebar navigation + Search & Discover / Download Queue / Settings pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from .. import __version__
from ..animepahe import AnimePahe
from ..config import Settings
from ..downloader import DownloadManager
from ..http import DEFAULT_USER_AGENT, CloudflareChallenge, HttpClient
from ..utils import find_ffmpeg, open_in_file_manager
from .queue_page import QueuePage
from .search_page import SearchPage
from .settings_page import SettingsPage
from .theme import app_icon, line_icon
from .verify_dialog import VerifyDialog
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
        self.jobs = JobRunner(self)
        self._images: dict[str, QPixmap] = {}
        self._cf_prompt_pending = False
        self._verifying = False
        self.cloudflare_needed.connect(self._cloudflare_prompt, Qt.ConnectionType.QueuedConnection)
        self.manager = DownloadManager(self.api, self.settings, on_cloudflare=self._cloudflare_from_thread)

        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        if not find_ffmpeg(self.settings.ffmpeg_path):
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
        self.queue_page = QueuePage(self)
        self.settings_page = SettingsPage(self)
        self.settings_page.saved.connect(self._settings_saved)

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for index, (label, icon, page) in enumerate((
            ("Search && Discover", "search", self.search_page),  # '&&' = literal '&' in Qt buttons
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
        version = QLabel(f"Version {__version__}")
        version.setObjectName("appVersion")
        side.addWidget(version)

        layout.addWidget(sidebar)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        self.go_to(0)

    def go_to(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        if self.pages.currentWidget() is self.settings_page:
            self.settings_page.load()
        elif self.pages.currentWidget() is self.search_page:
            self.search_page.input.setFocus()

    def show_queue(self) -> None:
        self.go_to(1)

    def _tick(self) -> None:
        active = self.queue_page.refresh()
        self.nav_buttons[1].setText(f"  Download Queue ({active})" if active else "  Download Queue")

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
                if self.verify() and retry:
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

        self.jobs.submit(lambda: self.http.get_bytes(url, referer=self.api.referer, retries=1), done,
                         lambda _exc: None)

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
        if self.verify():
            self.manager.retry_failed(only_cloudflare=True)

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
            self.settings.cookies.update(dialog.cookies)
            if dialog.user_agent:
                self.settings.user_agent = dialog.user_agent
            self.settings.save()
            self.http.set_identity(self.settings.user_agent, self.settings.cookies)
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
        self.http.set_identity(self.settings.user_agent or None, self.settings.cookies)
        self.notify("Settings saved.")

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
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
        event.accept()
