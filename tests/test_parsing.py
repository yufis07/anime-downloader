from animepahe_dl.animepahe import Source, choose_source, parse_anime_session, parse_sources
from animepahe_dl.hls import parse_playlist
from animepahe_dl.utils import format_episode, parse_episode_selection, sanitize_filename

PLAY_PAGE = """
<div id="resolutionMenu" class="dropdown-menu">
 <button data-src="https://kwik.cx/e/AAA" data-fansub="SubsPlease" data-resolution="360" data-audio="jpn" data-av1="0" class="dropdown-item">SubsPlease &middot; 360p</button>
 <button data-src="https://kwik.cx/e/BBB" data-fansub="SubsPlease" data-resolution="720" data-audio="jpn" data-av1="0" class="dropdown-item">SubsPlease &middot; 720p</button>
 <button data-src="https://kwik.cx/e/CCC" data-fansub="SubsPlease" data-resolution="1080" data-audio="jpn" data-av1="0" class="dropdown-item active">SubsPlease &middot; 1080p</button>
 <button data-src="https://kwik.cx/e/DDD" data-fansub="Yameii" data-resolution="1080" data-audio="eng" data-av1="0" class="dropdown-item">Yameii &middot; 1080p <span class="badge">eng</span></button>
 <button data-src="https://kwik.cx/e/EEE" data-fansub="SubsPlease" data-resolution="1080" data-audio="jpn" data-av1="1" class="dropdown-item">AV1</button>
</div>
<div id="pickDownload"><a href="https://pahe.win/xyz" class="dropdown-item">SubsPlease · 1080p (200MB)</a></div>
"""


def test_parse_sources():
    sources = parse_sources(PLAY_PAGE)
    assert [s.url[-3:] for s in sources] == ["AAA", "BBB", "CCC", "DDD", "EEE"]
    assert sources[3].audio == "eng" and sources[4].av1


def test_choose_source():
    sources = parse_sources(PLAY_PAGE)
    assert choose_source(sources, 1080, "jpn").url.endswith("CCC")
    assert choose_source(sources, 720, "jpn").url.endswith("BBB")
    assert choose_source(sources, 1080, "eng").url.endswith("DDD")
    assert choose_source(sources, 1080, "jpn", prefer_non_av1=False).resolution == 1080
    # Nothing at/below 240p -> lowest available
    assert choose_source(sources, 240, "jpn").resolution == 360
    # Missing dub falls back to sub
    assert choose_source([Source("k", 720, "jpn")], 1080, "eng").url == "k"
    assert choose_source([], 1080, "jpn") is None


def test_parse_anime_session():
    uuid = "0a1b2c3d-1111-2222-3333-444455556666"
    assert parse_anime_session(f"https://animepahe.pw/anime/{uuid}") == uuid
    assert parse_anime_session(f"https://animepahe.si/play/{uuid}/abcdef") == uuid
    assert parse_anime_session(uuid) == uuid
    assert parse_anime_session("naruto") is None


def test_parse_media_playlist():
    text = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA-SEQUENCE:5
#EXT-X-KEY:METHOD=AES-128,URI="mon.key"
#EXTINF:6.0,
seg-0.jpg
#EXTINF:4.5,
https://other.cdn/seg-1.jpg
#EXT-X-KEY:METHOD=AES-128,URI="https://k/2.key",IV=0x000102030405060708090a0b0c0d0e0f
#EXTINF:2,
seg-2.jpg
#EXT-X-ENDLIST
"""
    pl = parse_playlist(text, "https://cdn.test/stream/uwu.m3u8")
    assert not pl.is_master
    assert [s.url for s in pl.segments] == [
        "https://cdn.test/stream/seg-0.jpg", "https://other.cdn/seg-1.jpg", "https://cdn.test/stream/seg-2.jpg"]
    assert pl.segments[0].key.uri == "https://cdn.test/stream/mon.key"
    assert pl.segments[0].sequence == 5 and pl.segments[1].sequence == 6
    assert pl.segments[2].key.iv == bytes(range(16))
    assert pl.segments[1].duration == 4.5


def test_parse_master_playlist():
    text = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080
hi/index.m3u8
"""
    pl = parse_playlist(text, "https://cdn.test/master.m3u8")
    assert pl.is_master
    assert max(pl.variants, key=lambda v: v.bandwidth).url == "https://cdn.test/hi/index.m3u8"


def test_episode_selection():
    eps = [1, 2, 3, 4, 5, 6, 7.5, 13, 14]
    assert parse_episode_selection("", eps) == sorted(eps)
    assert parse_episode_selection("all", eps) == sorted(eps)
    assert parse_episode_selection("1-3, 5", eps) == [1, 2, 3, 5]
    assert parse_episode_selection("6-", eps) == [6, 7.5, 13, 14]
    assert parse_episode_selection("-2 14 99", eps) == [1, 2, 14]
    assert parse_episode_selection("7.5", eps) == [7.5]


def test_sanitize_and_format():
    assert sanitize_filename('Re:Zero? <Season 2> "Part" | 1.') == "Re Zero Season 2 Part 1"
    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("   ") == "untitled"
    assert format_episode(3) == "03"
    assert format_episode(12.5) == "12.5"
    assert format_episode(120) == "120"
