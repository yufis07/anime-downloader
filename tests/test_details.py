from animepahe_dl.details import DetailsClient, clean_synopsis, parse_media

FRIEREN = {
    "siteUrl": "https://anilist.co/anime/154587", "format": "TV", "status": "FINISHED", "seasonYear": 2023,
    "episodes": 28, "averageScore": 91, "genres": ["Adventure", "Drama", "Fantasy"],
    "description": "The adventure is over.<br><br>But life goes on.<br>She &quot;learns&quot; <i>again</i>.",
    "bannerImage": "https://s4.anilist.co/banner.jpg",
    "coverImage": {"extraLarge": "https://s4.anilist.co/xl.jpg", "large": "https://s4.anilist.co/l.jpg"},
    "studios": {"nodes": [{"name": "MADHOUSE"}]},
    "title": {"romaji": "Sousou no Frieren", "english": "Frieren: Beyond Journey's End"},
    "synonyms": ["Frieren at the Funeral"],
}
OTHER = {"title": {"romaji": "Totally Different", "english": None}, "synonyms": [], "genres": []}


class Http:
    def __init__(self, media):
        self.media, self.calls = media, 0

    def post_json(self, url, payload, **kwargs):
        self.calls += 1
        return {"data": {"Page": {"media": self.media}}}


def test_clean_synopsis():
    assert clean_synopsis(FRIEREN["description"]) == 'The adventure is over.\n\nBut life goes on.\nShe "learns" again.'
    assert clean_synopsis(None) == ""


def test_parse_media():
    _, d = parse_media(FRIEREN)
    assert (d.romaji, d.english, d.score, d.year, d.episodes) == (
        "Sousou no Frieren", "Frieren: Beyond Journey's End", 9.1, 2023, 28)
    assert (d.status, d.format, d.studio) == ("Finished", "TV", "MADHOUSE")
    assert d.banner_url.endswith("banner.jpg") and d.cover_url.endswith("xl.jpg")
    assert d.facts == ["★ 9.1", "TV", "2023", "28 episodes", "Finished", "MADHOUSE"]


def test_parse_media_with_missing_fields():
    _, d = parse_media(OTHER)
    assert d.romaji == "Totally Different" and d.english == "" and d.score is None and d.facts == []


def test_fetch_picks_the_matching_show_and_caches():
    http = Http([OTHER, FRIEREN])
    client = DetailsClient(http)
    d = client.fetch("Frieren: Beyond Journey's End")
    assert d.romaji == "Sousou no Frieren"
    assert client.fetch("frieren: beyond journey's end") is d and http.calls == 1


def test_fetch_returns_none_for_unrelated_results():
    assert DetailsClient(Http([OTHER])).fetch("Smoking Behind the Supermarket with You") is None
