"""Slim banner above the pages: "A new version is available" with Download and dismiss buttons."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ..updates import UpdateInfo
from ..utils import format_bytes
from .theme import emphasize


class UpdateBanner(QFrame):
    download_requested = Signal(str)  # release page address
    dismissed = Signal(str)  # commit of the dismissed update

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("updateBanner")
        self._info: UpdateInfo | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 12, 8)
        layout.setSpacing(12)
        self.label = QLabel()
        self.label.setObjectName("updateText")
        self.get_btn = emphasize(QPushButton("Download"))
        self.get_btn.setObjectName("primary")
        self.get_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.get_btn.clicked.connect(lambda: self._info and self.download_requested.emit(self._info.url))
        self.close_btn = QPushButton("Not now")
        self.close_btn.setObjectName("ghost")
        self.close_btn.clicked.connect(self._dismiss)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.get_btn)
        layout.addWidget(self.close_btn)
        self.hide()

    def show_update(self, info: UpdateInfo) -> None:
        self._info = info
        bits = ["A new version is available"]
        if info.published:
            bits.append(f"built {info.published}")
        if info.size:
            bits.append(format_bytes(info.size))
        self.label.setText("  ·  ".join(bits))
        self.show()

    def _dismiss(self) -> None:
        if self._info:
            self.dismissed.emit(self._info.sha)
        self.hide()
