# Changelog

Newest first. The version number is shown in the sidebar next to the build (commit) the exe was made from.

## 1.2.0 - 2026-10-10

### Added
- **AnimeHeaven** as a second download site: pick it next to the search box (`--site animeheaven` on the command
  line). Plain `.mp4` files with resume.
- **Rename to romaji.** After a download finishes, the file and folder are renamed to the Japanese (romaji) title,
  e.g. "Sousou no Frieren". MyAnimeList (Jikan) first, AniList as the fallback; AnimeHeaven's own title is used
  directly. The queue says why a name was kept.
- **Watchlist.** Follow shows, see *N new* badges, download the new episodes in one click. Episode lists mark
  what you already have with a check and have a *Select missing* button.
- **Show page** with banner, cover, other-language title, score, studio, genres and a collapsible synopsis (AniList).
- **Discover home** with *Trending now*, *This season* and *Top rated* rows; click a title to find it on the
  selected site.
- **Queue polish:** cover thumbnails, time left per download and overall, smoother progress, *Top / up / down*
  buttons to change the start order.
- **Update banner** that compares the build with the latest GitHub release (needs a read-only token in Settings
  while the repository is private).
- **Tray icon and notifications:** queue finished, new watchlist episodes, optional close-to-tray.
- **First-run setup** wizard (download folder, one-click ffmpeg with checksum check, preferences) and
  **portable mode** (`portable.txt` next to the exe).
- **App icon:** an original blade icon (also for the exe), a switch back to the classic purple one, and support
  for your own `AnimePaheDL.ico` / `icon.png`.
- **Japanese title** button and `cli japanese "<title>"` for looking up a romaji title.
- A **Support** section and a Sponsor button (Buy Me a Coffee).

### Changed
- Every push to `main` publishes the Windows build as the rolling **latest** GitHub release.
- CI lints (unused imports and names) and runs the tests before building.

### Fixed
- Windows builds failed after the update banner was added (the build stamp was written before the tests ran).

## 1.1.2
- Previous release: AnimePahe search, episode selection, parallel resumable downloads, MP4 output through ffmpeg,
  Cloudflare verification window, command-line mode.
