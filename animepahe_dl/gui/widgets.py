"""Reusable widgets: flowing card grid, anime card and download-queue row."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QLayoutItem, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from ..animepahe import Anime
from ..downloader import DownloadTask, Status
from ..utils import format_bytes, format_speed
from .theme import emphasize, placeholder_poster, repolish, rounded_pixmap


class FlowLayout(QLayout):
    """Lays out equally sized cards left-to-right, wrapping to new rows (a responsive grid)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 18) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def clear(self) -> None:
        while self._items:
            item = self._items.pop()
            if item.widget():
                item.widget().deleteLater()

    def _layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        if not self._items:
            return 0
        item_w = self._items[0].sizeHint().width()
        per_row = max(1, (area.width() + self._spacing) // (item_w + self._spacing))
        used = per_row * item_w + (per_row - 1) * self._spacing
        left = area.x() + max(0, (area.width() - used) // 2)  # centre the grid
        x, y, row_h, col = left, area.y(), 0, 0
        for item in self._items:
            hint = item.sizeHint()
            if col == per_row:
                x, y, row_h, col = left, y + row_h + self._spacing, 0, 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_h = max(row_h, hint.height())
            col += 1
        return y + row_h - rect.y() + margins.bottom()


class ElidedLabel(QLabel):
    """Single-line label that shortens its text with '…' instead of growing wider."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(20)
        self.set_full_text(text)

    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        text = " ".join(text.split())  # one line
        if text != self._full:
            self._full = text
            self.setToolTip(text)
            self._elide()

    def _elide(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, max(20, self.width())))

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().resizeEvent(event)
        self._elide()


class AnimeCard(QFrame):
    """Cover art, title, release info and a 'View Episodes' button."""

    view_requested = Signal(object)
    POSTER_W, POSTER_H = 176, 248

    def __init__(self, anime: Anime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.anime = anime
        self.setObjectName("card")
        self.setFixedWidth(self.POSTER_W + 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.poster = QLabel()
        self.poster.setFixedSize(self.POSTER_W, self.POSTER_H)
        self.poster.setPixmap(placeholder_poster(anime.title, self.POSTER_W, self.POSTER_H))
        layout.addWidget(self.poster)

        title = QLabel()
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        metrics = QFontMetrics(title.font())
        title.setText(metrics.elidedText(anime.title, Qt.TextElideMode.ElideRight, int(self.POSTER_W * 1.85)))
        title.setToolTip(anime.title)
        title.setFixedHeight(metrics.lineSpacing() * 2 + 6)
        title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        release = " · ".join(b for b in (anime.type, f"{anime.season} {anime.year or ''}".strip()) if b)
        stats = " · ".join(b for b in (f"{anime.episodes} eps" if anime.episodes else "",
                                        f"★ {anime.score}" if anime.score else "") if b)
        for line in (release or "Release info unavailable", stats or " ", anime.status or " "):
            info = ElidedLabel(line)
            info.setObjectName("cardInfo")
            layout.addWidget(info)

        button = emphasize(QPushButton("View Episodes"))
        button.setObjectName("primary")
        button.clicked.connect(lambda: self.view_requested.emit(self.anime))
        layout.addWidget(button)

    def set_cover(self, pixmap: QPixmap) -> None:
        self.poster.setPixmap(rounded_pixmap(pixmap, self.POSTER_W, self.POSTER_H))

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.view_requested.emit(self.anime)
        super().mouseDoubleClickEvent(event)


STATE_KEYS = {
    Status.QUEUED: "queued", Status.RESOLVING: "resolving", Status.DOWNLOADING: "downloading",
    Status.MUXING: "stitching", Status.DONE: "completed", Status.SKIPPED: "completed",
    Status.FAILED: "failed", Status.CANCELLED: "cancelled",
}


class DownloadRow(QFrame):
    """One entry in the download queue."""

    cancel_requested = Signal(int)
    retry_requested = Signal(int)
    open_requested = Signal(int)

    def __init__(self, task: DownloadTask, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.task_id = task.id
        self.setObjectName("queueRow")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        top = QHBoxLayout()
        self.title = ElidedLabel(f"{task.anime_title} — Episode {task.episode_label}")
        self.title.setObjectName("sectionTitle")
        self.source = QLabel()
        self.source.setObjectName("muted")
        self.pill = emphasize(QLabel())
        self.pill.setObjectName("pill")
        top.addWidget(self.title, 1)
        top.addWidget(self.source)
        top.addSpacing(8)
        top.addWidget(self.pill)
        outer.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        outer.addWidget(self.bar)

        bottom = QHBoxLayout()
        self.speed = QLabel()
        self.speed.setObjectName("sectionTitle")
        self.speed.setMinimumWidth(90)
        self.details = ElidedLabel()
        self.details.setObjectName("muted")
        self.cancel_btn = QPushButton("Cancel")
        self.retry_btn = QPushButton("Retry")
        self.open_btn = QPushButton("Show in folder")
        for btn in (self.cancel_btn, self.retry_btn, self.open_btn):
            btn.setObjectName("ghost")
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self.task_id))
        self.retry_btn.clicked.connect(lambda: self.retry_requested.emit(self.task_id))
        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.task_id))
        bottom.addWidget(self.speed)
        bottom.addWidget(self.details, 1)
        for btn in (self.cancel_btn, self.retry_btn, self.open_btn):
            bottom.addWidget(btn)
        outer.addLayout(bottom)
        self._state = ""
        self.update_from(task, paused=False)

    def update_from(self, task: DownloadTask, paused: bool) -> None:
        active = not task.status.finished
        state = "paused" if paused and active else STATE_KEYS[task.status]
        label = "Paused" if state == "paused" else task.status.value
        if self.pill.text() != label:
            self.pill.setText(label)
        if state != self._state:
            self._state = state
            for widget in (self.pill, self.bar):
                widget.setProperty("state", state)
                repolish(widget)
        self.source.setText(task.source_label)
        self.bar.setValue(int(task.progress * 1000))

        speed = 0.0 if paused else task.speed
        self.speed.setText(format_speed(speed) if speed else ("—" if active else ""))
        bits = [f"{task.progress:.0%}"]
        if task.bytes_done:
            bits.append(format_bytes(task.bytes_done))
        if task.segments_total and task.status == Status.DOWNLOADING:
            bits.append(f"{task.segments_done}/{task.segments_total} segments")
        if task.message:
            bits.append(task.message)
        elif task.output_path and task.status.finished:
            bits.append(task.output_path)
        self.details.set_full_text("  ·  ".join(bits))

        self.cancel_btn.setVisible(active)
        self.retry_btn.setVisible(task.status in {Status.FAILED, Status.CANCELLED})
        self.open_btn.setVisible(bool(task.output_path))
