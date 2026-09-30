"""Minimal HLS (m3u8) downloader with AES-128 decryption, parallel segments and resume."""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .http import HttpClient, HttpError


class Cancelled(Exception):
    pass


@dataclass
class Key:
    method: str
    uri: str | None
    iv: bytes | None


@dataclass
class Segment:
    index: int
    url: str
    duration: float
    sequence: int
    key: Key | None = None


@dataclass
class Variant:
    url: str
    bandwidth: int = 0
    resolution: str = ""


@dataclass
class Playlist:
    segments: list[Segment] = field(default_factory=list)
    variants: list[Variant] = field(default_factory=list)

    @property
    def is_master(self) -> bool:
        return bool(self.variants) and not self.segments


def _attrs(text: str) -> dict[str, str]:
    return {
        m.group(1).upper(): m.group(2).strip('"')
        for m in re.finditer(r'([A-Za-z0-9-]+)=("[^"]*"|[^,]*)', text)
    }


def parse_playlist(text: str, base_url: str) -> Playlist:
    if not text.lstrip().startswith("#EXTM3U"):
        raise HttpError("Not an HLS playlist")
    playlist = Playlist()
    sequence = 0
    key: Key | None = None
    duration = 0.0
    pending_variant: dict[str, str] | None = None
    index = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            sequence = int(line.split(":", 1)[1] or 0)
        elif line.startswith("#EXT-X-KEY:"):
            attrs = _attrs(line.split(":", 1)[1])
            method = attrs.get("METHOD", "NONE").upper()
            if method == "NONE":
                key = None
            else:
                iv_hex = attrs.get("IV")
                iv = bytes.fromhex(iv_hex[2:] if iv_hex.lower().startswith("0x") else iv_hex) if iv_hex else None
                uri = attrs.get("URI")
                key = Key(method, urljoin(base_url, uri) if uri else None, iv)
        elif line.startswith("#EXTINF:"):
            try:
                duration = float(line.split(":", 1)[1].split(",")[0])
            except ValueError:
                duration = 0.0
        elif line.startswith("#EXT-X-STREAM-INF:"):
            pending_variant = _attrs(line.split(":", 1)[1])
        elif line.startswith("#"):
            continue
        elif pending_variant is not None:
            playlist.variants.append(
                Variant(
                    url=urljoin(base_url, line),
                    bandwidth=int(pending_variant.get("BANDWIDTH", "0") or 0),
                    resolution=pending_variant.get("RESOLUTION", ""),
                )
            )
            pending_variant = None
        else:
            playlist.segments.append(
                Segment(index=index, url=urljoin(base_url, line), duration=duration,
                        sequence=sequence + index, key=key)
            )
            index += 1
            duration = 0.0
    return playlist


def load_media_playlist(http: HttpClient, url: str, referer: str) -> list[Segment]:
    for _ in range(3):
        playlist = parse_playlist(http.get_text(url, referer=referer, check_challenge=False), url)
        if not playlist.is_master:
            if not playlist.segments:
                raise HttpError("The playlist contains no segments")
            return playlist.segments
        url = max(playlist.variants, key=lambda v: v.bandwidth).url
    raise HttpError("Too many nested master playlists")


ProgressCallback = Callable[[int, int, int], None]  # done_segments, total_segments, bytes_added


class HlsDownloader:
    def __init__(
        self,
        http: HttpClient,
        segments: list[Segment],
        referer: str,
        work_dir: Path,
        workers: int = 8,
        cancel_event: threading.Event | None = None,
        progress: ProgressCallback | None = None,
        pause_gate: threading.Event | None = None,
    ) -> None:
        self.http = http
        self.segments = segments
        self.referer = referer
        self.work_dir = Path(work_dir)
        self.workers = max(1, workers)
        self.cancel_event = cancel_event or threading.Event()
        self._stop = threading.Event()  # set when a segment fails for good
        self.pause_gate = pause_gate  # set = running, cleared = paused
        self.progress = progress
        self._keys: dict[str, bytes] = {}
        self._key_lock = threading.Lock()
        self._progress_lock = threading.Lock()
        self._done = 0

    def _segment_path(self, segment: Segment) -> Path:
        return self.work_dir / f"{segment.index:06d}.ts"

    def _key_bytes(self, uri: str) -> bytes:
        with self._key_lock:
            if uri not in self._keys:
                data = self.http.get_bytes(uri, referer=self.referer, check_challenge=False)
                if len(data) != 16:
                    raise HttpError(f"Unexpected AES key length {len(data)}")
                self._keys[uri] = data
            return self._keys[uri]

    def _decrypt(self, segment: Segment, data: bytes) -> bytes:
        key = segment.key
        if key is None:
            return data
        if key.method != "AES-128" or not key.uri:
            raise HttpError(f"Unsupported HLS encryption: {key.method}")
        iv = key.iv or segment.sequence.to_bytes(16, "big")
        decryptor = Cipher(algorithms.AES(self._key_bytes(key.uri)), modes.CBC(iv)).decryptor()
        plain = decryptor.update(data) + decryptor.finalize()
        try:
            unpadder = padding.PKCS7(128).unpadder()
            return unpadder.update(plain) + unpadder.finalize()
        except ValueError:
            return plain

    def _report(self, added: int) -> None:
        with self._progress_lock:
            self._done += 1
            done = self._done
        if self.progress:
            self.progress(done, len(self.segments), added)

    def _wait_if_paused(self) -> None:
        if self.pause_gate is None:
            return
        while not self.pause_gate.wait(0.25):
            if self.cancel_event.is_set() or self._stop.is_set():
                raise Cancelled()

    def _fetch(self, segment: Segment) -> None:
        target = self._segment_path(segment)
        if target.exists():
            return
        self._wait_if_paused()
        for attempt in range(5):
            if self.cancel_event.is_set() or self._stop.is_set():
                raise Cancelled()
            try:
                data = self.http.get_bytes(segment.url, referer=self.referer, timeout=60, retries=2,
                                           check_challenge=False)
                data = self._decrypt(segment, data)
                break
            except HttpError:
                if attempt == 4:
                    raise
                time.sleep(1.5 * (attempt + 1))
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        self._report(len(data))

    def download(self, output: Path) -> Path:
        """Download every segment (resuming finished ones) and concatenate into ``output``."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        pending = [s for s in self.segments if not self._segment_path(s).exists()]
        self._done = len(self.segments) - len(pending)
        if self.progress:
            self.progress(self._done, len(self.segments), 0)
        if pending:
            pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="hls")
            try:
                futures = [pool.submit(self._fetch, s) for s in pending]
                done, _ = wait(futures, return_when=FIRST_EXCEPTION)
                errors = [f.exception() for f in done if f.exception() is not None]
                if errors:
                    self._stop.set()
                    real = [e for e in errors if not isinstance(e, Cancelled)]
                    raise (real or errors)[0]
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        if self.cancel_event.is_set():
            raise Cancelled()
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_name(output.name + ".part")
        with open(tmp, "wb") as out:
            for segment in self.segments:
                with open(self._segment_path(segment), "rb") as src:
                    shutil.copyfileobj(src, out, 1024 * 1024)
        os.replace(tmp, output)
        return output
