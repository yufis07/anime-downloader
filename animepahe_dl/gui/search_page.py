"""'Search & Discover': search bar, card grid of results and the episode selection sub-view."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from ..animepahe import Anime, Episode, parse_anime_session
from ..mal import MalLookup
from ..animeheaven import parse_anime_id
from ..config import AUDIO_CHOICES, QUALITIES, SITE_LABELS, SITES
from ..utils import format_episode, parse_episode_selection
from .theme import emphasize, line_icon, placeholder_poster, rounded_pixmap
from .detail_header import ShowHeader
from .discover_view import DiscoverView
from .widgets import AnimeCard, FlowLayout

if TYPE_CHECKING:
    from .main_window import MainWindow

def _norm(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


AUDIO_LABELS = {"jpn": "Japanese (sub)", "eng": "English (dub)", "any": "Any audio"}


class SearchPage(QWidget):
    def __init__(self, ctx: "MainWindow") -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(16)

        self.page_title = QLabel("Search & Discover")
        self.page_title.setObjectName("pageTitle")
        layout.addWidget(self.page_title)

        self.search_bar = QWidget()
        bar = QHBoxLayout(self.search_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(10)
        self.site = QComboBox()
        self.site.setToolTip("Which site to search and download from")
        for key in SITES:
            self.site.addItem(SITE_LABELS[key], key)
        self.site.setCurrentIndex(max(0, self.site.findData(ctx.settings.site)))
        self.site.currentIndexChanged.connect(self._site_changed)
        self.input = QLineEdit()
        self.input.setObjectName("searchInput")
        self.input.setPlaceholderText("Search anime by title, or paste an AnimePahe link…")
        self.input.setClearButtonEnabled(True)
        self.input.addAction(line_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.input.returnPressed.connect(self.search)
        self.search_btn = emphasize(QPushButton("Search"))
        self.search_btn.setObjectName("searchButton")
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_btn.clicked.connect(self.search)
        self.jp_btn = QPushButton("Japanese title")
        self.jp_btn.setToolTip("Look the English title up on MyAnimeList and show its Japanese (romaji) title")
        self.jp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.jp_btn.clicked.connect(self.lookup_japanese)
        bar.addWidget(self.site)
        bar.addWidget(self.input, 1)
        bar.addWidget(self.search_btn)
        bar.addWidget(self.jp_btn)
        layout.addWidget(self.search_bar)
        self.jp_label = QLabel("")
        self.jp_label.setObjectName("muted")
        self.jp_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.jp_label.hide()
        layout.addWidget(self.jp_label)
        self.mal = MalLookup()

        self.views = QStackedWidget()
        layout.addWidget(self.views, 1)
        # The show page needs the whole height, so the search bar steps aside while it is open.
        self.views.currentChanged.connect(self._view_changed)

        # --- results grid
        self.results_view = QWidget()
        rv = QVBoxLayout(self.results_view)
        rv.setContentsMargins(0, 0, 0, 0)
        self.results_label = QLabel("")
        self.results_label.setObjectName("muted")
        rv.addWidget(self.results_label)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("scrollBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(4, 4, 4, 16)
        self.empty = QLabel("Search for an anime to get started.\nTry “Frieren”, “One Piece” or paste a show link.")
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(self.empty)
        self.grid_host = QWidget()
        self.grid = FlowLayout(self.grid_host)
        body_layout.addWidget(self.grid_host)
        body_layout.addStretch(1)
        self.scroll.setWidget(body)
        rv.addWidget(self.scroll, 1)
        # Discover home: its own scroll area (a plain vertical layout), swapped with the results grid.
        self.discover = DiscoverView(ctx)
        self.discover.item_chosen.connect(self.search_for)
        self.discover_scroll = QScrollArea()
        self.discover_scroll.setWidgetResizable(True)
        self.discover_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        discover_body = self.discover_body = QWidget()
        discover_body.setObjectName("scrollBody")
        self.discover.content_changed.connect(self._sync_discover_height)
        db = QVBoxLayout(discover_body)
        db.setContentsMargins(4, 4, 8, 16)
        db.addWidget(self.discover)
        db.addStretch(1)
        self.discover_scroll.setWidget(discover_body)
        rv.addWidget(self.discover_scroll, 1)
        self.views.addWidget(self.results_view)

        # --- episode selection
        self.episodes_view = EpisodePanel(ctx)
        self.episodes_view.back_requested.connect(lambda: self.views.setCurrentWidget(self.results_view))
        self.views.addWidget(self.episodes_view)
        self.cards: list[AnimeCard] = []
        self._set_discover(True)  # the Discover home fills the page until the first search
        self.input.textChanged.connect(self._text_changed)
        QTimer.singleShot(400, self.discover.load)

    # ------------------------------------------------------------------ search
    def search(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.views.setCurrentWidget(self.results_view)
        self._set_discover(False)
        self._set_loading(True, f"Searching for “{text}”…")
        site = self.site.currentData()
        provider = self.ctx.provider(site)
        session = parse_anime_id(text) if site == "animeheaven" else parse_anime_session(text)
        if session:
            def load() -> list[Anime]:
                return [Anime(session=session, title=provider.anime_title(session), site=site)]
        else:
            def load() -> list[Anime]:
                return provider.search(text)
        self.ctx.run(load, self._show_results, retry=self.search, on_error=lambda: self._set_loading(False))

    def show_discover(self) -> None:
        """Back to the Discover home (used when the search box is cleared)."""
        self.results_label.setText("")
        self.grid.clear()
        self.cards = []
        self._set_discover(True)

    def _sync_discover_height(self) -> None:
        """QScrollArea does not grow its widget to the layout's minimum height on its own, so the rows
        would be squeezed instead of scrolled; state the minimum explicitly."""
        QTimer.singleShot(0, self._apply_discover_height)

    def _apply_discover_height(self) -> None:
        height = self.discover.minimumSizeHint().height() + 24
        if height != self.discover_body.minimumHeight():
            self.discover_body.setMinimumHeight(height)

    def _set_discover(self, on: bool) -> None:
        self.discover_scroll.setVisible(on)
        self.scroll.setVisible(not on)
        self.results_label.setVisible(not on)
        if on:
            self.empty.hide()

    def _text_changed(self, text: str) -> None:
        if not text.strip() and self.views.currentWidget() is self.results_view and self.search_btn.isEnabled():
            self.show_discover()

    def search_for(self, item) -> None:  # type: ignore[no-untyped-def]
        """A Discover title was clicked: find it on the active site, trying the English name first."""
        site = self.site.currentData()
        provider = self.ctx.provider(site)
        names = item.search_titles
        self.input.blockSignals(True)
        self.input.setText(names[0])
        self.input.blockSignals(False)
        self.views.setCurrentWidget(self.results_view)
        self._set_discover(False)
        self._set_loading(True, f"Looking for “{names[0]}” on {SITE_LABELS[site]}…")

        def load() -> list[Anime]:
            for name in names:
                found = provider.search(name)
                if found:
                    return found
            return []

        def done(results: list[Anime]) -> None:
            self._show_results(results)
            wanted = {_norm(n) for n in names}
            exact = [a for a in results if _norm(a.title) in wanted]
            if len(exact) == 1:  # unmistakable: go straight to its episodes
                self.open_anime(exact[0])

        self.ctx.run(load, done, retry=lambda: self.search_for(item), on_error=lambda: self._set_loading(False))

    def _view_changed(self, _index: int) -> None:
        searching = self.views.currentWidget() is self.results_view
        self.page_title.setVisible(searching)
        self.search_bar.setVisible(searching)
        if not searching:
            self.jp_label.hide()

    def _site_changed(self) -> None:
        self.ctx.settings.site = self.site.currentData()
        self.ctx.settings.save()

    def lookup_japanese(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.jp_btn.setEnabled(False)
        self.jp_label.setText(f"Looking up “{text}” on MyAnimeList…")
        self.jp_label.show()

        def done(match) -> None:  # type: ignore[no-untyped-def]
            self.jp_btn.setEnabled(True)
            if match:
                self.jp_label.setText(match.title)
            else:
                self.jp_label.setText("No match found on MyAnimeList.")

        def failed(exc: Exception) -> None:
            self.jp_btn.setEnabled(True)
            self.jp_label.setText(f"MyAnimeList lookup failed: {exc}")

        self.ctx.jobs.submit(lambda: self.mal.japanese_title(text), done, failed)

    def _set_loading(self, loading: bool, message: str = "") -> None:
        self.search_btn.setEnabled(not loading)
        self.search_btn.setText("Searching…" if loading else "Search")
        if message:
            self.results_label.setText(message)

    def _show_results(self, results: list[Anime]) -> None:
        self._set_loading(False)
        self.grid.clear()
        self.cards = []
        self._set_discover(False)
        self.empty.setVisible(not results)
        if not results:
            self.empty.setText("No anime matched your search.\nCheck the spelling or try another title.")
            self.results_label.setText("")
            return
        self.results_label.setText(f"{len(results)} result{'s' if len(results) != 1 else ''}")
        for anime in results:
            card = AnimeCard(anime)
            card.view_requested.connect(self.open_anime)
            self.grid.addWidget(card)
            self.cards.append(card)
            if anime.poster:
                self.ctx.load_image(anime.poster, card, card.set_cover)
        self.scroll.verticalScrollBar().setValue(0)

    def open_anime(self, anime: Anime) -> None:
        self.episodes_view.load(anime)
        self.views.setCurrentWidget(self.episodes_view)


class EpisodePanel(QWidget):
    """Episode checklist with Select All, range selection and bulk 'Add to Queue'."""

    back_requested = Signal()

    def __init__(self, ctx: "MainWindow") -> None:
        super().__init__()
        self.ctx = ctx
        self.anime: Anime | None = None
        self.episodes: list[Episode] = []
        self.have: set[float] = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.header = ShowHeader()
        self.header.back_btn.clicked.connect(self.back_requested.emit)
        self.header.follow_btn.clicked.connect(self._toggle_follow)
        self.follow_btn = self.header.follow_btn
        self.poster, self.title, self.meta = self.header.poster, self.header.title, self.header.meta
        layout.addWidget(self.header)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.select_all = QCheckBox("Select All")
        self.select_all.setTristate(False)
        self.select_all.clicked.connect(self._toggle_all)
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText("Range, e.g. 1-12, 15, 20-")
        self.range_edit.setMaximumWidth(220)
        self.range_edit.returnPressed.connect(self._apply_range)
        range_btn = QPushButton("Select range")
        range_btn.clicked.connect(self._apply_range)
        missing_btn = QPushButton("Select missing")
        missing_btn.setToolTip("Select every episode you have not downloaded yet")
        missing_btn.clicked.connect(self._select_missing)
        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.count_label.setMinimumWidth(self.count_label.fontMetrics().horizontalAdvance("9999 of 9999 selected") + 8)
        controls.addWidget(self.select_all)
        controls.addSpacing(12)
        controls.addWidget(self.range_edit)
        controls.addWidget(range_btn)
        controls.addWidget(missing_btn)
        controls.addStretch(1)
        controls.addWidget(self.count_label)
        layout.addLayout(controls)

        self.list = QListWidget()
        self.list.setObjectName("episodeList")
        self.list.setUniformItemSizes(True)
        self.list.itemChanged.connect(self._update_count)
        self.list.itemClicked.connect(self._toggle_item)
        layout.addWidget(self.list, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.quality = QComboBox()
        for q in QUALITIES:
            self.quality.addItem(f"{q}p", q)
        self.audio = QComboBox()
        for a in AUDIO_CHOICES:
            self.audio.addItem(AUDIO_LABELS[a], a)
        self.quality.currentIndexChanged.connect(self._save_prefs)
        self.audio.currentIndexChanged.connect(self._save_prefs)
        self.add_btn = emphasize(QPushButton("Add to Queue"))
        self.add_btn.setObjectName("primary")
        self.add_btn.setEnabled(False)
        # Text changes with the selection count; reserve room for the widest label.
        self.add_btn.setMinimumWidth(self.add_btn.fontMetrics().horizontalAdvance("Add 9999 to Queue") + 44)
        self.add_btn.clicked.connect(self._add_to_queue)
        footer.addStretch(1)
        footer.addWidget(QLabel("Quality"))
        footer.addWidget(self.quality)
        footer.addWidget(QLabel("Audio"))
        footer.addWidget(self.audio)
        footer.addSpacing(8)
        footer.addWidget(self.add_btn)
        layout.addLayout(footer)

    # ------------------------------------------------------------------ loading
    def load(self, anime: Anime) -> None:
        self.anime = anime
        self.episodes = []
        self.header.reset(anime.title, anime.subtitle or "Loading details…")
        if anime.poster:
            self.ctx.load_image(anime.poster, self, self._set_cover(anime))
        self.quality.setCurrentIndex(max(0, self.quality.findData(self.ctx.settings.quality)))
        self.audio.setCurrentIndex(max(0, self.audio.findData(self.ctx.settings.audio)))
        self.have = set()
        self._update_follow_button()
        self.list.clear()
        placeholder = QListWidgetItem("Loading episodes…")
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(placeholder)
        self.select_all.setChecked(False)
        self._update_count()

        def done(episodes: list[Episode]) -> None:
            if self.anime is anime:
                self._fill(episodes)

        heaven = anime.site == "animeheaven"
        self.quality.setEnabled(not heaven)  # AnimeHeaven offers a single video per episode
        self.audio.setEnabled(not heaven)
        provider = self.ctx.provider(anime.site)
        self.ctx.run(lambda: provider.episodes(anime.session), done, retry=lambda: self.load(anime))
        self.ctx.jobs.submit(lambda: self.ctx.details.fetch(anime.title), lambda d: self._show_details(anime, d),
                             lambda _exc: None)

    def _show_details(self, anime: Anime, details) -> None:  # type: ignore[no-untyped-def]
        """Synopsis, genres, score and banner from AniList (silently skipped when unavailable)."""
        if details is None or self.anime is not anime:
            return
        self.header.set_details(details)
        if details.banner_url:
            self.ctx.load_image(details.banner_url, self,
                                lambda pix: self.header.set_banner(pix) if self.anime is anime else None)

    def _set_cover(self, anime: Anime):  # type: ignore[no-untyped-def]
        def apply(pix: QPixmap) -> None:
            if self.anime is anime:
                self.header.set_cover(pix)
        return apply

    def _fill(self, episodes: list[Episode]) -> None:
        self.episodes = episodes
        self.have: set[float] = set()
        if self.anime:
            library = self.ctx.library
            self.have = library.downloaded_numbers(self.anime.site, self.anime.session)
            library.acknowledge(self.anime.site, self.anime.session, [e.number for e in episodes])
            self.ctx.update_watchlist_badge()
            self._update_follow_button()
        self.list.blockSignals(True)
        self.list.clear()
        for ep in episodes:
            parts = [f"Episode {format_episode(ep.number)}" + ("  ✓" if ep.number in self.have else "")]
            if ep.title:
                parts.append(ep.title)
            if ep.duration:
                parts.append(ep.duration)
            if ep.created_at:
                parts.append(ep.created_at[:10])
            if ep.filler:
                parts.append("filler")
            item = QListWidgetItem("     ".join(p for p in parts if p))
            # Not ItemIsUserCheckable: the row-click handler is the single toggle path, so a click on the
            # checkbox itself is not counted twice.
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, ep)
            self.list.addItem(item)
        if not episodes:
            empty = QListWidgetItem("No episodes are available for this title yet.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        self.list.blockSignals(False)
        if self.anime and not self.anime.subtitle:
            self.meta.setText(f"{len(episodes)} episodes")
        self._update_count()

    # ------------------------------------------------------------------ selection
    def _episode_items(self) -> list[QListWidgetItem]:
        return [self.list.item(i) for i in range(self.list.count())
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) is not None]

    def _toggle_item(self, item: QListWidgetItem) -> None:
        # Clicking anywhere on the row toggles it (not only the tiny checkbox).
        if item.data(Qt.ItemDataRole.UserRole) is None:
            return
        item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)

    def _set_checked(self, predicate) -> None:  # type: ignore[no-untyped-def]
        self.list.blockSignals(True)
        for item in self._episode_items():
            ep = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(Qt.CheckState.Checked if predicate(ep) else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self._update_count()

    def _select_missing(self) -> None:
        self._set_checked(lambda ep: ep.number not in self.have)

    def _update_follow_button(self) -> None:
        following = bool(self.anime) and self.ctx.library.is_following(self.anime.site, self.anime.session)
        self.follow_btn.setChecked(following)
        self.follow_btn.setText("★ Following" if following else "☆ Follow")
        self.follow_btn.setToolTip("Stop following this show" if following
                                   else "Tell me when new episodes of this show come out")
        self.follow_btn.setEnabled(bool(self.episodes))

    def _toggle_follow(self) -> None:
        if not self.anime:
            return
        library = self.ctx.library
        if library.is_following(self.anime.site, self.anime.session):
            library.unfollow(self.anime.site, self.anime.session)
        else:
            library.follow(self.anime.site, self.anime.session, self.anime.title, self.anime.poster,
                           [e.number for e in self.episodes])
            self.ctx.notify(f"Following {self.anime.title}. New episodes will show up in the Watchlist.")
        self._update_follow_button()
        self.ctx.update_watchlist_badge()

    def _toggle_all(self, checked: bool) -> None:
        self._set_checked(lambda _ep: checked)

    def _apply_range(self) -> None:
        try:
            wanted = set(parse_episode_selection(self.range_edit.text(), [e.number for e in self.episodes]))
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid range", str(exc))
            return
        self._set_checked(lambda ep: ep.number in wanted)

    def checked_episodes(self) -> list[Episode]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self._episode_items()
                if item.checkState() == Qt.CheckState.Checked]

    def _update_count(self, *_args) -> None:  # type: ignore[no-untyped-def]
        items = self._episode_items()
        chosen = len(self.checked_episodes())
        self.select_all.blockSignals(True)
        self.select_all.setChecked(bool(items) and chosen == len(items))
        self.select_all.blockSignals(False)
        self.count_label.setText(f"{chosen} of {len(items)} selected" if items else "")
        self.add_btn.setEnabled(chosen > 0)
        self.add_btn.setText(f"Add {chosen} to Queue" if chosen else "Add to Queue")

    def _save_prefs(self) -> None:
        self.ctx.settings.quality = self.quality.currentData()
        self.ctx.settings.audio = self.audio.currentData()
        self.ctx.settings.save()

    def _add_to_queue(self) -> None:
        if not self.anime:
            return
        chosen = self.checked_episodes()
        if not chosen:
            return
        added = self.ctx.manager.add(self.anime.title, self.anime.session, chosen, site=self.anime.site,
                                     poster=self.anime.poster)
        skipped = len(chosen) - len(added)
        message = f"Added {len(added)} episode(s) of {self.anime.title} to the queue"
        if skipped:
            message += f" ({skipped} already queued)"
        self.ctx.notify(message)
        self._set_checked(lambda _ep: False)
        self.ctx.show_queue()
