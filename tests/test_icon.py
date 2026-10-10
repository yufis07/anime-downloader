import importlib.util
import struct
from pathlib import Path

from animepahe_dl.config import Settings

SPEC = importlib.util.spec_from_file_location("make_icon", Path(__file__).resolve().parents[1] / "tools" / "make_icon.py")
make_icon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make_icon)


def test_build_ico_layout():
    png = b"\x89PNG-fake"
    data = make_icon.build_ico([(16, png), (256, png + b"!")])
    assert struct.unpack_from("<HHH", data, 0) == (0, 1, 2)
    first = struct.unpack_from("<BBBBHHII", data, 6)
    second = struct.unpack_from("<BBBBHHII", data, 22)
    assert first[0] == 16 and second[0] == 0  # 256 is stored as 0
    assert first[6] == len(png) and second[6] == len(png) + 1
    assert data[first[7]:first[7] + first[6]] == png and data[second[7]:] == png + b"!"


def test_committed_ico_has_all_sizes():
    data = (Path(__file__).resolve().parents[1] / "assets" / "AnimePaheDL.ico").read_bytes()
    count = struct.unpack_from("<HHH", data, 0)[2]
    sizes = [data[6 + 16 * i] or 256 for i in range(count)]
    assert sizes == list(make_icon.SIZES)
    assert all(data[struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)[7]:][:4] == b"\x89PNG" for i in range(count))


def test_icon_style_setting_is_validated():
    s = Settings(icon_style="neon")
    s.normalize()
    assert s.icon_style == "blade"
    s = Settings(icon_style="classic")
    s.normalize()
    assert s.icon_style == "classic"
