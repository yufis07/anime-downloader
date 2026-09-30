"""Command-line interface (handy for scripting or when the GUI is not wanted).

Examples::

    AnimePaheDL.exe cli search "frieren"
    AnimePaheDL.exe cli japanese "Frieren: Beyond Journey's End"
    AnimePaheDL.exe cli download https://animepahe.pw/anime/<uuid> -e 1-12 -q 720 -a eng
"""

from __future__ import annotations

import argparse
import sys
import time

from .animepahe import AnimePahe, parse_anime_session
from .config import Settings
from .downloader import DownloadManager, Status
from .http import CloudflareChallenge, HttpClient, HttpError
from .mal import MalLookup
from .utils import format_episode, format_speed, parse_episode_selection


def _build(args: argparse.Namespace) -> tuple[Settings, AnimePahe]:
    settings = Settings.load()
    if args.base_url:
        settings.base_url = args.base_url
    if args.cookie:
        for pair in args.cookie:
            name, _, value = pair.partition("=")
            settings.cookies[name.strip()] = value.strip()
    if args.user_agent:
        settings.user_agent = args.user_agent
    settings.normalize()
    http = HttpClient(settings.user_agent, settings.cookies)
    return settings, AnimePahe(http, settings.base_url)


def cmd_search(args: argparse.Namespace) -> int:
    _, api = _build(args)
    for index, anime in enumerate(api.search(args.query), 1):
        print(f"{index:2}. {anime.title}  [{anime.subtitle}]")
        print(f"    {api.base_url}/anime/{anime.session}")
    return 0


def cmd_japanese(args: argparse.Namespace) -> int:
    try:
        match = MalLookup().japanese_title(args.title)
    except HttpError as exc:
        print(f"MyAnimeList lookup failed: {exc}", file=sys.stderr)
        return 2
    if not match:
        print("No match found on MyAnimeList.")
        return 1
    print(match.title)
    print(f"  {match.url}")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    settings, api = _build(args)
    if args.quality:
        settings.quality = args.quality
    if args.audio:
        settings.audio = args.audio
    if args.output:
        settings.download_dir = args.output
    if args.parallel:
        settings.max_parallel_episodes = args.parallel
    if args.japanese_names:
        settings.rename_japanese = True
    settings.normalize()

    session = parse_anime_session(args.anime)
    if session:
        title = api.anime_title(session)
    else:
        results = api.search(args.anime)
        if not results:
            print("No anime found.")
            return 1
        session, title = results[0].session, results[0].title
    print(f"Anime: {title}")
    episodes = api.episodes(session)
    wanted = set(parse_episode_selection(args.episodes, [e.number for e in episodes]))
    chosen = [e for e in episodes if e.number in wanted]
    if not chosen:
        print("No matching episodes.")
        return 1
    print(f"Downloading {len(chosen)} episode(s) to {settings.download_dir}")

    manager = DownloadManager(api, settings)
    manager.add(title, session, chosen)
    try:
        while manager.is_busy():
            line = " | ".join(
                f"E{format_episode(t.episode.number)} {t.status.value} {t.progress:4.0%} {format_speed(t.speed)}"
                for t in manager.snapshot() if not t.status.finished
            )
            print("\r" + line[:200].ljust(200), end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        manager.shutdown()
        print("\nCancelled.")
        return 130
    print()
    failed = 0
    for task in manager.snapshot():
        print(f"E{format_episode(task.episode.number)}: {task.status.value} {task.output_path} {task.message}".rstrip())
        failed += task.status == Status.FAILED
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="AnimePaheDL cli", description="AnimePahe downloader")
    parser.add_argument("--base-url", help="Site address, e.g. https://animepahe.pw")
    parser.add_argument("--cookie", action="append", help="Extra cookie NAME=VALUE (e.g. cf_clearance=...)")
    parser.add_argument("--user-agent", help="User-Agent of the browser that produced cf_clearance")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Search anime by title")
    search.add_argument("query")
    search.set_defaults(func=cmd_search)

    japanese = sub.add_parser("japanese", help="Look up an English title on MyAnimeList and print its Japanese (romaji) title")
    japanese.add_argument("title")
    japanese.set_defaults(func=cmd_japanese)

    download = sub.add_parser("download", help="Download episodes")
    download.add_argument("anime", help="Anime URL, session id or search text (first hit is used)")
    download.add_argument("-e", "--episodes", default="all", help="e.g. 1-12,15 or 20- (default: all)")
    download.add_argument("-q", "--quality", type=int, choices=(1080, 720, 480, 360))
    download.add_argument("-a", "--audio", choices=("jpn", "eng", "any"))
    download.add_argument("-o", "--output", help="Download folder")
    download.add_argument("-p", "--parallel", type=int, help="Episodes downloaded at the same time")
    download.add_argument("--japanese-names", action="store_true",
                          help="Rename the file and folder to the Japanese title (MyAnimeList) once downloaded")
    download.set_defaults(func=cmd_download)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CloudflareChallenge as exc:
        print(f"\n{exc}\nOpen the site in your browser, copy the cf_clearance cookie and your "
              "browser's User-Agent, then pass --cookie cf_clearance=... --user-agent \"...\"",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
