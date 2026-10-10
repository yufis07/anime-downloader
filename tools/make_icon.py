"""Write assets/AnimePaheDL.ico (the exe's icon) from the built-in blade icon.

    python tools/make_icon.py

Needs PySide6. The .ico holds PNG-compressed images of 16-256 px, which Windows Vista and later read.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SIZES = (16, 24, 32, 48, 64, 128, 256)


def build_ico(png_images: list[tuple[int, bytes]]) -> bytes:
    """ICO container: header, one 16-byte directory entry per image, then the PNG data."""
    header = struct.pack("<HHH", 0, 1, len(png_images))
    offset = 6 + 16 * len(png_images)
    entries, blobs = b"", b""
    for size, data in png_images:
        dim = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return header + entries + blobs


def main() -> None:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication

    from animepahe_dl.gui.theme import render_icon_pixmap

    app = QApplication([])  # noqa: F841 - Qt needs one to paint
    images = []
    for size in SIZES:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        render_icon_pixmap("blade", size).save(buffer, "PNG")
        images.append((size, bytes(buffer.data())))
    out = ROOT / "assets" / "AnimePaheDL.ico"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(build_ico(images))
    print(f"wrote {out} ({out.stat().st_size} bytes, sizes {SIZES})")


if __name__ == "__main__":
    main()
