"""Windows 11 friendly look: Fusion style that follows the system light/dark setting."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

ACCENT = QColor("#8b5cf6")


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return False


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Segoe UI Variable Text", 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    palette = QPalette()
    if system_is_dark():
        base, window, text, alt = QColor("#1f1f1f"), QColor("#272727"), QColor("#f3f3f3"), QColor("#2c2c2c")
        palette.setColor(QPalette.ColorRole.Window, window)
        palette.setColor(QPalette.ColorRole.WindowText, text)
        palette.setColor(QPalette.ColorRole.Base, base)
        palette.setColor(QPalette.ColorRole.AlternateBase, alt)
        palette.setColor(QPalette.ColorRole.Text, text)
        palette.setColor(QPalette.ColorRole.Button, QColor("#333333"))
        palette.setColor(QPalette.ColorRole.ButtonText, text)
        palette.setColor(QPalette.ColorRole.ToolTipBase, alt)
        palette.setColor(QPalette.ColorRole.ToolTipText, text)
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9a9a9a"))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#777777"))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#777777"))
    else:
        palette = app.style().standardPalette()
    palette.setColor(QPalette.ColorRole.Highlight, ACCENT)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, ACCENT)
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QPushButton { padding: 6px 14px; border-radius: 6px; border: 1px solid palette(mid);
                      background: palette(button); }
        QPushButton:hover { border-color: #8b5cf6; }
        QPushButton:pressed { background: palette(midlight); }
        QPushButton#primary { background: #8b5cf6; color: white; border: none; font-weight: 600; }
        QPushButton#primary:hover { background: #7c3aed; }
        QPushButton#primary:disabled { background: #6b6b6b; }
        QLineEdit, QComboBox, QSpinBox { padding: 5px; border-radius: 6px; }
        QTabBar::tab { padding: 8px 18px; }
        QProgressBar { border-radius: 5px; text-align: center; min-height: 18px; }
        QProgressBar::chunk { background: #8b5cf6; border-radius: 5px; }
        """
    )


def app_icon() -> QIcon:
    """Draw a simple icon at runtime so no binary asset is needed."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(ACCENT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)
        painter.setBrush(QColor("white"))
        # Download arrow
        w = size
        painter.drawRect(int(w * 0.43), int(w * 0.18), int(w * 0.14), int(w * 0.36))
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPolygonF

        painter.drawPolygon(QPolygonF([QPointF(w * 0.25, w * 0.50), QPointF(w * 0.75, w * 0.50),
                                       QPointF(w * 0.50, w * 0.74)]))
        painter.drawRect(int(w * 0.22), int(w * 0.78), int(w * 0.56), max(1, int(w * 0.07)))
        painter.end()
        icon.addPixmap(pix)
    return icon
