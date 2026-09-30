"""Visual style: colour tokens for light/dark mode, the app stylesheet and vector icons."""

from __future__ import annotations

import math
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette, QPen,
    QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QApplication

ACCENT = "#8b5cf6"
ACCENT_HOVER = "#7c3aed"

DARK = {
    "bg": "#15151a", "sidebar": "#1b1b22", "surface": "#1f1f27", "surface2": "#272731", "border": "#32323e",
    "text": "#ececf1", "muted": "#9b9bab", "hover": "#2a2a35", "input": "#1a1a21",
}
LIGHT = {
    "bg": "#f4f4f7", "sidebar": "#ebebf0", "surface": "#ffffff", "surface2": "#f3f3f7", "border": "#dedee6",
    "text": "#1b1b21", "muted": "#6b6b78", "hover": "#e4e4ec", "input": "#ffffff",
}
STATUS_COLORS = {
    "queued": "#9ca3af", "resolving": "#38bdf8", "downloading": ACCENT, "stitching": "#f59e0b",
    "completed": "#22c55e", "failed": "#ef4444", "cancelled": "#9ca3af", "paused": "#f59e0b",
}

TOKENS = DARK


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return False


def _write_assets(t: dict[str, str]) -> dict[str, str]:
    """Small SVGs for checkbox ticks and arrows (stylesheets need image files for these)."""
    from ..config import app_data_dir

    folder = app_data_dir() / "ui"
    folder.mkdir(parents=True, exist_ok=True)
    muted = t["muted"]
    svgs = {
        "check": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" '
                 'fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "down": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12"><path d="M2.5 4.5l3.5 3.5 3.5-3.5" '
                f'fill="none" stroke="{muted}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "up": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12"><path d="M2.5 7.5l3.5-3.5 3.5 3.5" '
              f'fill="none" stroke="{muted}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    }
    paths = {}
    for name, svg in svgs.items():
        path = folder / f"{name}-{muted.lstrip('#')}.svg"
        try:
            if not path.exists():
                path.write_text(svg, encoding="utf-8")
            paths[name] = path.as_posix()
        except OSError:
            paths[name] = ""
    return paths


def _stylesheet(t: dict[str, str]) -> str:
    a = _write_assets(t)
    pills = "\n".join(
        f'QLabel#pill[state="{name}"] {{ color: {color}; border: 1px solid {color}; }}'
        for name, color in STATUS_COLORS.items()
    )
    return f"""
    QWidget {{ color: {t['text']}; }}
    QMainWindow, QWidget#page, QStackedWidget#pages, QScrollArea, QWidget#scrollBody {{ background: {t['bg']}; }}
    QScrollArea {{ border: none; }}
    QToolTip {{ background: {t['surface2']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 4px; }}

    QFrame#sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['border']}; }}
    QLabel#appName {{ font-size: 16px; font-weight: 700; }}
    QLabel#appVersion {{ color: {t['muted']}; font-size: 11px; }}
    QPushButton#navButton {{
        text-align: left; padding: 10px 14px; border: none; border-radius: 8px;
        background: transparent; color: {t['muted']}; font-size: 14px;
    }}
    QPushButton#navButton:hover {{ background: {t['hover']}; color: {t['text']}; }}
    QPushButton#navButton:checked {{ background: {t['surface2']}; color: {t['text']}; font-weight: 600;
        border-left: 3px solid {ACCENT}; }}

    QLabel#pageTitle {{ font-size: 24px; font-weight: 700; }}
    QLabel#sectionTitle {{ font-size: 15px; font-weight: 600; }}
    QLabel#muted, QLabel#cardInfo {{ color: {t['muted']}; }}
    QLabel#emptyState {{ color: {t['muted']}; font-size: 15px; padding: 60px; }}
    QLabel#cardTitle {{ font-size: 13px; font-weight: 600; }}

    QLineEdit, QComboBox, QSpinBox {{
        background: {t['input']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 7px 10px;
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
    QLineEdit#searchInput {{ font-size: 15px; padding: 11px 16px; border-radius: 10px; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
        selection-background-color: {ACCENT}; }}

    QPushButton {{
        background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 7px 14px;
    }}
    QPushButton:hover {{ border-color: {ACCENT}; }}
    QPushButton:pressed {{ background: {t['hover']}; }}
    QPushButton:disabled {{ color: {t['muted']}; }}
    QPushButton#primary {{ background: {ACCENT}; color: white; border: none; padding: 8px 18px; }}
    QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
    QPushButton#primary:disabled {{ background: {t['border']}; color: {t['muted']}; }}
    QPushButton#searchButton {{ background: {ACCENT}; color: white; border: none;
        font-size: 15px; padding: 11px 26px; border-radius: 10px; }}
    QPushButton#searchButton:hover {{ background: {ACCENT_HOVER}; }}
    QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {t['muted']};
        padding: 5px 10px; }}
    QPushButton#ghost:hover {{ background: {t['hover']}; color: {t['text']}; }}
    QPushButton#toggle:checked {{ background: #f59e0b; color: #1b1b21; border: none; }}

    QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
    QFrame#card:hover {{ border: 1px solid {ACCENT}; }}
    QFrame#panel {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
    QFrame#queueRow {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}

    QLabel#pill {{ border-radius: 10px; padding: 2px 10px; font-size: 12px; font-weight: 600; }}
    {pills}

    QListWidget#episodeList {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px;
        padding: 6px; outline: none; }}
    QListWidget#episodeList::item {{ padding: 9px 8px; border-radius: 8px; }}
    QListWidget#episodeList::item:hover {{ background: {t['hover']}; }}
    QListWidget#episodeList::item:selected {{ background: {t['surface2']}; color: {t['text']}; }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator, QListWidget#episodeList::indicator {{
        width: 16px; height: 16px; border: 1px solid {t['muted']}; border-radius: 4px; background: {t['input']};
    }}
    QCheckBox::indicator:hover, QListWidget#episodeList::indicator:hover {{ border-color: {ACCENT}; }}
    QCheckBox::indicator:checked, QListWidget#episodeList::indicator:checked {{
        background: {ACCENT}; border-color: {ACCENT}; image: url({a['check']});
    }}
    QComboBox {{ padding-right: 28px; }}
    QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
    QComboBox::down-arrow {{ image: url({a['down']}); width: 12px; height: 12px; }}
    QSpinBox {{ padding-right: 24px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ border: none; background: transparent; width: 22px; }}
    QSpinBox::up-arrow {{ image: url({a['up']}); width: 10px; height: 10px; }}
    QSpinBox::down-arrow {{ image: url({a['down']}); width: 10px; height: 10px; }}
    QProgressBar {{ background: {t['surface2']}; border: none; border-radius: 4px; max-height: 8px; }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
    QProgressBar[state="completed"]::chunk {{ background: {STATUS_COLORS['completed']}; }}
    QProgressBar[state="failed"]::chunk {{ background: {STATUS_COLORS['failed']}; }}
    QProgressBar[state="paused"]::chunk, QProgressBar[state="stitching"]::chunk {{ background: #f59e0b; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    QStatusBar {{ background: {t['sidebar']}; color: {t['muted']}; border-top: 1px solid {t['border']}; }}
    """


def apply_theme(app: QApplication) -> None:
    global TOKENS
    TOKENS = DARK if system_is_dark() else LIGHT
    app.setStyle("Fusion")
    family = "Segoe UI Variable Text" if sys.platform == "win32" else app.font().family()
    font = QFont(family, 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    palette = QPalette()
    t = TOKENS
    for role, key in (
        (QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.Base, "input"),
        (QPalette.ColorRole.AlternateBase, "surface2"), (QPalette.ColorRole.Button, "surface2"),
        (QPalette.ColorRole.ToolTipBase, "surface2"),
    ):
        palette.setColor(role, QColor(t[key]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.ToolTipText):
        palette.setColor(role, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["muted"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    palette.setColor(QPalette.ColorRole.Mid, QColor(t["border"]))
    app.setPalette(palette)
    app.setStyleSheet(_stylesheet(t))


def emphasize(widget):  # type: ignore[no-untyped-def]
    """Semi-bold text set on the widget's font (not the stylesheet) so its size hint accounts for it."""
    font = widget.font()
    font.setWeight(QFont.Weight.DemiBold)
    widget.setFont(font)
    return widget


def repolish(widget) -> None:  # type: ignore[no-untyped-def]
    """Re-apply the stylesheet after a dynamic property (e.g. 'state') changes."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# ----------------------------------------------------------------------------- icons
def _pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw(kind: str, painter: QPainter, s: float, color: QColor) -> None:
    painter.setPen(_pen(color, s * 0.09))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "search":
        painter.drawEllipse(QRectF(s * 0.14, s * 0.14, s * 0.5, s * 0.5))
        painter.drawLine(QPointF(s * 0.56, s * 0.56), QPointF(s * 0.86, s * 0.86))
    elif kind == "download":
        painter.drawLine(QPointF(s * 0.5, s * 0.12), QPointF(s * 0.5, s * 0.62))
        painter.drawPolyline(QPolygonF([QPointF(s * 0.28, s * 0.42), QPointF(s * 0.5, s * 0.64),
                                        QPointF(s * 0.72, s * 0.42)]))
        painter.drawPolyline(QPolygonF([QPointF(s * 0.15, s * 0.7), QPointF(s * 0.15, s * 0.86),
                                        QPointF(s * 0.85, s * 0.86), QPointF(s * 0.85, s * 0.7)]))
    elif kind == "settings":
        center = QPointF(s / 2, s / 2)
        for i in range(8):
            angle = i * math.pi / 4
            painter.drawLine(QPointF(s / 2 + math.cos(angle) * s * 0.3, s / 2 + math.sin(angle) * s * 0.3),
                             QPointF(s / 2 + math.cos(angle) * s * 0.4, s / 2 + math.sin(angle) * s * 0.4))
        painter.drawEllipse(center, s * 0.27, s * 0.27)
        painter.drawEllipse(center, s * 0.1, s * 0.1)
    elif kind == "shield":
        path = QPainterPath(QPointF(s * 0.5, s * 0.1))
        path.lineTo(s * 0.82, s * 0.22)
        path.cubicTo(s * 0.82, s * 0.6, s * 0.7, s * 0.78, s * 0.5, s * 0.9)
        path.cubicTo(s * 0.3, s * 0.78, s * 0.18, s * 0.6, s * 0.18, s * 0.22)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawPolyline(QPolygonF([QPointF(s * 0.36, s * 0.5), QPointF(s * 0.47, s * 0.61),
                                        QPointF(s * 0.66, s * 0.4)]))
    elif kind == "back":
        painter.drawPolyline(QPolygonF([QPointF(s * 0.6, s * 0.2), QPointF(s * 0.3, s * 0.5),
                                        QPointF(s * 0.6, s * 0.8)]))


def line_icon(kind: str, active_color: str | None = None) -> QIcon:
    """Simple stroked icon; uses the accent colour when the (checkable) button is checked."""
    icon = QIcon()
    normal = QColor(TOKENS["muted"])
    active = QColor(active_color or ACCENT)
    for size in (16, 20, 24, 32, 48):
        for color, state in ((normal, QIcon.State.Off), (active, QIcon.State.On)):
            pix = QPixmap(size, size)
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            _draw(kind, painter, size, color)
            painter.end()
            icon.addPixmap(pix, QIcon.Mode.Normal, state)
    return icon


def placeholder_poster(title: str, width: int, height: int) -> QPixmap:
    """Gradient cover with the title's initials, shown until the real poster loads."""
    pix = QPixmap(width, height)
    pix.fill(Qt.GlobalColor.transparent)
    hue = (sum(map(ord, title)) * 37) % 360
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor.fromHsl(hue, 120, 70))
    gradient.setColorAt(1, QColor.fromHsl((hue + 40) % 360, 140, 40))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), 10, 10)
    painter.fillPath(path, QBrush(gradient))
    initials = "".join(w[0] for w in title.split()[:2] if w and w[0].isalnum()).upper() or "?"
    font = QFont(QApplication.font())
    font.setPixelSize(int(height * 0.18))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 220))
    painter.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, initials)
    painter.end()
    return pix


def rounded_pixmap(source: QPixmap, width: int, height: int, radius: float = 10) -> QPixmap:
    scaled = source.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    x = (scaled.width() - width) // 2
    y = (scaled.height() - height) // 2
    scaled = scaled.copy(x, y, width, height)
    out = QPixmap(width, height)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return out


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(ACCENT))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)
        _draw("download", painter, size, QColor("white"))
        painter.end()
        icon.addPixmap(pix)
    return icon
