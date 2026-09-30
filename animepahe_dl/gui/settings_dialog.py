"""Settings window."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..config import AUDIO_CHOICES, QUALITIES, Settings
from ..utils import find_ffmpeg

AUDIO_LABELS = {"jpn": "Japanese (sub)", "eng": "English (dub)", "any": "Any"}


def _browse_row(edit: QLineEdit, button: QPushButton) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(edit, 1)
    layout.addWidget(button)
    return row


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = settings
        self.resize(620, 0)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.base_url = QLineEdit(settings.base_url)
        self.base_url.setToolTip("AnimePahe changes domains from time to time (.pw, .si, .ru, .com, ...).")
        form.addRow("Site address", self.base_url)

        self.folder = QLineEdit(settings.download_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        form.addRow("Download folder", _browse_row(self.folder, browse))

        self.template = QLineEdit(settings.filename_template)
        self.template.setToolTip("Placeholders: {anime} {episode} {quality} {audio} {title}")
        form.addRow("File name", self.template)

        self.quality = QComboBox()
        for q in QUALITIES:
            self.quality.addItem(f"{q}p", q)
        self.quality.setCurrentIndex(max(0, self.quality.findData(settings.quality)))
        form.addRow("Preferred quality", self.quality)

        self.audio = QComboBox()
        for a in AUDIO_CHOICES:
            self.audio.addItem(AUDIO_LABELS[a], a)
        self.audio.setCurrentIndex(max(0, self.audio.findData(settings.audio)))
        form.addRow("Audio", self.audio)

        self.no_av1 = QCheckBox("Prefer H.264 over AV1 (better compatibility)")
        self.no_av1.setChecked(settings.prefer_non_av1)
        form.addRow("", self.no_av1)

        self.parallel = QSpinBox()
        self.parallel.setRange(1, 6)
        self.parallel.setValue(settings.max_parallel_episodes)
        form.addRow("Episodes at once", self.parallel)

        self.workers = QSpinBox()
        self.workers.setRange(1, 32)
        self.workers.setValue(settings.segment_workers)
        form.addRow("Connections per episode", self.workers)

        self.ffmpeg = QLineEdit(settings.ffmpeg_path)
        self.ffmpeg.setPlaceholderText(find_ffmpeg("") or "Not found - episodes will be saved as .ts")
        ff_browse = QPushButton("Browse…")
        ff_browse.clicked.connect(self._pick_ffmpeg)
        form.addRow("ffmpeg.exe", _browse_row(self.ffmpeg, ff_browse))

        hint = QLabel("ffmpeg converts downloads to .mp4. Install it with: <code>winget install Gyan.FFmpeg</code>")
        hint.setWordWrap(True)
        form.addRow("", hint)

        self.clear_cookies = QCheckBox("Forget Cloudflare cookies")
        form.addRow("", self.clear_cookies)

        layout.addLayout(form)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Download folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def _pick_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate ffmpeg", "", "ffmpeg (ffmpeg.exe ffmpeg);;All files (*)")
        if path:
            self.ffmpeg.setText(path)

    def _save(self) -> None:
        s = self.settings
        s.base_url = self.base_url.text()
        s.download_dir = self.folder.text().strip() or s.download_dir
        s.filename_template = self.template.text()
        s.quality = self.quality.currentData()
        s.audio = self.audio.currentData()
        s.prefer_non_av1 = self.no_av1.isChecked()
        s.max_parallel_episodes = self.parallel.value()
        s.segment_workers = self.workers.value()
        s.ffmpeg_path = self.ffmpeg.text().strip()
        if self.clear_cookies.isChecked():
            s.cookies = {}
            s.user_agent = ""
        s.normalize()
        s.save()
        self.accept()
