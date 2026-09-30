from animepahe_dl.mal import MalLookup, _parse_entry, best_match

FRIEREN = {
    "mal_id": 52991, "title": "Sousou no Frieren", "title_english": "Frieren: Beyond Journey's End",
    "title_japanese": "葬送のフリーレン", "type": "TV", "year": 2023, "url": "https://myanimelist.net/anime/52991",
    "titles": [{"type": "Default", "title": "Sousou no Frieren"}, {"type": "Synonym", "title": "Frieren at the Funeral"}],
}
OTHER = {"mal_id": 1, "title": "Frieren Recap", "title_english": "", "title_japanese": "", "titles": []}
OTHER_JP = {"mal_id": 2, "title": "Something Else", "title_english": "Something Else", "title_japanese": "別のもの", "titles": []}


class FakeHttp:
    def __init__(self, payload):
        self.payload, self.urls = payload, []

    def get_json(self, url, **kwargs):
        self.urls.append(url)
        return self.payload


def test_parse_entry():
    entry = _parse_entry(FRIEREN)
    assert entry.title_japanese == "葬送のフリーレン"
    assert entry.synonyms == ["Frieren at the Funeral"]


def test_best_match_prefers_exact_english_name():
    candidates = [_parse_entry(OTHER_JP), _parse_entry(FRIEREN)]
    assert best_match("frieren: beyond journey's end", candidates).mal_id == 52991


def test_best_match_skips_entries_without_japanese_title():
    candidates = [_parse_entry(OTHER), _parse_entry(OTHER_JP)]
    assert best_match("Frieren", candidates).mal_id == 2
    assert best_match("x", [_parse_entry(OTHER)]) is None


def test_japanese_title_lookup():
    http = FakeHttp({"data": [OTHER, FRIEREN]})
    result = MalLookup(http).japanese_title("Frieren: Beyond Journey's End")
    assert result.title_japanese == "葬送のフリーレン"
    assert "q=Frieren%3A+Beyond" in http.urls[0]


def test_empty_query_makes_no_request():
    http = FakeHttp({"data": []})
    assert MalLookup(http).search("  ") == []
    assert http.urls == []
