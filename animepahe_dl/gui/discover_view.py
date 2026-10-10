"""Discover home shown on the search page before you search: cover rows for trending, this season, top rated."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..discover import SECTION_TITLES, DiscoverItem
from .theme import placeholder_poster, rounded_pixmap
from .widgets import ElidedLabel

if TYPE_CHECKING:
    from .main_window import MainWindow


def _two_lines(text: str, metrics: QFontMetrics, width: int) -> str:
    """Greedy word wrap to at most two lines; the second one is elided with '…'."""
    words, first = text.split(), ""
    while words and metrics.horizontalAdvance((first + " " + words[0]).strip()) <= width:
        first = (first + " " + words.pop(0)).strip()
    if not first:  # a single word wider than the card
        return metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)
    if not words:
        return first
    return first + "\n" + metrics.elidedText(" ".join(words), Qt.TextElideMode.ElideRight, width)


class MiniCard(QFrame):
    """Cover, title and a short info line. Clicking it searches the active site for the show."""

    chosen = Signal(object)
    POSTER_W, POSTER_H = 140, 198

    def __init__(self, item: DiscoverItem) -> None:
        super().__init__()
        self.item = item
        self.setObjectName("card")
        self.setFixedWidth(self.POSTER_W + 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(item.title if item.title == item.romaji else f"{item.title}\n{item.romaji}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        self.poster = QLabel()
        self.poster.setFixedSize(self.POSTER_W, self.POSTER_H)
        self.poster.setPixmap(placeholder_poster(item.title, self.POSTER_W, self.POSTER_H))
        layout.addWidget(self.poster)
        title = QLabel()
        title.setObjectName("cardTitle")
        bold = title.font()
        bold.setWeight(QFont.Weight.DemiBold)  # the stylesheet makes card titles bold; measure with that
        metrics = QFontMetrics(bold)
        # Two lines wrapped by hand: a word-wrapped QLabel reports a height-for-width, which makes the
        # surrounding scroll area squeeze the rows instead of scrolling.
        title.setText(_two_lines(item.title, metrics, self.POSTER_W - 6))
        title.setFixedHeight(metrics.lineSpacing() * 2 + 6)
        title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)
        info = ElidedLabel(item.info or " ")
        info.setObjectName("cardInfo")
        layout.addWidget(info)

    def set_cover(self, pixmap: QPixmap) -> None:
        self.poster.setPixmap(rounded_pixmap(pixmap, self.POSTER_W, self.POSTER_H))

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.item)
        super().mousePressEvent(event)


class DiscoverRow(QWidget):
    """One heading and a single row of cards; only as many cards as fit the width are shown."""

    GAP = 14
    fitted = Signal()

    def __init__(self, title: str) -> None:
        super().__init__()
        # Width is dictated by the window, not by the cards (which are shown or hidden to fit it).
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.strip = QHBoxLayout()
        self.strip.setSpacing(self.GAP)
        layout.addLayout(self.strip)
        self.cards: list[MiniCard] = []

    def set_cards(self, cards: list[MiniCard]) -> None:
        while self.strip.count():  # old cards and the old trailing stretch
            item = self.strip.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = cards
        for card in cards:
            self.strip.addWidget(card)
        self.strip.addStretch(1)
        self._fit()

    def _fit(self) -> None:
        if not self.cards:
            return
        step = self.cards[0].width() + self.GAP
        fit = max(2, (self.width() + self.GAP) // step)
        for index, card in enumerate(self.cards):
            card.setVisible(index < fit)
        self.fitted.emit()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().resizeEvent(event)
        self._fit()


class DiscoverView(QWidget):
    item_chosen = Signal(object)
    content_changed = Signal()  # rows were filled or shown: the surrounding scroll area must re-measure

    def __init__(self, ctx: "MainWindow") -> None:
        super().__init__()
        self.ctx = ctx
        self._loading = False
        self._loaded = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        header = QHBoxLayout()
        title = QLabel("Discover")
        title.setObjectName("sectionTitle")
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.clicked.connect(lambda: self.load(force=True))
        header.addWidget(title)
        header.addWidget(self.status, 1)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self.rows: dict[str, DiscoverRow] = {}
        for key, name in SECTION_TITLES.items():
            row = DiscoverRow(name)
            row.hide()
            row.fitted.connect(self.content_changed.emit)
            self.rows[key] = row
            layout.addWidget(row)

    def load(self, force: bool = False) -> None:
        """Fill the rows (from the cache at once when there is one, then from AniList in the background)."""
        if self._loading:
            return
        self._loading = True
        self.refresh_btn.setEnabled(False)
        cache = self.ctx.discover.cached()
        if cache and not self._loaded:
            self._show(*cache)
        elif not cache:
            self.status.setText("Loading…")

        def done(result) -> None:  # type: ignore[no-untyped-def]
            self._loading = False
            self.refresh_btn.setEnabled(True)
            self._show(*result)

        def failed(exc: Exception) -> None:
            self._loading = False
            self.refresh_btn.setEnabled(True)
            if not self._loaded:
                self.status.setText(f"Could not load suggestions ({exc}). Search above to get started.")

        self.ctx.jobs.submit(lambda: self.ctx.discover.fetch(force=force), done, failed)

    def _show(self, fetched_at: float, sections: dict[str, list[DiscoverItem]]) -> None:
        self._loaded = True
        age = max(0, time.time() - fetched_at)
        self.status.setText("Updated just now" if age < 90 else
                            f"Updated {int(age // 3600)} h ago" if age >= 3600 else f"Updated {int(age // 60)} min ago")
        for key, row in self.rows.items():
            items = sections.get(key) or []
            cards = []
            for item in items:
                card = MiniCard(item)
                card.chosen.connect(self.item_chosen.emit)
                cards.append(card)
                if item.cover_url:
                    self.ctx.load_image(item.cover_url, card, card.set_cover)
            row.set_cards(cards)
            row.setVisible(bool(cards))
        self.content_changed.emit()
