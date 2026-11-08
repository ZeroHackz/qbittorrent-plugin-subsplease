# SubsPlease for qBittorrent

[![tests](https://github.com/ZeroHackz/qbittorrent-plugin-subsplease/actions/workflows/tests.yml/badge.svg)](https://github.com/ZeroHackz/qbittorrent-plugin-subsplease/actions/workflows/tests.yml)
[![release](https://img.shields.io/github/v/release/ZeroHackz/qbittorrent-plugin-subsplease)](https://github.com/ZeroHackz/qbittorrent-plugin-subsplease/releases/latest)

A search plug-in for [qBittorrent](https://www.qbittorrent.org/) that adds [SubsPlease](https://subsplease.org/) as an anime search engine.

SubsPlease publishes every episode in 480p, 720p and 1080p. This plug-in reads the site's JSON API and returns **only the 1080p release**, so the result list is already filtered by the time it reaches qBittorrent.

## Features

- Search any show by name (`frieren`, `one piece`, `dandadan`, ...).
- Latest releases on demand: leave the search box empty or type `!latest`.
- 1080p only by default, with `!all` as a one-shot override for other resolutions.
- Season batches such as `(01-10)` are included next to single episodes.
- Exact file size, taken from the torrent's `xl` magnet parameter.
- Each row links to the show page on subsplease.org.
- Newest first.
- Standard library only: no `pip install`, no extra dependencies.

## Requirements

| Component | Version |
| --- | --- |
| qBittorrent | 5.0 or newer (verified on 5.2.0) |
| Python | 3.9 or newer, as shipped or supported by qBittorrent |
| Network | access to `subsplease.org` |

qBittorrent runs search plug-ins with Python. Most installers bundle or locate a compatible interpreter; on Linux you may need the `python3` package.

The plug-in only uses the standard search-plugin interface, so 4.x builds that ship Python 3.7 or newer should work as well, although they are not tested.

## Installation

### Option 1: qBittorrent (recommended)

1. Download [`subsplease.py`](https://github.com/ZeroHackz/qbittorrent-plugin-subsplease/releases/latest/download/subsplease.py) from the latest release (right click, then Save link as...).
2. In qBittorrent open **View > Search** (or the **Search** tab).
3. Click **Search plugins...**.
4. Click **Install a new one**, select the downloaded `subsplease.py`, and confirm.
5. Tick **SubsPlease** in the list of installed engines, then close the dialog.
6. Back in the Search tab, pick the **All** or **Anime** category, type a show name and press **Search**.

### Option 2: copy the file

Copy `subsplease.py` into qBittorrent's `nova3/engines` directory, restart qBittorrent, then enable the plug-in in **Search plugins...**.

| Platform | Directory |
| --- | --- |
| Windows, qBittorrent 5.x | `%LOCALAPPDATA%\qBittorrent\nova3\engines` |
| Windows, qBittorrent 4.x | `%APPDATA%\qBittorrent\nova3\engines` |
| Linux | `~/.local/share/qBittorrent/nova3/engines` |
| Linux (Flatpak) | `~/.var/app/org.qbittorrent.qBittorrent/data/qBittorrent/nova3/engines` |
| macOS | `~/Library/Application Support/qBittorrent/nova3/engines` |

Windows PowerShell:

```powershell
Copy-Item .\subsplease.py "$env:LOCALAPPDATA\qBittorrent\nova3\engines\"
```

Linux:

```bash
cp subsplease.py ~/.local/share/qBittorrent/nova3/engines/
```

macOS:

```bash
cp subsplease.py ~/Library/Application\ Support/qBittorrent/nova3/engines/
```

If the `engines` folder does not exist yet, create it. qBittorrent only creates the `nova3` tree after its first search, so a fresh install may need the folders made by hand.

### Check that the plug-in loads

qBittorrent runs `nova2.py` inside `nova3`. Run it yourself to see exactly what the plug-in produces.

Windows:

```powershell
cd "$env:LOCALAPPDATA\qBittorrent\nova3"
python nova2.py subsplease all frieren
```

Linux and macOS:

```bash
cd ~/.local/share/qBittorrent/nova3
python3 nova2.py subsplease all frieren
```

A working install prints one line per release:

```text
magnet:?xt=urn:btih:...|[SubsPlease] Sousou no Frieren S2 - 10 (1080p) [7D35515E].mkv|1457009569|-1|-1|https://subsplease.org|https://subsplease.org/shows/sousou-no-frieren-s2/|1774623759
```

The fields are: download link, name, size in bytes, seeds, leech, engine URL, description link, publication date (Unix timestamp).

`python nova2.py --capabilities` should also list a `subsplease` element with the name `SubsPlease` and the categories `anime tv`.

## Usage

| In the search box | What you get |
| --- | --- |
| `frieren` | Matching shows, newest 1080p releases first |
| `one piece` | Multi-word queries work |
| *(empty)* or `!latest` | The site's current latest releases (20 entries) |
| `!all frieren` | The same search without the 1080p filter (480p, 720p, 1080p) |

Notes:

- The category can be **All**, **Anime** or **TV**. All three are accepted and behave identically, because the site only catalogs anime.
- Seeds and leechers are always `-1`. subsplease.org does not publish swarm data, and the plug-in does not invent numbers. Sort by **Date** or **Size** rather than **Seeds**.
- The site's search API returns at most about 30 releases per query. For a long-running show that means the newest episodes plus any batches, not the full back catalogue.
- The 1080p filter is a single constant (`resolution = "1080"`) at the top of the class, so it is easy to change in a fork.

## How it works

The plug-in uses the same JSON API as the website:

| Endpoint | Purpose |
| --- | --- |
| `https://subsplease.org/api/?f=search&s=<query>&tz=UTC` | Search by show name |
| `https://subsplease.org/api/?f=latest&tz=UTC` | Latest releases |

A trimmed API entry:

```json
"Sousou no Frieren S2 - 10": {
  "show": "Sousou no Frieren S2",
  "episode": "10",
  "page": "sousou-no-frieren-s2",
  "release_date": "Fri, 27 Mar 2026 16:02:39 +0100",
  "downloads": [
    {"res": "480",  "magnet": "..."},
    {"res": "720",  "magnet": "..."},
    {"res": "1080", "magnet": "magnet:?xt=urn:btih:...&dn=...&xl=1457009569&tr=..."}
  ]
}
```

For every entry the plug-in keeps the `1080` download, reads the display name and exact size from the magnet (`dn` and `xl`), converts `release_date` to a Unix timestamp, and points the description link at `https://subsplease.org/shows/<page>/`.

Why not the RSS feed? `https://subsplease.org/rss/?r=1080` is a 1080p-only feed, but it carries only the most recent items and offers no search, so it cannot answer a query or reach older episodes. The JSON API supports both, and it returns exact sizes directly.

The `tz` parameter is required by the API but irrelevant to the plug-in: the timestamps already carry their own UTC offset.

## Troubleshooting

**SubsPlease does not appear in the plug-in list**

- The file must be named exactly `subsplease.py`, and the class inside must be named `subsplease`. qBittorrent refuses plug-ins where the file name and class name differ.
- Restart qBittorrent after a manual copy, then tick the engine in **Search plugins...**.
- Run the command-line check above. A syntax error there usually means the qBittorrent build uses a Python older than 3.9.

**The search returns no results**

- Check that https://subsplease.org/ opens in a browser.
- Use the romanized show title as it appears on the site, for example `sousou no frieren`.
- Run the command-line check. The plug-in writes the reason to stderr when the site answers with something unexpected.

**Seeds and leechers show `-1`**

That is expected. The site does not expose swarm data. Sort by date instead.

**It stopped working after a site change**

SubsPlease occasionally changes its API. Open an issue with the output of the command-line check.

## Uninstall

Open **Search plugins...**, select **SubsPlease** and click **Uninstall**. Alternatively, delete `subsplease.py` from the `nova3/engines` directory and restart qBittorrent.

## Development

The tests are offline: API responses come from `tests/fixtures/`, and `helpers` / `novaprinter` are stubbed out, so no qBittorrent installation is needed.

```bash
python -m unittest discover -s tests -v
```

CI runs the same suite on Python 3.11 and 3.13.

To test against the live site, copy the plug-in into `nova3/engines` and use the `nova2.py` command from the installation section.

## Disclaimer

This is an unofficial, community-made plug-in. It is not affiliated with SubsPlease or qBittorrent. It only searches a public index and does not host, mirror or distribute any content. Use it only for content you are legally allowed to download, and follow the laws that apply to you.

## License

[MIT](LICENSE)
