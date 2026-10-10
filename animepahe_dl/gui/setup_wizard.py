"""First-run setup (download folder, ffmpeg, preferences) and the reusable ffmpeg installer widget."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..config import AUDIO_CHOICES, QUALITIES, SITE_LABELS, SITES, app_data_dir, is_portable
from ..ffmpeg_install import FfmpegInstallError, install_ffmpeg
from ..http import HttpClient
from ..utils import find_ffmpeg, format_bytes
from .theme import emphasize

if TYPE_CHECKING:
    from .main_window import MainWindow

AUDIO_LABELS = {"jpn": "Japanese (sub)", "eng": "English (dub)", "any": "Any audio"}


class FfmpegInstaller(QWidget):
    """Shows whether ffmpeg is available and (on Windows) installs it with one click."""

    changed = Signal()
    _progress = Signal(int, int)  # emitted from the download thread

    def __init__(self, ctx: "MainWindow") -> None:
        super().__init__()
        self.ctx = ctx
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.button = emphasize(QPushButton("Install ffmpeg"))
        self.button.setObjectName("primary")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._install)
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        self._progress.connect(self._show_progress)
        self.refresh()

    def refresh(self) -> None:
        found = find_ffmpeg(self.ctx.settings.ffmpeg_path)
        if found:
            self.status.setText(f"✔ ffmpeg is installed: {found}")
        elif sys.platform == "win32":
            self.status.setText("✖ ffmpeg was not found. Without it episodes are saved as .ts files. "
                                "The button below downloads the official build (about 80 MB) and checks it.")
        else:
            self.status.setText("✖ ffmpeg was not found. Install it with your package manager "
                                "(for example: sudo apt install ffmpeg).")
        self.button.setVisible(not found and sys.platform == "win32" and not self._busy)

    def _install(self) -> None:
        self._busy = True
        self.button.hide()
        self.bar.setValue(0)
        self.bar.show()
        self.status.setText("Downloading ffmpeg…")
        target = app_data_dir() / "tools"

        def work() -> str:
            http = HttpClient(retries=2, timeout=60.0)
            return str(install_ffmpeg(http, target, progress=lambda done, total, _added: self._progress.emit(done, total)))

        def done(path: str) -> None:
            self._busy = False
            self.bar.hide()
            self.ctx.settings.ffmpeg_path = path
            self.ctx.settings.save()
            self.refresh()
            self.changed.emit()

        def failed(exc: Exception) -> None:
            self._busy = False
            self.bar.hide()
            self.refresh()
            reason = str(exc) if isinstance(exc, FfmpegInstallError) else f"{exc.__class__.__name__}: {exc}"
            self.status.setText(f"✖ Could not install ffmpeg. {reason}")

        self.ctx.jobs.submit(work, done, failed)

    def _show_progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setValue(int(done / total * 1000))
            self.status.setText(f"Downloading ffmpeg… {format_bytes(done)} of {format_bytes(total)}")
        else:
            self.status.setText(f"Downloading ffmpeg… {format_bytes(done)}")


class SetupWizard(QDialog):
    """Three short steps shown on the first start; can be run again from Settings."""

    def __init__(self, ctx: "MainWindow") -> None:
        super().__init__(ctx)
        self.ctx = ctx
        self.setWindowTitle("Welcome to Anime Downloader")
        self.setModal(True)
        self.setMinimumWidth(640)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 20)
        outer.setSpacing(14)
        self.heading = QLabel()
        self.heading.setObjectName("pageTitle")
        self.step = QLabel()
        self.step.setObjectName("muted")
        outer.addWidget(self.heading)
        outer.addWidget(self.step)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self._build_pages()

        buttons = QHBoxLayout()
        self.skip = QPushButton("Skip setup")
        self.skip.setObjectName("ghost")
        self.back = QPushButton("Back")
        self.next = emphasize(QPushButton("Next"))
        self.next.setObjectName("primary")
        self.skip.clicked.connect(self._skip)
        self.back.clicked.connect(lambda: self._go(self.pages.currentIndex() - 1))
        self.next.clicked.connect(self._next)
        buttons.addWidget(self.skip)
        buttons.addStretch(1)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        outer.addLayout(buttons)
        self._go(0)

    # ------------------------------------------------------------------ pages
    def _build_pages(self) -> None:
        s = self.ctx.settings
        # 1: folder
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(10)
        intro = QLabel("Choose where finished episodes are saved. Each show gets its own folder inside it.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.folder = QLineEdit(s.download_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        lay.addLayout(row)
        note = QLabel("Portable mode: settings and downloads stay inside this program's folder."
                      if is_portable() else "Tip: a folder on a drive with plenty of free space works best.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        self.pages.addWidget(page)
        # 2: ffmpeg
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(10)
        intro = QLabel("ffmpeg joins the downloaded pieces into one .mp4 file that plays everywhere.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.ffmpeg = FfmpegInstaller(self.ctx)
        lay.addWidget(self.ffmpeg)
        lay.addStretch(1)
        self.pages.addWidget(page)
        # 3: preferences
        page = QWidget()
        form = QFormLayout(page)
        form.setVerticalSpacing(10)
        self.site = QComboBox()
        for key in SITES:
            self.site.addItem(SITE_LABELS[key], key)
        self.site.setCurrentIndex(max(0, self.site.findData(s.site)))
        self.quality = QComboBox()
        for q in QUALITIES:
            self.quality.addItem(f"{q}p", q)
        self.quality.setCurrentIndex(max(0, self.quality.findData(s.quality)))
        self.audio = QComboBox()
        for a in AUDIO_CHOICES:
            self.audio.addItem(AUDIO_LABELS[a], a)
        self.audio.setCurrentIndex(max(0, self.audio.findData(s.audio)))
        self.rename = QCheckBox("Rename files and folders to the Japanese (romaji) title after downloading")
        self.rename.setChecked(s.rename_japanese)
        self.tray = QCheckBox("Show a tray icon and tell me when downloads finish")
        self.tray.setChecked(s.tray_icon and s.notify_finished)
        self.updates = QCheckBox("Tell me when a new version is available")
        self.updates.setChecked(s.check_updates)
        form.addRow("Search on", self.site)
        form.addRow("Quality", self.quality)
        form.addRow("Audio", self.audio)
        form.addRow("", self.rename)
        form.addRow("", self.tray)
        form.addRow("", self.updates)
        self.pages.addWidget(page)
        self._titles = [
            ("Where should downloads go?", "Step 1 of 3"),
            ("Get ffmpeg for .mp4 files", "Step 2 of 3"),
            ("Your preferences", "Step 3 of 3 · you can change all of this later in Settings"),
        ]

    def _go(self, index: int) -> None:
        index = max(0, min(index, self.pages.count() - 1))
        self.pages.setCurrentIndex(index)
        self.heading.setText(self._titles[index][0])
        self.step.setText(self._titles[index][1])
        self.back.setEnabled(index > 0)
        self.next.setText("Finish" if index == self.pages.count() - 1 else "Next")
        if index == 1:
            self.ffmpeg.refresh()

    def _next(self) -> None:
        if self.pages.currentIndex() == self.pages.count() - 1:
            self._finish()
        else:
            self._go(self.pages.currentIndex() + 1)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Download folder", self.folder.text())
        if path:
            self.folder.setText(path)

    # ------------------------------------------------------------------ result
    def _finish(self) -> None:
        s = self.ctx.settings
        s.download_dir = self.folder.text().strip() or s.download_dir
        s.site = self.site.currentData()
        s.quality = self.quality.currentData()
        s.audio = self.audio.currentData()
        s.rename_japanese = self.rename.isChecked()
        s.tray_icon = s.notify_finished = self.tray.isChecked()
        s.check_updates = self.updates.isChecked()
        s.setup_done = True
        s.normalize()
        s.save()
        self.ctx.settings_applied()
        self.accept()

    def _skip(self) -> None:
        self.ctx.settings.setup_done = True  # do not show it again; Settings can run it later
        self.ctx.settings.save()
        self.reject()
