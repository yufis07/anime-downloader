import time

from animepahe_dl.animepahe import Episode
from animepahe_dl.config import Settings
from animepahe_dl.downloader import DownloadManager, DownloadTask, Status
from animepahe_dl.utils import format_eta


def test_format_eta():
    assert format_eta(None) == "" and format_eta(-1) == "" and format_eta(float("inf")) == ""
    assert format_eta(0.2) == "1 s" and format_eta(45) == "45 s"
    assert format_eta(120) == "2 min" and format_eta(3900) == "1 h 05 min"


def test_eta_from_progress_and_speed():
    task = DownloadTask("A", "s", Episode(session="e", number=1.0))
    assert task.eta is None  # not downloading yet
    task.status = Status.DOWNLOADING
    task.segments_total, task.segments_done = 100, 25
    assert task.eta is None  # no bytes / speed yet
    task.record_bytes(25_000_000)  # 25 % done = 25 MB, so 75 MB left
    assert abs(task.remaining_bytes - 75_000_000) < 1
    time.sleep(0.05)
    assert task.speed > 0 and task.eta == task.remaining_bytes / task.speed
    task.segments_done = 1  # under 2 %: too early to estimate
    assert task.remaining_bytes is None


def _manager():
    manager = DownloadManager(None, Settings(download_dir="unused"))
    manager.pause_all()  # keep the dispatcher from starting anything
    episodes = [Episode(session=f"e{n}", number=float(n)) for n in range(1, 5)]
    manager.add("Show", "s", episodes)
    return manager


def numbers(manager):
    return [int(t.episode.number) for t in manager.snapshot()]


def test_move_waiting_downloads():
    manager = _manager()
    ids = {int(t.episode.number): t.id for t in manager.snapshot()}
    assert manager.move_task(ids[3], "top") and numbers(manager) == [3, 1, 2, 4]
    assert manager.move_task(ids[4], "up") and numbers(manager) == [3, 1, 4, 2]
    assert manager.move_task(ids[3], "down") and numbers(manager) == [1, 3, 4, 2]
    assert not manager.move_task(ids[1], "up") and not manager.move_task(ids[2], "down")  # already at the ends
    assert not manager.move_task(ids[1], "sideways")
    manager.shutdown()


def test_running_and_finished_downloads_are_skipped_when_moving():
    manager = _manager()
    first, second, third, fourth = manager.snapshot()
    first.status = Status.DOWNLOADING  # already running: stays put
    fourth.status = Status.DONE
    assert manager.move_task(third.id, "up") and numbers(manager) == [1, 3, 2, 4]
    assert not manager.move_task(first.id, "down")  # not waiting any more
    assert not manager.move_task(fourth.id, "top")
    manager.shutdown()
