"""Header of the show page: banner, poster, titles, fact chips, genres and a collapsible synopsis."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..details import ShowDetails
from . import theme
from .theme import line_icon, placeholder_poster, rounded_pixmap


class BannerLabel(QWidget):
    """Banner picture cropped to fill the width, with a fade into the card colour at the bottom."""

    HEIGHT = 120

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        radius = 13.0
        clip.addRoundedRect(rect.adjusted(0, 0, 0, radius + 1), radius, radius)  # round the top corners only
        painter.setClipPath(clip)
        surface = QColor(theme.TOKENS["surface"])
        if self._pixmap is None or self._pixmap.isNull():
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            gradient.setColorAt(0, QColor(theme.ACCENT_HOVER))
            gradient.setColorAt(1, QColor(theme.TOKENS["surface2"]))
            painter.fillRect(rect, gradient)
        else:
            scaled = self._pixmap.scaled(self.size() * self.devicePixelRatioF(),
                                         Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(self.devicePixelRatioF())
            x = (scaled.width() / self.devicePixelRatioF() - rect.width()) / 2
            y = (scaled.height() / self.devicePixelRatioF() - rect.height()) / 3
            painter.drawPixmap(0, 0, scaled, int(x * self.devicePixelRatioF()), int(y * self.devicePixelRatioF()),
                               scaled.width(), scaled.height())
        fade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        transparent = QColor(surface)
        transparent.setAlpha(0)
        fade.setColorAt(0.35, transparent)
        fade.setColorAt(1, surface)
        painter.fillRect(rect, fade)


def _chip(text: str, kind: str = "chip") -> QLabel:
    label = QLabel(text)
    label.setObjectName(kind)
    return label


class ShowHeader(QFrame):
    POSTER_W, POSTER_H = 132, 186
    SYNOPSIS_LINES = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 14)
        outer.setSpacing(0)

        self.banner = BannerLabel()
        outer.addWidget(self.banner)

        bar = QHBoxLayout()
        bar.setContentsMargins(14, 8, 18, 0)
        self.back_btn = QPushButton("  Back to results")
        self.back_btn.setObjectName("ghost")
        self.back_btn.setIcon(line_icon("back"))
        self.follow_btn = QPushButton()
        self.follow_btn.setCheckable(True)
        self.follow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bar.addWidget(self.back_btn)
        bar.addStretch(1)
        bar.addWidget(self.follow_btn)
        outer.addLayout(bar)

        body = QHBoxLayout()
        body.setContentsMargins(18, 6, 18, 0)
        body.setSpacing(20)
        self.poster = QLabel()
        self.poster.setFixedSize(self.POSTER_W, self.POSTER_H)
        body.addWidget(self.poster, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.title.setWordWrap(True)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        self.meta = QLabel()  # plain release info from the site, shown until AniList answers
        self.meta.setObjectName("muted")
        self.meta.setWordWrap(True)
        self.facts = QHBoxLayout()
        self.facts.setSpacing(8)
        self.genres = QHBoxLayout()
        self.genres.setSpacing(6)
        self.synopsis = QLabel()
        self.synopsis.setWordWrap(True)
        self.synopsis.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.more_btn = QPushButton("Show more")
        self.more_btn.setObjectName("ghost")
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.clicked.connect(self._toggle_synopsis)
        info.addWidget(self.title)
        info.addWidget(self.subtitle)
        info.addWidget(self.meta)
        info.addLayout(self.facts)
        info.addLayout(self.genres)
        info.addWidget(self.synopsis)
        info.addWidget(self.more_btn, 0, Qt.AlignmentFlag.AlignLeft)
        info.addStretch(1)
        body.addLayout(info, 1)
        outer.addLayout(body)
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self, title: str = "", meta: str = "") -> None:
        self.title.setText(title)
        self.subtitle.clear()
        self.subtitle.hide()
        self.meta.setText(meta)
        self.meta.setVisible(bool(meta))
        self._clear(self.facts)
        self._clear(self.genres)
        self.synopsis.clear()
        self.synopsis.hide()
        self.more_btn.hide()
        self._expanded = False
        self._full_synopsis = ""
        self.banner.set_pixmap(None)
        self.banner.setVisible(False)
        self.poster.setPixmap(placeholder_poster(title, self.POSTER_W, self.POSTER_H))

    @staticmethod
    def _clear(layout: QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def set_cover(self, pixmap: QPixmap) -> None:
        self.poster.setPixmap(rounded_pixmap(pixmap, self.POSTER_W, self.POSTER_H, 10))

    def set_banner(self, pixmap: QPixmap) -> None:
        self.banner.set_pixmap(pixmap)
        self.banner.setVisible(True)

    def set_details(self, details: ShowDetails) -> None:
        main = self.title.text().strip().lower()
        others = [n for n in (details.romaji, details.english) if n and n.strip().lower() != main]
        if others:
            self.subtitle.setText("  ·  ".join(others))
            self.subtitle.show()
        if details.facts:
            self.meta.hide()
        self._clear(self.facts)
        for fact in details.facts:
            self.facts.addWidget(_chip(fact, "factChip"))
        self.facts.addStretch(1)
        self._clear(self.genres)
        for genre in details.genres[:7]:
            self.genres.addWidget(_chip(genre))
        self.genres.addStretch(1)
        self._full_synopsis = details.synopsis
        self._expanded = False
        self._apply_synopsis()
        if not details.banner_url:  # no banner picture: keep the accent gradient as a header band
            self.banner.setVisible(True)

    # ------------------------------------------------------------------ synopsis
    def _apply_synopsis(self) -> None:
        text = self._full_synopsis
        self.synopsis.setVisible(bool(text))
        self.synopsis.setText(text)
        line = self.synopsis.fontMetrics().lineSpacing()
        long_text = len(text) > 320 or text.count("\n") >= self.SYNOPSIS_LINES
        self.synopsis.setMaximumHeight(16777215 if self._expanded or not long_text else line * self.SYNOPSIS_LINES + 4)
        self.more_btn.setVisible(long_text)
        self.more_btn.setText("Show less" if self._expanded else "Show more")

    def _toggle_synopsis(self) -> None:
        self._expanded = not self._expanded
        self._apply_synopsis()
