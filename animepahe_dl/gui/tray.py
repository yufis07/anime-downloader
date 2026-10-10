"""System-tray icon: status tooltip, a small menu and desktop notifications."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .theme import app_icon


class TrayController(QObject):
    open_requested = Signal()
    pause_toggled = Signal()
    quit_requested = Signal()
    message_clicked = Signal(str)  # which page the notification was about: "queue" | "watchlist"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.icon: QSystemTrayIcon | None = None
        self._target = "queue"
        self._tooltip = ""
        if not self.available:
            return
        self.icon = QSystemTrayIcon(app_icon(), self)
        menu = QMenu()
        open_action = QAction("Open Anime Downloader", menu)
        open_action.triggered.connect(self.open_requested.emit)
        self.pause_action = QAction("Pause all", menu)
        self.pause_action.triggered.connect(self.pause_toggled.emit)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(open_action)
        menu.addAction(self.pause_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._menu = menu  # keep the menu alive
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)
        self.icon.messageClicked.connect(lambda: self.message_clicked.emit(self._target))
        self.icon.setToolTip("Anime Downloader")

    @property
    def visible(self) -> bool:
        return bool(self.icon and self.icon.isVisible())

    def set_enabled(self, enabled: bool) -> None:
        if self.icon:
            self.icon.setVisible(enabled)

    def set_status(self, active: int, speed_text: str, paused: bool) -> None:
        """Tooltip and menu text; cheap to call on every timer tick."""
        if not self.icon:
            return
        if active:
            tip = f"Anime Downloader — {active} download{'s' if active != 1 else ''}"
            tip += " (paused)" if paused else (f", {speed_text}" if speed_text else "")
        else:
            tip = "Anime Downloader"
        if tip != self._tooltip:
            self._tooltip = tip
            self.icon.setToolTip(tip)
        label = "Resume all" if paused else "Pause all"
        if self.pause_action.text() != label:
            self.pause_action.setText(label)

    def notify(self, title: str, message: str, target: str = "queue") -> bool:
        """Show a desktop notification; False when the tray icon is not available or hidden."""
        if not self.icon or not self.icon.isVisible():
            return False
        self._target = target
        self.icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 8000)
        return True

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_requested.emit()
