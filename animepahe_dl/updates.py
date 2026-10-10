"""Update check against the rolling ``latest`` GitHub Release.

Every push to ``main`` replaces the ``latest`` release (see ``.github/workflows/build-windows.yml``);
its notes contain the commit it was built from, and the build stamps the same commit into the exe
(``animepahe_dl/_build.py``). The app is up to date when the two match. Running from source has no
stamp, so no check is made.

While the repository is private GitHub answers 404 to anonymous requests; a read-only token
(fine-grained, "Contents: read") entered in Settings makes the check work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .http import HttpClient, HttpError

REPO = "yufis07/anime-downloader"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/tags/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/tag/latest"
CHECK_INTERVAL = 6 * 3600


def current_build() -> str:
    """Commit this exe was built from ('' when running from source)."""
    try:
        from ._build import BUILD_SHA  # type: ignore[import-not-found]
    except ImportError:
        return ""
    return str(BUILD_SHA or "")


@dataclass
class UpdateInfo:
    sha: str
    url: str = RELEASES_PAGE
    published: str = ""  # ISO date of the release
    size: int = 0  # bytes of the zip asset


@dataclass
class UpdateCheck:
    status: str  # "current" | "available" | "unavailable" | "dev"
    info: UpdateInfo | None = None
    message: str = ""


def parse_release(data: object) -> UpdateInfo | None:
    """The commit and download details of a release payload (None when it is not one of our builds)."""
    if not isinstance(data, dict):
        return None
    sha = re.search(r"\bcommit ([0-9a-f]{40})\b", str(data.get("body") or ""))
    sha = sha.group(1) if sha else str(data.get("target_commitish") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None
    assets = [a for a in data.get("assets") or [] if str(a.get("name", "")).endswith(".zip")]
    return UpdateInfo(sha=sha, url=str(data.get("html_url") or RELEASES_PAGE),
                      published=str(data.get("published_at") or "")[:10],
                      size=int(assets[0].get("size") or 0) if assets else 0)


def check_for_update(http: HttpClient, current: str, token: str = "") -> UpdateCheck:
    if not current:
        return UpdateCheck("dev", message="Running from source: no update check.")
    headers = {"Accept": "application/vnd.github+json"}
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    try:
        data = http.get_json(RELEASE_API, headers=headers, check_challenge=False)
    except HttpError as exc:
        if exc.status in (401, 403, 404):
            hint = ("The release page is not public. Add a GitHub token in Settings to check for updates."
                    if not token.strip() else "GitHub did not accept the token (it needs read access to the "
                                              "repository's contents).")
            return UpdateCheck("unavailable", message=hint)
        raise
    info = parse_release(data)
    if info is None:
        return UpdateCheck("unavailable", message="The latest release has no build information.")
    if info.sha == current:
        return UpdateCheck("current", info, "You have the latest version.")
    return UpdateCheck("available", info, "A newer version is available.")
