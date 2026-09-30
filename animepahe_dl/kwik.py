"""Kwik player handling: unpack Dean Edwards' p,a,c,k,e,d JavaScript and find the HLS URL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .http import HttpClient, HttpError

_PACKED_ARGS = re.compile(
    r"}\s*\(\s*'(?P<p>(?:\\.|[^'\\])*)'\s*,\s*(?P<a>\d+)\s*,\s*(?P<c>\d+)\s*,\s*"
    r"'(?P<k>(?:\\.|[^'\\])*)'\s*\.split\(\s*'\|'\s*\)",
    re.S,
)
_M3U8 = re.compile(r"https?://[^\s'\"\\<>]+?\.m3u8(?:\?[^\s'\"\\<>]*)?")
_JS_ESCAPES = re.compile(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.S)


def _js_unescape(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        esc = match.group(1)
        if esc[0] in "ux" and len(esc) > 1:
            return chr(int(esc[1:], 16))
        return {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}.get(esc, esc)

    return _JS_ESCAPES.sub(repl, value)


def _encode(num: int, radix: int) -> str:
    """Python port of the packer's ``e`` function."""
    prefix = "" if num < radix else _encode(num // radix, radix)
    num %= radix
    if num > 35:
        return prefix + chr(num + 29)
    return prefix + "0123456789abcdefghijklmnopqrstuvwxyz"[num]


def is_packed(source: str) -> bool:
    return bool(_PACKED_ARGS.search(source))


def unpack(source: str) -> str:
    """Unpack the first ``eval(function(p,a,c,k,e,d){...})`` payload found in ``source``."""
    match = _PACKED_ARGS.search(source)
    if not match:
        raise ValueError("No packed JavaScript found")
    payload = _js_unescape(match.group("p"))
    radix = int(match.group("a"))
    count = int(match.group("c"))
    keywords = _js_unescape(match.group("k")).split("|")
    table: dict[str, str] = {}
    for index in range(count - 1, -1, -1):
        word = keywords[index] if index < len(keywords) else ""
        key = _encode(index, radix)
        table[key] = word or key
    return re.sub(r"\b\w+\b", lambda m: table.get(m.group(0), m.group(0)), payload)


def extract_m3u8(page: str) -> str | None:
    """Find the HLS playlist URL inside a kwik embed page (packed or not)."""
    candidates = [page]
    for chunk in re.findall(r"eval\(function\(p,a,c,k,e,[rd]\).*?\.split\('\|'\)[^)]*\)\)", page, re.S):
        text = chunk
        for _ in range(4):  # nested packing
            try:
                text = unpack(text)
            except ValueError:
                break
            candidates.append(text)
            if not is_packed(text):
                break
    for text in reversed(candidates):
        match = re.search(r"source\s*=\s*['\"](https?://[^'\"]+)['\"]", text)
        if match and ".m3u8" in match.group(1):
            return match.group(1)
        match = _M3U8.search(text.replace("\\/", "/"))
        if match:
            return match.group(0)
    return None


@dataclass
class Stream:
    playlist_url: str
    referer: str  # CDN requires the kwik origin as Referer


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def resolve(http: HttpClient, kwik_url: str, site_referer: str) -> Stream:
    page = http.get_text(kwik_url, referer=site_referer)
    playlist = extract_m3u8(page)
    if not playlist:
        raise HttpError("Could not find the video playlist in the kwik player page.")
    return Stream(playlist_url=playlist, referer=origin(kwik_url))
