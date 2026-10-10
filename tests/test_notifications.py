from animepahe_dl.animepahe import Episode
from animepahe_dl.downloader import DownloadTask, Status
from animepahe_dl.notifications import QueueWatcher, new_episodes_text


def task(number, status, title="Frieren", message=""):
    t = DownloadTask(title, "s", Episode(session=f"e{number}", number=float(number)))
    t.status, t.message = status, message
    return t


def test_nothing_to_report_until_the_queue_goes_idle():
    watcher = QueueWatcher()
    a, b = task(1, Status.DOWNLOADING), task(2, Status.QUEUED)
    assert watcher.update([]) is None  # never busy
    assert watcher.update([a, b]) is None
    a.status = Status.DONE
    assert watcher.update([a, b]) is None  # one episode still waiting
    b.status = Status.DONE
    summary = watcher.update([a, b])
    assert (summary.done, summary.failed) == (2, 0)
    assert summary.text() == ("Downloads finished", "2 completed")
    assert watcher.update([a, b]) is None  # reported once


def test_single_episode_messages():
    watcher = QueueWatcher()
    t = task(3, Status.DOWNLOADING)
    watcher.update([t])
    t.status = Status.DONE
    assert watcher.update([t]).text() == ("Download finished", "Frieren — Episode 03")
    t = task(4, Status.DOWNLOADING)
    watcher.update([t])
    t.status, t.message = Status.FAILED, "No video link found"
    assert watcher.update([t]).text() == ("Download failed", "Frieren — Episode 04\nNo video link found")


def test_mixed_results_and_quiet_cases():
    watcher = QueueWatcher()
    tasks = [task(1, Status.DOWNLOADING), task(2, Status.DOWNLOADING), task(3, Status.DOWNLOADING)]
    watcher.update(tasks)
    tasks[0].status, tasks[1].status, tasks[2].status = Status.DONE, Status.FAILED, Status.SKIPPED
    assert watcher.update(tasks).text() == ("Downloads finished with errors",
                                            "1 completed, 1 failed, 1 already downloaded")
    # only cancelled / already-downloaded episodes: nothing worth a notification
    only = [task(5, Status.QUEUED), task(6, Status.QUEUED)]
    watcher.update(only)
    only[0].status, only[1].status = Status.CANCELLED, Status.SKIPPED
    assert watcher.update(only) is None
    # a task removed from the list (Clear finished) is still counted from the tracked object
    t = task(7, Status.DOWNLOADING)
    watcher.update([t])
    t.status = Status.DONE
    assert watcher.update([]).done == 1


def test_new_episodes_text():
    assert new_episodes_text(1, ["A"]) == ("New episode", "1 new in your watchlist: A")
    assert new_episodes_text(7, ["A", "B", "C", "D", "E"]) == (
        "New episodes", "7 new in your watchlist: A, B, C and 2 more")
