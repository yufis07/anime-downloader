"""One-click ffmpeg install: download the official Windows build, verify it, keep ffmpeg.exe in the data folder.

Used by the first-run wizard and Settings. ffmpeg is what turns the downloaded pieces into .mp4 files;
without it the app saves .ts files.
"""

from __future__ import annotations

import hashlib
import os
import re
import zipfile
from pathlib import Path
from typing import Callable

from .http import HttpClient, HttpError

FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


class FfmpegInstallError(Exception):
    pass


def parse_sha256(text: str) -> str:
    """The 64-hex digest in a ``.sha256`` file ("<hash>" or "<hash>  <name>")."""
    match = re.search(r"\b([0-9a-fA-F]{64})\b", text or "")
    if not match:
        raise FfmpegInstallError("The checksum file for ffmpeg is not in the expected format.")
    return match.group(1).lower()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_ffmpeg(archive: Path, target: Path) -> None:
    """Copy ``bin/ffmpeg.exe`` out of the release zip to ``target`` (atomically)."""
    try:
        with zipfile.ZipFile(archive) as zf:
            member = next((n for n in zf.namelist() if n.replace("\\", "/").lower().endswith("/bin/ffmpeg.exe")), None)
            if member is None:
                raise FfmpegInstallError("The downloaded archive does not contain bin/ffmpeg.exe.")
            tmp = target.with_suffix(".tmp")
            with zf.open(member) as src, open(tmp, "wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
            os.replace(tmp, target)
    except zipfile.BadZipFile as exc:
        raise FfmpegInstallError("The downloaded file is not a valid zip archive.") from exc


def install_ffmpeg(
    http: HttpClient,
    dest_dir: Path,
    progress: Callable[[int, int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    url: str = FFMPEG_ZIP_URL,
) -> Path:
    """Download, verify (SHA-256 published next to the archive) and unpack ffmpeg into ``dest_dir``.

    Returns the path of ``ffmpeg.exe``. A checksum mismatch deletes the download and raises."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        expected = parse_sha256(http.get_text(url + ".sha256", timeout=30))
    except HttpError as exc:
        raise FfmpegInstallError(f"Could not get the checksum for ffmpeg ({exc}).") from exc
    archive = dest_dir / "ffmpeg-download.zip"
    try:
        http.download_file(url, archive, progress=progress, should_stop=should_stop)
    except InterruptedError:
        raise FfmpegInstallError("Cancelled.") from None
    except HttpError as exc:
        raise FfmpegInstallError(f"Download failed ({exc}).") from exc
    if file_sha256(archive) != expected:
        archive.unlink(missing_ok=True)
        raise FfmpegInstallError("The downloaded ffmpeg did not match its checksum, so it was not installed. "
                                 "Try again.")
    target = dest_dir / "ffmpeg.exe"
    extract_ffmpeg(archive, target)
    archive.unlink(missing_ok=True)
    return target
