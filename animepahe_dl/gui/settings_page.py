"""'Settings' page (embedded in the main window instead of a pop-up dialog)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..animepahe import AnimePahe
from ..config import AUDIO_CHOICES, QUALITIES
from ..http import CloudflareChallenge, HttpClient
from ..utils import find_ffmpeg
from .search_page import AUDIO_LABELS
from .theme import emphasize

if TYPE_CHECKING:
    from .main_window import MainWindow


def _row(*widgets: QWidget) -> QWidget:
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if index == 0 else 0)
    return host


def _section(title: str, subtitle: str = "") -> tuple[QFrame, QFormLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(20, 16, 20, 18)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    outer.addWidget(heading)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        outer.addWidget(sub)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    outer.addLayout(form)
    return frame, form


class SettingsPage(QWidget):
    saved = Signal()

    def __init__(self, ctx: "MainWindow") -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 16)
        outer.setSpacing(14)
        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("scrollBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # Downloads
        box, form = _section("Downloads")
        self.folder = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        form.addRow("Download folder", _row(self.folder, browse))
        self.template = QLineEdit()
        self.template.setToolTip("Placeholders: {anime} {episode} {quality} {audio} {title}")
        form.addRow("File name pattern", self.template)
        self.quality = QComboBox()
        for q in QUALITIES:
            self.quality.addItem(f"{q}p", q)
        form.addRow("Preferred quality", self.quality)
        self.audio = QComboBox()
        for a in AUDIO_CHOICES:
            self.audio.addItem(AUDIO_LABELS[a], a)
        form.addRow("Audio", self.audio)
        self.no_av1 = QCheckBox("Prefer H.264 over AV1 (plays on more devices)")
        form.addRow("", self.no_av1)
        self.rename_jp = QCheckBox("Rename file and folder to the Japanese (romaji) title when a download finishes "
                                   "(looked up on MyAnimeList)")
        form.addRow("", self.rename_jp)
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 6)
        form.addRow("Episodes at once", self.parallel)
        self.workers = QSpinBox()
        self.workers.setRange(1, 32)
        form.addRow("Connections per episode", self.workers)
        layout.addWidget(box)

        # FFmpeg
        box, form = _section("FFmpeg", "Joins the downloaded pieces into an .mp4 file. "
                                       "Install it with: winget install Gyan.FFmpeg")
        self.ffmpeg = QLineEdit()
        ff_browse = QPushButton("Browse…")
        ff_browse.clicked.connect(self._pick_ffmpeg)
        form.addRow("ffmpeg.exe", _row(self.ffmpeg, ff_browse))
        self.ffmpeg_status = QLabel()
        self.ffmpeg_status.setObjectName("muted")
        self.ffmpeg_status.setWordWrap(True)
        form.addRow("", self.ffmpeg_status)
        self.ffmpeg.textChanged.connect(self._update_ffmpeg_status)
        layout.addWidget(box)

        # Site & Cloudflare
        box, form = _section("Site & Cloudflare", "AnimePahe changes its address from time to time "
                                                  "(.pw, .si, .ru, .com…). Cloudflare cookies expire, "
                                                  "or stop working when your IP changes.")
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://animepahe.pw")
        self.test_btn = QPushButton("Test")
        self.test_btn.setToolTip("Check that this address is a working AnimePahe site")
        self.test_btn.clicked.connect(self._test_site)
        form.addRow("Site address", _row(self.base_url, self.test_btn))
        self.site_status = QLabel("")
        self.site_status.setObjectName("muted")
        self.site_status.setWordWrap(True)
        form.addRow("", self.site_status)
        self.cf_status = QLabel()
        self.cf_status.setObjectName("muted")
        verify = QPushButton("Verify in browser")
        verify.clicked.connect(self._verify)
        forget = QPushButton("Forget cookies")
        forget.clicked.connect(self._forget)
        form.addRow("Cloudflare", _row(self.cf_status, verify, forget))
        layout.addWidget(box)
        layout.addStretch(1)

        footer = QHBoxLayout()
        self.saved_label = QLabel("")
        self.saved_label.setObjectName("muted")
        revert = QPushButton("Revert")
        revert.clicked.connect(self.load)
        save = emphasize(QPushButton("Save settings"))
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        footer.addWidget(self.saved_label, 1)
        footer.addWidget(revert)
        footer.addWidget(save)
        outer.addLayout(footer)
        self.load()

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        s = self.ctx.settings
        self.folder.setText(s.download_dir)
        self.template.setText(s.filename_template)
        self.quality.setCurrentIndex(max(0, self.quality.findData(s.quality)))
        self.audio.setCurrentIndex(max(0, self.audio.findData(s.audio)))
        self.no_av1.setChecked(s.prefer_non_av1)
        self.rename_jp.setChecked(s.rename_japanese)
        self.parallel.setValue(s.max_parallel_episodes)
        self.workers.setValue(s.segment_workers)
        self.ffmpeg.setText(s.ffmpeg_path)
        self.base_url.setText(s.base_url)
        self._update_ffmpeg_status()
        self._update_cf_status()
        self.saved_label.setText("")
        self.site_status.setText("")

    def save(self) -> None:
        s = self.ctx.settings
        s.download_dir = self.folder.text().strip() or s.download_dir
        s.filename_template = self.template.text()
        s.quality = self.quality.currentData()
        s.audio = self.audio.currentData()
        s.prefer_non_av1 = self.no_av1.isChecked()
        s.rename_japanese = self.rename_jp.isChecked()
        s.max_parallel_episodes = self.parallel.value()
        s.segment_workers = self.workers.value()
        s.ffmpeg_path = self.ffmpeg.text().strip()
        s.base_url = self.base_url.text()
        s.normalize()
        s.save()
        self.base_url.setText(s.base_url)
        self.saved_label.setText("✔ Settings saved")
        self.saved.emit()

    def _test_site(self) -> None:
        from ..config import Settings

        probe = Settings(base_url=self.base_url.text())
        probe.normalize()
        s = self.ctx.settings
        api = AnimePahe(HttpClient(s.user_agent, s.cookies, retries=1), probe.base_url)
        self.test_btn.setEnabled(False)
        self.site_status.setText(f"Testing {probe.base_url}…")

        def ok(count: int) -> None:
            self.test_btn.setEnabled(True)
            self.site_status.setText(f"✔ {probe.base_url} is working ({count} results for a test search). "
                                     "Click Save settings to use it.")

        def failed(exc: Exception) -> None:
            self.test_btn.setEnabled(True)
            if isinstance(exc, CloudflareChallenge):
                self.site_status.setText("This address needs the Cloudflare check first. Save settings, "
                                         "then click Verify in browser.")
            else:
                self.site_status.setText(f"✖ {exc}")

        self.ctx.jobs.submit(api.check_site, ok, failed)

    def _update_ffmpeg_status(self) -> None:
        found = find_ffmpeg(self.ffmpeg.text().strip())
        self.ffmpeg_status.setText(f"✔ Using {found}" if found
                                   else "✖ Not found. Episodes will be saved as .ts files (VLC plays them).")

    def _update_cf_status(self) -> None:
        has = "cf_clearance" in self.ctx.settings.cookies
        self.cf_status.setText("✔ Browser check saved" if has else "No browser check saved yet")

    def _verify(self) -> None:
        self.ctx.verify()
        self._update_cf_status()

    def _forget(self) -> None:
        self.ctx.settings.cookies = {}
        self.ctx.settings.user_agent = ""
        self.ctx.settings.save()
        self.ctx.reset_identity()
        self._update_cf_status()

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Download folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def _pick_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate ffmpeg", "", "ffmpeg (ffmpeg.exe ffmpeg);;All files (*)")
        if path:
            self.ffmpeg.setText(path)
