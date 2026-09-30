"""Full pipeline against a local fake AnimePahe + kwik + CDN server (no internet needed)."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from animepahe_dl import downloader as dl_module
from animepahe_dl.animepahe import AnimePahe
from animepahe_dl.config import Settings
from animepahe_dl.downloader import DownloadManager, Status
from animepahe_dl.http import CloudflareChallenge, HttpClient
from packer import pack

ANIME = "0a1b2c3d-1111-2222-3333-444455556666"
KEY = bytes(range(16))
SEGMENTS = [os.urandom(1000 + i * 37) for i in range(12)]


def encrypt(data: bytes, sequence: int) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    enc = Cipher(algorithms.AES(KEY), modes.CBC(sequence.to_bytes(16, "big"))).encryptor()
    return enc.update(padded) + enc.finalize()


class FakeSite(BaseHTTPRequestHandler):
    require_clearance = False

    def log_message(self, *args):  # silence
        pass

    def _send(self, body, status=200, ctype="text/html"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        host = f"http://{self.headers['Host']}"
        path = self.path
        if path.startswith("/api") and self.require_clearance and "cf_clearance=ok" not in (self.headers.get("Cookie") or ""):
            return self._send("<title>Just a moment...</title>", 403)
        if path.startswith("/api?m=search"):
            return self._send(json.dumps({"data": [{"session": ANIME, "title": "Test &amp; Anime", "type": "TV",
                                                     "episodes": 3, "year": 2024, "score": 8.5, "poster": ""}]}),
                              ctype="application/json")
        if path.startswith("/api?m=release"):
            page = int(path.rsplit("page=", 1)[1])
            items = [{"session": f"ep{n}session", "episode": n, "title": "", "duration": "00:24:00",
                      "created_at": "2024-01-01 00:00:00"} for n in ([1, 2] if page == 1 else [3])]
            return self._send(json.dumps({"last_page": 2, "current_page": page, "data": items}),
                              ctype="application/json")
        if path == f"/anime/{ANIME}":
            return self._send("<html><title>Test Anime :: animepahe</title><h1><span>Test Anime</span></h1></html>")
        if path.startswith(f"/play/{ANIME}/"):
            assert self.headers.get("Referer", "").startswith(host)
            return self._send(
                f'<button data-src="{host}/kwik/e/low" data-resolution="360" data-audio="jpn" data-av1="0">x</button>'
                f'<button data-src="{host}/kwik/e/high" data-resolution="720" data-audio="jpn" data-av1="0">x</button>')
        if path == "/kwik/e/high":
            js = f"const source='{host}/cdn/uwu.m3u8';const player=new Plyr(document.querySelector('video'));"
            return self._send(f"<html><script>{pack(js)}</script></html>")
        if path.startswith("/cdn/"):
            assert self.headers.get("Referer") == f"{host}/", "CDN must receive the kwik origin as Referer"
        if path == "/cdn/uwu.m3u8":
            lines = ["#EXTM3U", "#EXT-X-MEDIA-SEQUENCE:0", '#EXT-X-KEY:METHOD=AES-128,URI="mon.key"']
            for i in range(len(SEGMENTS)):
                lines += ["#EXTINF:5.0,", f"seg-{i}-v1-a1.jpg"]
            lines.append("#EXT-X-ENDLIST")
            return self._send("\n".join(lines), ctype="application/vnd.apple.mpegurl")
        if path == "/cdn/mon.key":
            return self._send(KEY, ctype="application/octet-stream")
        if path.startswith("/cdn/seg-"):
            index = int(path.split("-")[1])
            return self._send(encrypt(SEGMENTS[index], index), ctype="image/jpeg")
        return self._send("not found", 404)


@pytest.fixture()
def site(monkeypatch):
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSite)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    FakeSite.require_clearance = False
    server.shutdown()


@pytest.mark.parametrize("backend", ["curl_cffi", "requests"])
def test_search_episodes_and_download(site, tmp_path, monkeypatch, backend):
    monkeypatch.setattr(dl_module, "find_ffmpeg", lambda _p="": None)
    http = HttpClient(backend=backend, retries=1)
    api = AnimePahe(http, site)

    results = api.search("test")
    assert results[0].title == "Test & Anime" and results[0].session == ANIME
    assert api.anime_title(ANIME) == "Test Anime"
    episodes = api.episodes(ANIME)
    assert [e.number for e in episodes] == [1, 2, 3]

    settings = Settings(base_url=site, download_dir=str(tmp_path), quality=1080, max_parallel_episodes=2,
                        segment_workers=4)
    manager = DownloadManager(api, settings)
    manager.add("Test: Anime", ANIME, episodes[:2])
    manager.wait_all(poll=0.1)
    tasks = manager.snapshot()
    assert [t.status for t in tasks] == [Status.DONE, Status.DONE], [t.message for t in tasks]
    for task in tasks:
        assert task.source_label.startswith("720p")
        with open(task.output_path, "rb") as fh:
            assert fh.read() == b"".join(SEGMENTS)
    assert tasks[0].output_path.endswith(os.path.join("Test Anime", "Test Anime - Episode 01.ts"))
    assert not (tmp_path / ".parts").exists()

    # A second request for the same episode is skipped because the file exists.
    again = manager.add("Test: Anime", ANIME, episodes[:1])
    manager.wait_all(poll=0.1)
    assert again[0].status == Status.SKIPPED
    manager.shutdown()


def test_cloudflare_challenge_detected_and_cleared(site):
    FakeSite.require_clearance = True
    http = HttpClient(retries=0)
    api = AnimePahe(http, site)
    with pytest.raises(CloudflareChallenge):
        api.search("test")
    http.set_identity("Mozilla/5.0 Test", {"cf_clearance": "ok"})
    assert api.search("test")[0].session == ANIME


def test_cancel(site, tmp_path, monkeypatch):
    monkeypatch.setattr(dl_module, "find_ffmpeg", lambda _p="": None)
    api = AnimePahe(HttpClient(retries=0), site)
    settings = Settings(base_url=site, download_dir=str(tmp_path), max_parallel_episodes=1)
    manager = DownloadManager(api, settings)
    ep = api.episodes(ANIME)
    tasks = manager.add("X", ANIME, ep)
    manager.cancel(tasks[-1].id)  # still queued -> cancelled immediately
    manager.wait_all(poll=0.1)
    assert tasks[-1].status == Status.CANCELLED
    assert tasks[0].status == Status.DONE
    manager.shutdown()


def test_segment_failure_is_reported_as_failure(site, tmp_path, monkeypatch):
    """A broken segment must show 'Failed' with a reason, not 'Cancelled'."""
    monkeypatch.setattr(dl_module, "find_ffmpeg", lambda _p="": None)
    import animepahe_dl.hls as hls

    monkeypatch.setattr(hls.time, "sleep", lambda _s: None)
    original = FakeSite.do_GET

    def broken(self):
        if self.path.startswith("/cdn/seg-3"):
            return self._send("gone", 404)
        return original(self)

    monkeypatch.setattr(FakeSite, "do_GET", broken)
    api = AnimePahe(HttpClient(retries=0), site)
    manager = DownloadManager(api, Settings(base_url=site, download_dir=str(tmp_path)))
    task = manager.add("X", ANIME, api.episodes(ANIME)[:1])[0]
    manager.wait_all(poll=0.1)
    assert task.status == Status.FAILED
    assert "404" in task.message
    manager.shutdown()


def test_pause_and_resume(site, tmp_path, monkeypatch):
    monkeypatch.setattr(dl_module, "find_ffmpeg", lambda _p="": None)
    api = AnimePahe(HttpClient(retries=0), site)
    manager = DownloadManager(api, Settings(base_url=site, download_dir=str(tmp_path)))
    manager.pause_all()
    assert manager.paused
    tasks = manager.add("X", ANIME, api.episodes(ANIME)[:2])
    import time

    time.sleep(1.0)
    assert all(t.status == Status.QUEUED for t in tasks), "nothing may start while paused"
    manager.resume_all()
    manager.wait_all(poll=0.1)
    assert [t.status for t in tasks] == [Status.DONE, Status.DONE]
    assert tasks[0].speed == 0.0  # idle tasks report no speed
    manager.shutdown()


def test_pause_holds_segment_workers(tmp_path):
    """A paused HlsDownloader must not fetch; cancelling while paused ends it."""
    import threading

    from animepahe_dl.hls import Cancelled, HlsDownloader, Segment

    class NoNetwork:
        def get_bytes(self, *a, **k):
            raise AssertionError("must not fetch while paused")

    gate, cancel = threading.Event(), threading.Event()
    segs = [Segment(index=i, url=f"http://x/{i}", duration=1, sequence=i) for i in range(3)]
    dl = HlsDownloader(NoNetwork(), segs, "r", tmp_path / "w", workers=2, cancel_event=cancel, pause_gate=gate)
    threading.Timer(0.6, cancel.set).start()
    with pytest.raises(Cancelled):
        dl.download(tmp_path / "out.ts")
