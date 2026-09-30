"""Small helpers: Windows-safe file names, episode range parsing, formatting, ffmpeg lookup."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, max_length: int = 150) -> str:
    """Make ``name`` safe to use as a single Windows path component."""
    name = _INVALID_CHARS.sub(" ", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if not name:
        name = "untitled"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    if len(name) > max_length:
        name = name[:max_length].rstrip(". ")
    return name


def format_episode(number: float, pad: int = 2) -> str:
    """1 -> '01', 12.5 -> '12.5'."""
    if float(number).is_integer():
        return str(int(number)).zfill(pad)
    return f"{number:g}"


def parse_episode_selection(text: str, available: list[float]) -> list[float]:
    """Parse '1-12, 15, 20-' against the available episode numbers.

    Supports single numbers, closed ranges, open ranges ('20-'), 'all' and '*'.
    Returns the matching episode numbers in ascending order without duplicates.
    """
    available_sorted = sorted(set(available))
    text = (text or "").strip().lower()
    if not text or text in {"all", "*"}:
        return available_sorted
    chosen: set[float] = set()
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        match = re.fullmatch(r"(\d+(?:\.\d+)?)?\s*-\s*(\d+(?:\.\d+)?)?", part)
        if match and "-" in part:
            low = float(match.group(1)) if match.group(1) else float("-inf")
            high = float(match.group(2)) if match.group(2) else float("inf")
            chosen.update(n for n in available_sorted if low <= n <= high)
            continue
        try:
            value = float(part)
        except ValueError as exc:
            raise ValueError(f"Invalid episode selection: {part!r}") from exc
        if value in available_sorted:
            chosen.add(value)
    return sorted(chosen)


def format_bytes(size: float) -> str:
    size = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size) < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_speed(bytes_per_second: float) -> str:
    return f"{format_bytes(bytes_per_second)}/s" if bytes_per_second > 0 else ""


def find_ffmpeg(configured: str = "") -> str | None:
    """Return a usable ffmpeg executable path, or None."""
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    # Next to the frozen executable / project root (lets users drop ffmpeg.exe beside the app).
    base = Path(getattr(sys, "_MEIPASS", Path(sys.argv[0]).resolve().parent))
    candidates += [str(base / exe), str(Path(sys.executable).parent / exe)]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("ffmpeg")
    if found:
        return found
    if sys.platform == "win32":
        # winget installs Gyan.FFmpeg under LOCALAPPDATA\Microsoft\WinGet\Packages
        root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if root.is_dir():
            for path in root.glob("*FFmpeg*/**/bin/ffmpeg.exe"):
                return str(path)
    return None


def open_in_file_manager(path: str | os.PathLike) -> None:
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')  # noqa: S605
    else:
        os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')  # noqa: S605
