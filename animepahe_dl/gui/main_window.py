"""Main application window: search, browse episodes, queue downloads, watch progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from .. import __version__
from ..animepahe import Anime, AnimePahe, Episode, parse_anime_session
from ..config import AUDIO_CHOICES, QUALITIES, Settings
from ..downloader import DownloadManager, DownloadTask, Status
from ..http import CloudflareChallenge, HttpClient
from ..utils import (
    find_ffmpeg, format_bytes, format_episode, format_speed, open_in_file_manager,
    parse_episode_selection,
)
from .settings_dialog import AUDIO_LABELS, SettingsDialog
from .verify_dialog import VerifyDialog
from .workers import JobRunner

STATUS_COLORS = {
    Status.DONE: "#22c55e",
    Status.SKIPPED: "#22c55e",
    Status.FAILED: "#ef4444",
    Status.CANCELLED: "#9ca3af",
}


class MainWindow(QMainWindow):
    cloudflare_needed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.cloudflare_needed.connect(self._cloudflare_prompt, Qt.ConnectionType.QueuedConnection)
        self.setWindowTitle(f"AnimePahe Downloader {__version__}")
        self.resize(1280, 800)

        self.settings = Settings.load()
        self.http = HttpClient(self.settings.user_agent, self.settings.cookies)
        self.api = AnimePahe(self.http, self.settings.base_url)
        self.jobs = JobRunner(self)
        self._cf_prompt_pending = False
        self.manager = DownloadManager(self.api, self.settings, on_cloudflare=self._cloudflare_from_thread)

        self.current_anime: Anime | None = None
        self.episodes: list[Episode] = []
        self._poster_cache: dict[str, QPixmap] = {}
        self._rows: dict[int, int] = {}  # task id -> row
        self._verifying = False

        self._build_ui()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_downloads)
        self.refresh_timer.start(500)
        self.statusBar().showMessage(
            "Type an anime title or paste an AnimePahe link, then press Enter." if find_ffmpeg(self.settings.ffmpeg_path)
            else "Tip: install ffmpeg (winget install Gyan.FFmpeg) to get .mp4 files instead of .ts."
        )

    # ================================================================== UI construction
    def _build_ui(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(toolbar)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search anime or paste https://animepahe…/anime/<id>")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.search)
        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self.search)
        toolbar.addWidget(self.search_edit)
        toolbar.addWidget(self.search_btn)
        toolbar.addSeparator()
        verify = QAction("Verify in browser", self)
        verify.setToolTip("Open the site to pass the Cloudflare check")
        verify.triggered.connect(lambda: self.verify())
        toolbar.addAction(verify)
        settings = QAction("Settings", self)
        settings.setShortcut(QKeySequence("Ctrl+,"))
        settings.triggered.connect(self.open_settings)
        toolbar.addAction(settings)
        folder = QAction("Open folder", self)
        folder.triggered.connect(self._open_download_folder)
        toolbar.addAction(folder)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_browse_tab(), "Browse")
        self.tabs.addTab(self._build_downloads_tab(), "Downloads")
        self.setCentralWidget(self.tabs)

    def _build_browse_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: search results
        self.results = QListWidget()
        self.results.setMinimumWidth(300)
        self.results.setWordWrap(True)
        self.results.setSpacing(2)
        self.results.currentItemChanged.connect(self._on_result_selected)
        splitter.addWidget(self.results)

        # Right: details + episodes
        right = QWidget()
        rlayout = QVBoxLayout(right)
        header = QHBoxLayout()
        self.poster = QLabel()
        self.poster.setFixedSize(150, 212)
        self.poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster.setStyleSheet("border-radius: 8px; background: rgba(127,127,127,0.15);")
        header.addWidget(self.poster)
        info = QVBoxLayout()
        self.title_label = QLabel("No anime selected")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("color: gray;")
        info.addWidget(self.title_label)
        info.addWidget(self.meta_label)
        info.addStretch(1)
        header.addLayout(info, 1)
        rlayout.addLayout(header)

        self.episode_table = QTableWidget(0, 5)
        self.episode_table.setHorizontalHeaderLabels(["", "Episode", "Title", "Duration", "Added"])
        self.episode_table.verticalHeader().setVisible(False)
        self.episode_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.episode_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.episode_table.setAlternatingRowColors(True)
        hdr = self.episode_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.episode_table.cellDoubleClicked.connect(self._toggle_row)
        rlayout.addWidget(self.episode_table, 1)

        controls = QHBoxLayout()
        select_all = QPushButton("Select all")
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        select_none = QPushButton("Select none")
        select_none.clicked.connect(lambda: self._set_all_checked(False))
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText("e.g. 1-12, 15, 20-")
        self.range_edit.setMaximumWidth(180)
        self.range_edit.returnPressed.connect(self._apply_range)
        apply_range = QPushButton("Select range")
        apply_range.clicked.connect(self._apply_range)
        self.quality_combo = QComboBox()
        for q in QUALITIES:
            self.quality_combo.addItem(f"{q}p", q)
        self.quality_combo.setCurrentIndex(max(0, self.quality_combo.findData(self.settings.quality)))
        self.quality_combo.currentIndexChanged.connect(self._quick_settings_changed)
        self.audio_combo = QComboBox()
        for a in AUDIO_CHOICES:
            self.audio_combo.addItem(AUDIO_LABELS[a], a)
        self.audio_combo.setCurrentIndex(max(0, self.audio_combo.findData(self.settings.audio)))
        self.audio_combo.currentIndexChanged.connect(self._quick_settings_changed)
        self.download_btn = QPushButton("Download selected")
        self.download_btn.setObjectName("primary")
        self.download_btn.clicked.connect(self.download_selected)
        for widget in (select_all, select_none, self.range_edit, apply_range):
            controls.addWidget(widget)
        controls.addStretch(1)
        controls.addWidget(QLabel("Quality"))
        controls.addWidget(self.quality_combo)
        controls.addWidget(QLabel("Audio"))
        controls.addWidget(self.audio_combo)
        controls.addWidget(self.download_btn)
        rlayout.addLayout(controls)

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 940])
        return splitter

    def _build_downloads_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.dl_table = QTableWidget(0, 7)
        self.dl_table.setHorizontalHeaderLabels(["Anime", "Ep", "Source", "Status", "Progress", "Speed", "Info"])
        self.dl_table.verticalHeader().setVisible(False)
        self.dl_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.dl_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dl_table.setAlternatingRowColors(True)
        hdr = self.dl_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.dl_table.setColumnWidth(4, 220)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.dl_table.cellDoubleClicked.connect(self._open_task_file)
        layout.addWidget(self.dl_table, 1)

        buttons = QHBoxLayout()
        self.summary_label = QLabel("")
        cancel = QPushButton("Cancel selected")
        cancel.clicked.connect(self._cancel_selected)
        cancel_all = QPushButton("Cancel all")
        cancel_all.clicked.connect(self.manager.cancel_all)
        retry = QPushButton("Retry selected")
        retry.clicked.connect(self._retry_selected)
        retry_all = QPushButton("Retry failed")
        retry_all.clicked.connect(lambda: self.manager.retry_failed())
        clear = QPushButton("Clear finished")
        clear.clicked.connect(self._clear_finished)
        buttons.addWidget(self.summary_label, 1)
        for button in (cancel, cancel_all, retry, retry_all, clear):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return page

    # ================================================================== Cloudflare
    def _cloudflare_from_thread(self) -> None:
        # Called from a download thread: hop to the GUI thread.
        if not self._cf_prompt_pending:
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
            self.statusBar().showMessage("Browser verification saved.", 5000)
            return True
        finally:
            self._verifying = False

    def _handle_error(self, exc: Exception, retry=None) -> None:  # type: ignore[no-untyped-def]
        self._set_busy(False)
        if isinstance(exc, CloudflareChallenge):
            if self.verify() and retry:
                retry()
            return
        QMessageBox.warning(self, "Something went wrong", str(exc) or exc.__class__.__name__)

    # ================================================================== search / browse
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.search_btn.setEnabled(not busy)
        if busy:
            self.statusBar().showMessage(message)
            self.setCursor(Qt.CursorShape.BusyCursor)
        else:
            self.unsetCursor()
            if message:
                self.statusBar().showMessage(message, 6000)

    def search(self) -> None:
        text = self.search_edit.text().strip()
        if not text:
            return
        session = parse_anime_session(text)
        if session:
            self._set_busy(True, "Opening anime…")

            def load() -> Anime:
                return Anime(session=session, title=self.api.anime_title(session))

            self.jobs.submit(load, lambda anime: self._show_results([anime]),
                             lambda e: self._handle_error(e, self.search))
            return
        self._set_busy(True, f"Searching for “{text}”…")
        self.jobs.submit(lambda: self.api.search(text), self._show_results,
                         lambda e: self._handle_error(e, self.search))

    def _show_results(self, results: list[Anime]) -> None:
        self._set_busy(False, f"{len(results)} result(s)")
        self.results.clear()
        for anime in results:
            item = QListWidgetItem(f"{anime.title}\n{anime.subtitle}")
            item.setData(Qt.ItemDataRole.UserRole, anime)
            item.setSizeHint(QSize(0, 52))
            self.results.addItem(item)
        if results:
            self.results.setCurrentRow(0)
        else:
            QMessageBox.information(self, "No results", "Nothing matched your search.")

    def _on_result_selected(self, item: QListWidgetItem | None, _prev=None) -> None:  # type: ignore[no-untyped-def]
        if item is None:
            return
        anime: Anime = item.data(Qt.ItemDataRole.UserRole)
        self.current_anime = anime
        self.title_label.setText(anime.title)
        self.meta_label.setText(anime.subtitle)
        self.episode_table.setRowCount(0)
        self._load_poster(anime)
        self._load_episodes(anime)

    def _load_poster(self, anime: Anime) -> None:
        self.poster.setPixmap(QPixmap())
        self.poster.setText("")
        if not anime.poster:
            return
        if anime.poster in self._poster_cache:
            self.poster.setPixmap(self._poster_cache[anime.poster])
            return
        url = anime.poster

        def fetch() -> bytes:
            return self.http.get_bytes(url, referer=self.api.referer, retries=1)

        def show(data: bytes) -> None:
            pix = QPixmap()
            if pix.loadFromData(data):
                pix = pix.scaled(self.poster.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                self._poster_cache[url] = pix
                if self.current_anime and self.current_anime.poster == url:
                    self.poster.setPixmap(pix)

        self.jobs.submit(fetch, show, lambda _e: None)

    def _load_episodes(self, anime: Anime) -> None:
        self._set_busy(True, f"Loading episodes of {anime.title}…")

        def done(episodes: list[Episode]) -> None:
            if self.current_anime is not anime:
                return
            self._set_busy(False, f"{len(episodes)} episode(s) available")
            self.episodes = episodes
            self._fill_episode_table()

        self.jobs.submit(lambda: self.api.episodes(anime.session), done,
                         lambda e: self._handle_error(e, lambda: self._load_episodes(anime)))

    def _fill_episode_table(self) -> None:
        table = self.episode_table
        table.setRowCount(len(self.episodes))
        for row, ep in enumerate(self.episodes):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Unchecked)
            table.setItem(row, 0, check)
            number = QTableWidgetItem(format_episode(ep.number))
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 1, number)
            title = ep.title or f"Episode {format_episode(ep.number, 1)}"
            if ep.filler:
                title += "  (filler)"
            table.setItem(row, 2, QTableWidgetItem(title))
            table.setItem(row, 3, QTableWidgetItem(ep.duration))
            table.setItem(row, 4, QTableWidgetItem(ep.created_at[:10]))

    def _toggle_row(self, row: int, _col: int) -> None:
        item = self.episode_table.item(row, 0)
        if item:
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                               else Qt.CheckState.Checked)

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.episode_table.rowCount()):
            self.episode_table.item(row, 0).setCheckState(state)

    def _apply_range(self) -> None:
        try:
            wanted = set(parse_episode_selection(self.range_edit.text(), [e.number for e in self.episodes]))
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid range", str(exc))
            return
        for row, ep in enumerate(self.episodes):
            self.episode_table.item(row, 0).setCheckState(
                Qt.CheckState.Checked if ep.number in wanted else Qt.CheckState.Unchecked)

    def _checked_episodes(self) -> list[Episode]:
        chosen = [ep for row, ep in enumerate(self.episodes)
                  if self.episode_table.item(row, 0).checkState() == Qt.CheckState.Checked]
        if not chosen:  # fall back to highlighted rows
            rows = sorted({i.row() for i in self.episode_table.selectedIndexes()})
            chosen = [self.episodes[r] for r in rows]
        return chosen

    def _quick_settings_changed(self) -> None:
        self.settings.quality = self.quality_combo.currentData()
        self.settings.audio = self.audio_combo.currentData()
        self.settings.save()

    def download_selected(self) -> None:
        if not self.current_anime:
            return
        chosen = self._checked_episodes()
        if not chosen:
            QMessageBox.information(self, "Nothing selected", "Tick the episodes you want, or use Select all.")
            return
        added = self.manager.add(self.current_anime.title, self.current_anime.session, chosen)
        self.statusBar().showMessage(f"Queued {len(added)} episode(s) of {self.current_anime.title}", 6000)
        self.tabs.setCurrentIndex(1)

    # ================================================================== downloads tab
    def _refresh_downloads(self) -> None:
        tasks = self.manager.snapshot()
        table = self.dl_table
        if len(self._rows) != len(tasks) or any(t.id not in self._rows for t in tasks):
            table.setRowCount(len(tasks))
            self._rows = {t.id: i for i, t in enumerate(tasks)}
            for row in range(len(tasks)):
                bar = QProgressBar()
                bar.setRange(0, 1000)
                table.setCellWidget(row, 4, bar)
        active = done = failed = 0
        total_speed = 0.0
        for task in tasks:
            row = self._rows[task.id]
            self._set_cell(row, 0, task.anime_title, task)
            self._set_cell(row, 1, task.episode_label, task)
            self._set_cell(row, 2, task.source_label, task)
            status = self._set_cell(row, 3, task.status.value, task)
            color = STATUS_COLORS.get(task.status)
            if color:
                status.setForeground(QColor(color))
            bar: QProgressBar = table.cellWidget(row, 4)  # type: ignore[assignment]
            bar.setValue(int(task.progress * 1000))
            if task.segments_total and task.status == Status.DOWNLOADING:
                bar.setFormat(f"{task.progress:.0%}  ({format_bytes(task.bytes_done)})")
            else:
                bar.setFormat(f"{task.progress:.0%}")
            self._set_cell(row, 5, format_speed(task.speed), task)
            info = task.message or (Path(task.output_path).name if task.output_path else "")
            self._set_cell(row, 6, info, task)
            total_speed += task.speed
            if task.status in {Status.DONE, Status.SKIPPED}:
                done += 1
            elif task.status == Status.FAILED:
                failed += 1
            elif not task.status.finished:
                active += 1
        self.summary_label.setText(
            f"{active} active · {done} done · {failed} failed" + (f" · {format_speed(total_speed)}" if total_speed else "")
        )
        self.tabs.setTabText(1, f"Downloads ({active})" if active else "Downloads")

    def _set_cell(self, row: int, col: int, text: str, task: DownloadTask) -> QTableWidgetItem:
        item = self.dl_table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            self.dl_table.setItem(row, col, item)
        if item.text() != text:
            item.setText(text)
            item.setToolTip(text)
        item.setData(Qt.ItemDataRole.UserRole, task.id)
        return item

    def _selected_task_ids(self) -> list[int]:
        ids = []
        for row in sorted({i.row() for i in self.dl_table.selectedIndexes()}):
            item = self.dl_table.item(row, 0)
            if item is not None:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids

    def _cancel_selected(self) -> None:
        for task_id in self._selected_task_ids():
            self.manager.cancel(task_id)

    def _retry_selected(self) -> None:
        for task_id in self._selected_task_ids():
            self.manager.retry(task_id)

    def _clear_finished(self) -> None:
        self.manager.clear_finished()
        self._rows = {}
        self._refresh_downloads()

    def _open_task_file(self, row: int, _col: int) -> None:
        item = self.dl_table.item(row, 0)
        if item is None:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        for task in self.manager.snapshot():
            if task.id == task_id and task.output_path and Path(task.output_path).exists():
                open_in_file_manager(Path(task.output_path).parent)

    def _open_download_folder(self) -> None:
        path = Path(self.settings.download_dir)
        path.mkdir(parents=True, exist_ok=True)
        open_in_file_manager(path)

    # ================================================================== settings / lifecycle
    def open_settings(self) -> None:
        old_base = self.settings.base_url
        if SettingsDialog(self.settings, self).exec():
            if self.settings.base_url != old_base:
                self.api.set_base_url(self.settings.base_url)
            self.http.cookies = dict(self.settings.cookies)
            self.http.set_identity(self.settings.user_agent, self.settings.cookies)
            self.quality_combo.setCurrentIndex(max(0, self.quality_combo.findData(self.settings.quality)))
            self.audio_combo.setCurrentIndex(max(0, self.audio_combo.findData(self.settings.audio)))
            self.statusBar().showMessage("Settings saved.", 4000)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.manager.is_busy():
            answer = QMessageBox.question(
                self, "Downloads in progress",
                "Downloads are still running. Quit anyway? Finished segments are kept and will resume next time.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.manager.shutdown()
        self.settings.save()
        event.accept()
