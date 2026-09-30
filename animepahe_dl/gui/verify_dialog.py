"""Cloudflare / DDoS-Guard verification.

Opens the site in an embedded Chromium (Qt WebEngine). Once the challenge is
passed, the site's cookies (``cf_clearance`` etc.) and the browser's
User-Agent are handed to the HTTP client, which then works like that browser.
If WebEngine is not available, the user can paste the cookie manually.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    HAS_WEBENGINE = True
except ImportError:  # pragma: no cover
    HAS_WEBENGINE = False

try:  # Qt 6.9+: the recommended way to configure a profile's storage before it is created
    from PySide6.QtWebEngineCore import QWebEngineProfileBuilder
except ImportError:  # pragma: no cover - Qt 6.7/6.8
    QWebEngineProfileBuilder = None

from ..config import app_data_dir

_CHALLENGE_TITLES = ("just a moment", "attention required", "ddos-guard", "checking your browser",
                     "please wait", "verify you are human")
_profile = None


def _shared_profile():  # type: ignore[no-untyped-def]
    """One persistent browser profile for the whole app (keeps cookies between runs)."""
    global _profile
    if _profile is None:
        from PySide6.QtWidgets import QApplication

        storage = app_data_dir() / "browser"
        cookies = QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        if QWebEngineProfileBuilder is not None:
            builder = QWebEngineProfileBuilder()
            builder.setPersistentStoragePath(str(storage))
            builder.setCachePath(str(storage / "cache"))
            builder.setPersistentCookiesPolicy(cookies)
            _profile = builder.createProfile("AnimePaheDL", QApplication.instance())
        else:  # older Qt: configure after construction
            _profile = QWebEngineProfile("AnimePaheDL", QApplication.instance())
            _profile.setPersistentStoragePath(str(storage))
            _profile.setCachePath(str(storage / "cache"))
            _profile.setPersistentCookiesPolicy(cookies)
        # Keep the engine's genuine User-Agent. Changing only the UA string makes it disagree with the
        # browser's other signals (client hints, JS APIs), which Cloudflare answers with endless re-checks.
    return _profile


class VerifyDialog(QDialog):
    def __init__(self, base_url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Verify you are human")
        self.resize(1000, 720)
        self.base_url = base_url
        self.host = (urlsplit(base_url).hostname or "").lower()
        self.cookies: dict[str, str] = {}
        self.user_agent = ""
        self._verified = False
        self.reset_requested = False  # tells the caller to drop previously saved cookies
        self._challenge_loads = 0
        self._challenge_since: float | None = None
        self._loaded_ok = False  # a page finished loading (not just a title placeholder)

        layout = QVBoxLayout(self)
        self.info = QLabel(
            "AnimePahe is protected by Cloudflare. Complete the check below if one appears. "
            "This window closes by itself once the site loads."
        )
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        if HAS_WEBENGINE:
            self._build_browser(layout)
        else:
            self._build_manual(layout)

    # ------------------------------------------------------------------ browser mode
    def _build_browser(self, layout: QVBoxLayout) -> None:
        profile = _shared_profile()
        self.user_agent = profile.httpUserAgent()
        self.view = QWebEngineView(self)
        self.page = QWebEnginePage(profile, self.view)
        self.view.setPage(self.page)
        layout.addWidget(self.view, 1)

        self._store = profile.cookieStore()
        self._store.cookieAdded.connect(self._on_cookie)
        self._store.loadAllCookies()
        self.page.loadStarted.connect(self._on_load_started)
        self.page.loadFinished.connect(self._on_loaded)
        self.page.titleChanged.connect(lambda _t: self._check_title())

        self.loop_hint = QLabel(
            "The check keeps repeating. Try these in order: 1) click Reset browser data, "
            "2) turn off any VPN or proxy and click Reload, 3) click Enter cookie manually and copy the "
            "cookie from Chrome or Edge. If the check loops in your normal browser too, the site itself "
            "is under heavy protection right now. Wait a while and try again."
        )
        self.loop_hint.setWordWrap(True)
        self.loop_hint.setStyleSheet("background: rgba(245,158,11,0.15); border: 1px solid #f59e0b; "
                                     "border-radius: 8px; padding: 8px;")
        self.loop_hint.hide()
        layout.addWidget(self.loop_hint)

        buttons = QHBoxLayout()
        self.status = QLabel("Loading…")
        manual = QPushButton("Enter cookie manually…")
        manual.clicked.connect(self._manual_popup)
        reset_btn = QPushButton("Reset browser data")
        reset_btn.setToolTip("Delete this window's cookies and cache, then reload (fixes most check loops)")
        reset_btn.clicked.connect(self._reset_browser)
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self.view.reload)
        self._loop_timer = QTimer(self)
        self._loop_timer.timeout.connect(self._check_loop)
        self._loop_timer.start(3000)
        self.done_btn = QPushButton("Done")
        self.done_btn.setObjectName("primary")
        self.done_btn.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.status, 1)
        for button in (manual, reset_btn, reload_btn, cancel, self.done_btn):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.view.load(QUrl(self.base_url))

    def _on_cookie(self, cookie) -> None:  # type: ignore[no-untyped-def]
        domain_s = str(cookie.domain()).lstrip(".").lower()
        if domain_s and (self.host == domain_s or self.host.endswith("." + domain_s)):
            name = bytes(cookie.name()).decode(errors="ignore")
            value = bytes(cookie.value()).decode(errors="ignore")
            self.cookies[name] = value
            if name == "cf_clearance":
                self._check_title()

    def _on_load_started(self) -> None:
        self._loaded_ok = False

    def _on_loaded(self, ok: bool) -> None:
        self._loaded_ok = ok
        # Cloudflare serves its challenge with an error status, which the engine reports as a failed
        # load. Treat it as a challenge, not as a network failure.
        if self._is_challenge():
            self._challenge_loads += 1
            self._check_title()
            self._check_loop()
            return
        if not ok:
            self.status.setText("Page failed to load. The site may be down or blocked on your network.")
            return
        self._check_title()

    def _is_challenge(self) -> bool:
        title = (self.page.title() or "").lower()
        return any(marker in title for marker in _CHALLENGE_TITLES)

    def _check_loop(self) -> None:
        if self._verified:
            self._loop_timer.stop()
            return
        if self._is_challenge():
            if self._challenge_since is None:
                self._challenge_since = time.monotonic()
            stuck = time.monotonic() - self._challenge_since > 45
            if self._challenge_loads >= 3 or stuck:
                self.loop_hint.show()
                self.status.setText("The check is looping.")
        else:
            self._challenge_since = None

    def _reset_browser(self) -> None:
        profile = self.page.profile()
        profile.cookieStore().deleteAllCookies()
        profile.clearHttpCache()
        self.cookies.clear()
        self.reset_requested = True
        self._challenge_loads = 0
        self._challenge_since = None
        self.loop_hint.hide()
        self.status.setText("Browser data cleared. Loading…")
        QTimer.singleShot(500, lambda: self.view.load(QUrl(self.base_url)))

    def _has_real_title(self) -> bool:
        """While loading, the engine uses the address as a placeholder title; that is not the site."""
        title = (self.page.title() or "").strip().lower()
        if not title:
            return False
        url_like = " " not in title and ("/" in title or self.host in title or title.startswith("http"))
        return not url_like

    def _site_loaded(self) -> bool:
        url = self.page.url().toString()
        return (bool(url) and url != "about:blank" and self._loaded_ok
                and self._has_real_title() and not self._is_challenge())

    def _check_title(self) -> None:
        if self._verified:
            return
        if self._is_challenge():
            self.status.setText("Waiting for the check to finish…")
            return
        if self._site_loaded():
            self._verified = True
            self.status.setText("✔ Verified. Closing…")
            QTimer.singleShot(1200, self._confirm_and_accept)

    def _confirm_and_accept(self) -> None:
        # The challenge can redirect back to itself; only close if the real site is still showing.
        if self._site_loaded():
            self.accept()
        else:
            self._verified = False
            self.status.setText("Waiting for the check to finish…")

    # ------------------------------------------------------------------ manual mode
    def _build_manual(self, layout: QVBoxLayout) -> None:
        self.info.setText(
            "The built-in browser is not available. Open the site in Chrome or Edge, pass the check, "
            "then press F12 → Application → Cookies and copy the value of 'cf_clearance'. "
            "Also copy your browser's User-Agent (type 'navigator.userAgent' in the Console)."
        )
        form = QFormLayout()
        self.cookie_edit = QLineEdit()
        self.ua_edit = QLineEdit()
        form.addRow("cf_clearance", self.cookie_edit)
        form.addRow("User-Agent", self.ua_edit)
        layout.addLayout(form)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._accept_manual)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _accept_manual(self) -> None:
        if self.cookie_edit.text().strip():
            self.cookies["cf_clearance"] = self.cookie_edit.text().strip()
        self.user_agent = self.ua_edit.text().strip() or self.user_agent
        self.accept()

    def _manual_popup(self) -> None:
        dialog = ManualCookieDialog(self.user_agent, self)
        if dialog.exec():
            self.cookies.update(dialog.cookies)
            self.user_agent = dialog.user_agent or self.user_agent
            self.accept()

    def done(self, result: int) -> None:  # noqa: D401 - Qt override
        if HAS_WEBENGINE and hasattr(self, "view"):
            self.view.stop()
            self._loop_timer.stop()
            try:
                self._store.cookieAdded.disconnect(self._on_cookie)
            except (RuntimeError, TypeError):
                pass
        super().done(result)


class ManualCookieDialog(QDialog):
    def __init__(self, user_agent: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Enter Cloudflare cookie")
        self.cookies: dict[str, str] = {}
        self.user_agent = user_agent
        layout = QVBoxLayout(self)
        label = QLabel(
            "Open the site in your normal browser and pass the check. Then press F12 → Application → "
            "Cookies, copy 'cf_clearance', and copy the User-Agent (Console: navigator.userAgent). "
            "Both must come from the same browser."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        self.cookie_edit = QLineEdit()
        self.ua_edit = QLineEdit(user_agent)
        form.addRow("cf_clearance", self.cookie_edit)
        form.addRow("User-Agent", self.ua_edit)
        layout.addLayout(form)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(640, 200)

    def _ok(self) -> None:
        value = self.cookie_edit.text().strip()
        if value.lower().startswith("cf_clearance="):
            value = value.split("=", 1)[1]
        if value:
            self.cookies["cf_clearance"] = value
        self.user_agent = self.ua_edit.text().strip()
        self.accept()
