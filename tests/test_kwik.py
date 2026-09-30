import shutil
import subprocess

import pytest

from animepahe_dl.kwik import _encode, extract_m3u8, unpack
from packer import pack

SOURCE = (
    "const source='https://vault-12.owocdn.top/stream/12/08/abc123/uwu.m3u8';"
    "const video=document.querySelector('video');const player=new Plyr(video,{quality:{default:1080}});"
    "let words='" + " ".join(f"w{i}x" for i in range(150)) + "';"
)


def test_encode_matches_packer_alphabet():
    assert _encode(0, 62) == "0"
    assert _encode(35, 62) == "z"
    assert _encode(36, 62) == "A"
    assert _encode(61, 62) == "Z"
    assert _encode(62, 62) == "10"


def test_unpack_roundtrip():
    assert unpack(pack(SOURCE)) == SOURCE


def test_extract_from_kwik_page():
    page = f"<html><body><video></video><script>{pack(SOURCE)}</script></body></html>"
    assert extract_m3u8(page) == "https://vault-12.owocdn.top/stream/12/08/abc123/uwu.m3u8"


def test_extract_plain_source():
    page = "<script>var x = {file:\"https:\\/\\/cdn.example\\/a\\/b.m3u8?t=1\"}</script>"
    assert extract_m3u8(page) == "https://cdn.example/a/b.m3u8?t=1"


def test_extract_none():
    assert extract_m3u8("<html>nothing here</html>") is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_python_unpack_matches_real_javascript():
    """Evaluate the packed code with node (eval -> return) and compare with our unpacker."""
    packed = pack(SOURCE)
    script = "console.log(" + packed[len("eval("):]
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert out.rstrip("\n") == unpack(packed)
