from animepahe_dl.library import Library


def test_follow_new_episodes_and_acknowledge(tmp_path):
    lib = Library(tmp_path / "library.json")
    show = lib.follow("animepahe", "abc", "Frieren", "poster", [1, 2, 3])
    assert lib.total_new() == 0 and lib.is_following("animepahe", "abc")

    lib.record_check("animepahe", "abc", [1, 2, 3, 4, 5])
    assert lib.new_numbers(show) == [4, 5] and lib.total_new() == 2

    lib.acknowledge("animepahe", "abc", [4, 5])
    assert lib.total_new() == 0


def test_downloaded_episode_is_not_new_and_missing_files_do_not_count(tmp_path):
    lib = Library(tmp_path / "library.json")
    show = lib.follow("animeheaven", "x1", "Show", "", [1])
    lib.record_check("animeheaven", "x1", [1, 2, 3])
    file = tmp_path / "ep2.mp4"
    file.write_bytes(b"x")
    lib.record_download("animeheaven", "x1", 2.0, str(file))
    lib.record_download("animeheaven", "x1", 3.0, str(tmp_path / "gone.mp4"))
    assert lib.downloaded_numbers("animeheaven", "x1") == {2.0}
    assert lib.new_numbers(show) == [3]  # 3 was deleted from disk, so it is not "downloaded"


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "library.json"
    lib = Library(path)
    lib.follow("animepahe", "abc", "Frieren", "p", [1, 2])
    lib.record_download("animepahe", "abc", 1, str(path))
    again = Library(path)
    assert again.shows()[0].title == "Frieren"
    assert again.downloaded_numbers("animepahe", "abc") == {1.0}


def test_check_all_survives_a_failing_show(tmp_path):
    lib = Library(tmp_path / "library.json")
    lib.follow("animepahe", "ok", "A", "", [1])
    lib.follow("animeheaven", "bad", "B", "", [1])

    def episodes_of(site, session):
        if session == "bad":
            raise RuntimeError("site down")
        return [1, 2]

    progress = []
    assert lib.check_all(episodes_of, lambda d, t: progress.append((d, t))) == 1
    assert progress == [(1, 2), (2, 2)]
    bad = lib.followed["animeheaven:bad"]
    assert bad.error == "site down" and bad.available == [1.0]


def test_unfollow_and_corrupt_file(tmp_path):
    path = tmp_path / "library.json"
    lib = Library(path)
    lib.follow("animepahe", "abc", "A", "", [1])
    lib.unfollow("animepahe", "abc")
    assert lib.shows() == []
    path.write_text("{not json", encoding="utf-8")
    assert Library(path).shows() == []
