import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from animepahe_dl import downloader as dl_module
from animepahe_dl.animeheaven import (
    AnimeHeaven, parse_anime_id, parse_episodes, parse_search, parse_show, parse_video_urls,
)
from animepahe_dl.config import Settings
from animepahe_dl.downloader import DownloadManager, Status
from animepahe_dl.http import HttpClient

# Trimmed copies of the real animeheaven.me pages.
SEARCH_PAGE = """<div class="info3 bc1"><div class="similarimg"><div class="p1"><a href="https://animeheaven.me/anime.php?ak2gr"><img class="coverimg" src="https://animeheaven.me/image.php?z4mfi" alt="Frieren: Beyond Journey's End" loading="lazy"></a><div class="similarname c"><a href="https://animeheaven.me/anime.php?ak2gr" class="c">Frieren: Beyond Journey's End</a></div></div></div><div class="similarimg"><div class="p1"><a href="https://animeheaven.me/anime.php?hgj3i"><img class="coverimg" src="https://animeheaven.me/image.php?neiap" alt="Frieren: Beyond Journey's End Season 2" loading="lazy"></a></div></div></div>"""

SHOW_PAGE = """<div class="infodiv">
<div class="infotitle c">Frieren: Beyond Journey's End</div>
<div class="infotitlejp c">Sousou no Frieren</div>
<div class="infoyear c">Episodes: <div class="inline c2">28</div> Year: <div class="inline c2">2023-2024</div></div></div>
<div class="boldtext"> <div class="linetitle2 c2"><a class="c" id="47edc338ae59c34cc3ea427c7f6871df" href="https://animeheaven.me/gate.php"><div class="trackep0 watch bc2"><div class="trackep watchb bc"><div class="watch1 bc c">Episode</div><div class=" watch2 bc ">28</div><div class="watch1 bc c">266 d ago</div></div></div></a><a class="c" id="cd9a4996ea3e27887d22a26e6ce3113f" href="https://animeheaven.me/gate.php"><div class="trackep0 watch bc2"><div class="trackep watchb bc"><div class="watch1 bc c">Episode</div><div class=" watch2 bc ">1</div><div class="watch1 bc c">266 d ago</div></div></div></a><a class="c" id="b9e57993a80d8ed82019db23e8e7764c" href="https://animeheaven.me/gate.php"><div class="trackep0 watch bc2"><div class="trackep watchb bc"><div class="watch1 bc c">Episode</div><div class=" watch2 bc ">2</div></div></div></a></div></div>"""

GATE_PAGE = """<video id="vid" controls><source src='https://cdn.example.net/video.mp4?abc&amp;s=1' type='video/mp4'></video>
<a href="https://cdn.example.net/video.mp4?abc&amp;s=1&amp;d">Download</a>"""


def test_parse_search():
    results = parse_search(SEARCH_PAGE)
    assert [r.session for r in results] == ["ak2gr", "hgj3i"]
    assert results[0].title == "Frieren: Beyond Journey's End"
    assert results[0].poster == "https://animeheaven.me/image.php?z4mfi"
    assert results[0].site == "animeheaven"


def test_parse_show_and_episodes():
    info = parse_show(SHOW_PAGE)
    assert info.title == "Frieren: Beyond Journey's End"
    assert info.japanese_title == "Sousou no Frieren"
    assert info.episodes == 28
    episodes = parse_episodes(SHOW_PAGE)
    assert [e.number for e in episodes] == [1, 2, 28]
    assert episodes[0].session == "cd9a4996ea3e27887d22a26e6ce3113f"


def test_parse_video_urls_and_anime_id():
    assert parse_video_urls(GATE_PAGE) == ["https://cdn.example.net/video.mp4?abc&s=1",
                                           "https://cdn.example.net/video.mp4?abc&s=1&d"]
    assert parse_video_urls("no video here") == []
    assert parse_anime_id("https://animeheaven.me/anime.php?ak2gr") == "ak2gr"
    assert parse_anime_id("frieren") is None


VIDEO = os.urandom(300_000)
EP1 = "cd9a4996ea3e27887d22a26e6ce3113f"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, status=200, ctype="text/html", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        host = f"http://127.0.0.1:{self.server.server_port}"
        if self.path.startswith("/search.php"):
            self._send(SEARCH_PAGE.replace("https://animeheaven.me", host).encode())
        elif self.path.startswith("/anime.php"):
            self._send(SHOW_PAGE.replace("https://animeheaven.me", host).encode())
        elif self.path.startswith("/gate.php"):
            if f"key={EP1}" not in (self.headers.get("Cookie") or ""):
                return self._send(b"<div>404</div>", 404)
            self._send(f"<source src='{host}/files/ep1.mp4' type='video/mp4'>".encode())
        elif self.path.startswith("/files/ep1.mp4"):
            rng = self.headers.get("Range")
            if rng:
                start = int(rng.split("=")[1].split("-")[0])
                body = VIDEO[start:]
                self._send(body, 206, "video/mp4", {"Content-Range": f"bytes {start}-{len(VIDEO) - 1}/{len(VIDEO)}"})
            else:
                self._send(VIDEO, 200, "video/mp4")
        else:
            self._send(b"nope", 404)


@pytest.fixture()
def heaven_site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_search_episodes_and_video_url(heaven_site):
    heaven = AnimeHeaven(HttpClient(retries=1), heaven_site)
    assert heaven.search("frieren")[0].session == "ak2gr"
    episodes = heaven.episodes("ak2gr")
    assert [e.number for e in episodes] == [1, 2, 28]
    assert heaven.japanese_title("ak2gr") == "Sousou no Frieren"
    assert heaven.video_url(EP1).endswith("/files/ep1.mp4")


def test_download_resumes_and_renames_to_romaji(heaven_site, tmp_path, monkeypatch):
    monkeypatch.setattr(dl_module, "find_ffmpeg", lambda _p="": None)
    heaven = AnimeHeaven(HttpClient(retries=1), heaven_site)
    settings = Settings(download_dir=str(tmp_path), rename_japanese=True, max_parallel_episodes=1)
    # A half-finished download from an earlier run is resumed, not restarted.
    part = tmp_path / ".parts" / f"ah-ak2gr-{EP1[:12]}" / "video.mp4.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(VIDEO[:100_000])

    manager = DownloadManager(None, settings, animeheaven=heaven)
    episodes = [e for e in heaven.episodes("ak2gr") if e.session == EP1]
    manager.add("Frieren: Beyond Journey's End", "ak2gr", episodes, site="animeheaven")
    manager.wait_all(poll=0.1)
    task = manager.snapshot()[0]
    assert task.status == Status.DONE, task.message
    expected = tmp_path / "Sousou no Frieren" / "Sousou no Frieren - Episode 01.mp4"
    assert task.output_path == str(expected)
    assert expected.read_bytes() == VIDEO
    assert not (tmp_path / "Frieren Beyond Journey's End").exists()
    assert not (tmp_path / ".parts").exists()

    again = manager.add("Frieren: Beyond Journey's End", "ak2gr", episodes, site="animeheaven")
    manager.wait_all(poll=0.1)
    assert again[0].status == Status.SKIPPED
    manager.shutdown()
