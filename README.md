# finder-pane

Web-based Finder-like file browser for macOS. Browse your filesystem in the browser.

![Python](https://img.shields.io/badge/python-3.8+-blue) ![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)

## Why finder-pane?

When working in the terminal with [Claude Code](https://docs.anthropic.com/en/docs/claude-code), you often need to:

- **See directory structure at a glance** — `ls` and `tree` don't give you the full picture
- **Preview images** — check generated images or screenshots without leaving the terminal
- **Preview videos** — quickly verify video output

finder-pane is a Finder-like file browser that runs in a browser pane. Combined with [cmux](https://cmux.dev), you can keep a file browser right next to Claude Code — browse directory trees, preview images and videos, all without switching windows.

### cmux + Claude Code

```
┌─────────────────────┬──────────────────────┐
│                     │                      │
│   Claude Code       │   finder-pane        │
│                     │                      │
│  > generate image   │  📁 output/           │
│  > show me          │    🖼️ result.png  ◀── │
│                     │    [preview pane]     │
│                     │                      │
└─────────────────────┴──────────────────────┘
```

Tell Claude Code "show me in finder-pane" and it opens the file in a cmux browser pane.

## Install

```sh
git clone https://github.com/orchardworks/finder-pane.git
cd finder-pane
```

### Claude Code skill

finder-pane ships with a Claude Code skill. Once installed, saying things like "show me in finder-pane" or "I want to see the directory structure" will automatically start finder-pane and display files.

```sh
ln -s "$(pwd)/skill" ~/.claude/skills/finder-pane
```

## Quick start

```sh
./start.sh          # starts on port 8234
./start.sh 9000     # or specify a port
```

Open `http://localhost:8234` in your browser.

### With cmux

```sh
cmux browser open http://localhost:8234
```

## Features

- **Finder sidebar sync** — reads your actual Finder sidebar favorites via `LSSharedFileList` API (Swift)
- **Volumes/Locations** — mounted external drives automatically appear in the sidebar
- **Tree expansion** — click `▶` on folders to expand inline, just like Finder's list view
- **Image/video preview** — single-click a file to preview images (`png`, `jpg`, `gif`, `webp`, `heic`, ...) and videos (`mp4`, `mov`, `mkv`, ...) in a side pane
- **URL = path** — the browser URL reflects the current directory (e.g., `localhost:8234/Users/you/Desktop`), and direct URL access works
- **Sort, filter, hidden files** — click column headers to sort, type to filter, toggle `.*` to show hidden files
- **Zero dependencies** — pure Python standard library + a small Swift snippet (compiled and cached automatically)

## Requirements

- macOS
- Python 3.8+
- Xcode Command Line Tools (`swiftc` — used to read Finder sidebar)

## API

`server.py` runs a lightweight HTTP server:

| Endpoint | Description |
|---|---|
| `/` | Single-page UI (`index.html`) |
| `/api/ls?dir=PATH` | Directory listing (JSON) |
| `/api/favorites` | Finder sidebar favorites (via compiled Swift binary) |
| `/api/volumes` | Mounted volumes from `/Volumes/` |
| `/api/file?path=PATH` | Raw file content with correct MIME type |
| `/api/open?path=PATH` | Open file with macOS default app |
| `/*` | Any path serves the file directly, or the UI if it's a directory |

## License

MIT
