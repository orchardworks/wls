# wls

Web-based Finder-like file browser for macOS. "web ls" — browse your filesystem in the browser.

![Python](https://img.shields.io/badge/python-3.8+-blue) ![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)

## Features

- **Finder sidebar sync** — reads your actual Finder sidebar favorites via `LSSharedFileList` API (Swift)
- **Volumes/Locations** — mounted external drives automatically appear in the sidebar
- **Tree expansion** — click `▶` on folders to expand inline, just like Finder's list view
- **Image/video preview** — single-click a file to preview images (`png`, `jpg`, `gif`, `webp`, `heic`, ...) and videos (`mp4`, `mov`, `mkv`, ...) in a side pane
- **URL = path** — the browser URL reflects the current directory (e.g., `http://localhost:8234/Users/you/Desktop`), and direct URL access works
- **Sort, filter, hidden files** — click column headers to sort, type to filter, toggle `.*` to show hidden files
- **Keyboard navigation** — `Backspace` to go up a directory
- **Zero dependencies** — pure Python standard library + a small Swift snippet (compiled and cached automatically)

## Quick start

```sh
./start.sh          # starts on port 8234
./start.sh 9000     # or specify a port
```

Then open `http://localhost:8234` in your browser.

## Requirements

- macOS (uses `LSSharedFileList` API for Finder favorites, `open` command for file opening)
- Python 3.8+
- Xcode Command Line Tools (for `swiftc` — the Swift compiler, used to read Finder sidebar)

## How it works

`server.py` runs a lightweight HTTP server that serves:

| Endpoint | Description |
|---|---|
| `/` | The single-page UI (`index.html`) |
| `/api/ls?dir=PATH` | JSON directory listing |
| `/api/favorites` | Finder sidebar favorites (via compiled Swift binary) |
| `/api/volumes` | Mounted volumes from `/Volumes/` |
| `/api/file?path=PATH` | Raw file content with correct MIME type |
| `/api/open?path=PATH` | Opens file with macOS default app |
| `/*` | Any path serves the file directly, or the UI if it's a directory |

## License

MIT
