"""'Download Queue': live list of downloads with progress, speed, status and Pause/Resume All."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..downloader import Status
from ..utils import format_speed, open_in_file_manager
from .theme import emphasize
from .widgets import DownloadRow

if TYPE_CHECKING:
    from .main_window import MainWindow


class QueuePage(QWidget):
    def __init__(self, ctx: "MainWindow") -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName("page")
        self.rows: dict[int, DownloadRow] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Download Queue")
        title.setObjectName("pageTitle")
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        titles.addWidget(title)
        titles.addWidget(self.summary)
        header.addLayout(titles, 1)

        self.pause_btn = emphasize(QPushButton("Pause All"))
        self.pause_btn.setMinimumWidth(self.pause_btn.fontMetrics().horizontalAdvance("Resume All") + 40)
        self.pause_btn.setObjectName("toggle")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.toggled.connect(self._toggle_pause)
        retry = QPushButton("Retry failed")
        retry.clicked.connect(lambda: ctx.manager.retry_failed())
        clear = QPushButton("Clear finished")
        clear.clicked.connect(self._clear_finished)
        folder = QPushButton("Open folder")
        folder.clicked.connect(ctx.open_download_folder)
        for btn in (self.pause_btn, retry, clear, folder):
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
        self.empty = QLabel("Your queue is empty.\nPick episodes in Search & Discover and click “Add to Queue”.")
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll, 1)

    # ------------------------------------------------------------------ actions
    def _toggle_pause(self, paused: bool) -> None:
        if paused:
            self.ctx.manager.pause_all()
        else:
            self.ctx.manager.resume_all()
        self.pause_btn.setText("Resume All" if paused else "Pause All")
        self.refresh()

    def _clear_finished(self) -> None:
        self.ctx.manager.clear_finished()
        self.refresh()

    def _open(self, task_id: int) -> None:
        for task in self.ctx.manager.snapshot():
            if task.id == task_id and task.output_path:
                path = Path(task.output_path)
                open_in_file_manager(path.parent if path.parent.exists() else self.ctx.settings.download_dir)

    # ------------------------------------------------------------------ refresh (timer driven)
    def refresh(self) -> int:
        """Sync rows with the manager. Returns the number of unfinished downloads."""
        manager = self.ctx.manager
        tasks = manager.snapshot()
        paused = manager.paused
        live_ids = {t.id for t in tasks}
        for task_id in list(self.rows):
            if task_id not in live_ids:
                row = self.rows.pop(task_id)
                self.list_layout.removeWidget(row)
                row.deleteLater()
        for task in tasks:
            row = self.rows.get(task.id)
            if row is None:
                row = DownloadRow(task)
                row.cancel_requested.connect(manager.cancel)
                row.retry_requested.connect(manager.retry)
                row.open_requested.connect(self._open)
                self.rows[task.id] = row
                self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            row.update_from(task, paused)
        self.empty.setVisible(not tasks)

        active = sum(1 for t in tasks if not t.status.finished)
        done = sum(1 for t in tasks if t.status in {Status.DONE, Status.SKIPPED})
        failed = sum(1 for t in tasks if t.status == Status.FAILED)
        speed = 0.0 if paused else sum(t.speed for t in tasks)
        parts = [f"{active} active", f"{done} completed"]
        if failed:
            parts.append(f"{failed} failed")
        if paused and active:
            parts.append("paused")
        elif speed:
            parts.append(f"total {format_speed(speed)}")
        self.summary.setText("  ·  ".join(parts) if tasks else "Nothing queued yet")
        if self.pause_btn.isChecked() != paused:
            self.pause_btn.blockSignals(True)
            self.pause_btn.setChecked(paused)
            self.pause_btn.setText("Resume All" if paused else "Pause All")
            self.pause_btn.blockSignals(False)
        return active
