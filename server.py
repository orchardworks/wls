#!/usr/bin/env python3
"""Finder-like file browser server for cmux browser panes."""

import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8234
except ValueError:
    PORT = 8234

# Swift script to read Finder sidebar favorites via LSSharedFileList API
SWIFT_CODE = r"""
import Cocoa

let listRef = LSSharedFileListCreate(nil, kLSSharedFileListFavoriteItems.takeUnretainedValue(), nil)
guard let list = listRef?.takeRetainedValue() else {
    print("[]")
    exit(0)
}

var seed: UInt32 = 0
guard let items = LSSharedFileListCopySnapshot(list, &seed)?.takeRetainedValue() as? [LSSharedFileListItem] else {
    print("[]")
    exit(0)
}

var results: [[String: String]] = []
for item in items {
    if let url = LSSharedFileListItemCopyResolvedURL(item, 0, nil)?.takeRetainedValue() as URL? {
        if url.isFileURL {
            let nameRef = LSSharedFileListItemCopyDisplayName(item)
            let name = nameRef.takeRetainedValue() as String
            results.append(["name": name, "path": url.path])
        }
    }
}

if let jsonData = try? JSONSerialization.data(withJSONObject: results, options: []),
   let jsonString = String(data: jsonData, encoding: .utf8) {
    print(jsonString)
}
"""

SWIFT_ICON_CODE = r"""
import Cocoa

guard CommandLine.arguments.count > 2 else {
    fputs("Usage: icon <path> <output.png>\n", stderr)
    exit(1)
}

let path = CommandLine.arguments[1]
let output = CommandLine.arguments[2]

let ws = NSWorkspace.shared
let icon = ws.icon(forFile: path)

// Get 128x128 representation
let size = NSSize(width: 128, height: 128)
icon.size = size

guard let tiff = icon.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiff),
      let png = rep.representation(using: .png, properties: [:]) else {
    exit(1)
}

let url = URL(fileURLWithPath: output)
try! png.write(to: url)
"""

# macOS bundle extensions that should be treated as files, not folders
BUNDLE_EXTS = {
    ".app", ".framework", ".bundle", ".plugin", ".kext",
    ".xcodeproj", ".xcworkspace", ".playground",
    ".prefPane", ".screensaver", ".pkg", ".mpkg", ".rtfd",
}

_compile_lock = threading.Lock()

def _compile_swift_cached(name, code):
    """Compile Swift code to a cached binary. Thread-safe via atomic rename."""
    cache_dir = os.path.join(tempfile.gettempdir(), "wls_cache")
    os.makedirs(cache_dir, exist_ok=True)
    code_hash = hashlib.md5(code.encode()).hexdigest()[:12]
    binary_path = os.path.join(cache_dir, f"{name}_{code_hash}")
    if os.path.exists(binary_path):
        return binary_path
    with _compile_lock:
        if os.path.exists(binary_path):
            return binary_path
        swift_src = os.path.join(cache_dir, f"{name}.swift")
        tmp_bin = binary_path + f".tmp.{os.getpid()}"
        with open(swift_src, "w") as f:
            f.write(code)
        subprocess.run(
            ["swiftc", "-O", "-framework", "Cocoa", "-suppress-warnings",
             swift_src, "-o", tmp_bin],
            check=True, capture_output=True,
        )
        os.rename(tmp_bin, binary_path)
    return binary_path

def _get_swift_binary():
    return _compile_swift_cached("favorites", SWIFT_CODE)

def _get_icon_binary():
    return _compile_swift_cached("icon", SWIFT_ICON_CODE)

# Cache for icon PNGs: path -> png_path
_icon_cache = {}

class FinderHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len else {}

        if parsed.path == "/api/trash":
            self.trash_item(body.get("path", ""))
        elif parsed.path == "/api/rename":
            self.rename_item(body.get("path", ""), body.get("name", ""))
        elif parsed.path == "/api/move":
            self.move_item(body.get("paths", []), body.get("dest", ""))
        elif parsed.path == "/api/copy":
            self.copy_item(body.get("paths", []), body.get("dest", ""))
        elif parsed.path == "/api/mkdir":
            self.make_directory(body.get("dir", ""), body.get("name", ""))
        else:
            self.send_error(404)

    def trash_item(self, filepath):
        """Move file/folder to Trash via macOS NSFileManager API."""
        filepath = os.path.abspath(filepath)
        if not os.path.exists(filepath):
            self.send_error(404, "Not found")
            return
        try:
            # Use Swift with NSFileManager.trashItem — path passed as argument, not interpolated
            swift_code = (
                'import Foundation;'
                'let fm = FileManager.default;'
                'let url = URL(fileURLWithPath: CommandLine.arguments[1]);'
                'try fm.trashItem(at: url, resultingItemURL: nil)'
            )
            subprocess.run(
                ["swift", "-e", swift_code, filepath],
                check=True, capture_output=True, timeout=10,
            )
            self._json_response({"ok": True})
        except Exception as e:
            self.send_error(500, str(e))

    def rename_item(self, filepath, new_name):
        """Rename a file or folder."""
        filepath = os.path.abspath(filepath)
        if not os.path.exists(filepath):
            self.send_error(404, "Not found")
            return
        if not new_name or "/" in new_name:
            self.send_error(400, "Invalid name")
            return
        new_path = os.path.join(os.path.dirname(filepath), new_name)
        if os.path.exists(new_path):
            self.send_error(409, "Already exists")
            return
        try:
            os.rename(filepath, new_path)
            self._json_response({"ok": True, "path": new_path})
        except Exception as e:
            self.send_error(500, str(e))

    def move_item(self, paths, dest):
        """Move files/folders into a destination directory."""
        import shutil
        dest = os.path.abspath(dest)
        if not os.path.isdir(dest):
            self.send_error(400, "Destination is not a directory")
            return
        errors = []
        for p in paths:
            p = os.path.abspath(p)
            name = os.path.basename(p)
            if not os.path.exists(p):
                errors.append(f"{name}: not found")
                continue
            target = os.path.join(dest, name)
            if os.path.exists(target):
                if os.path.abspath(target) == os.path.abspath(p):
                    continue
                errors.append(f"{name}: already exists")
                continue
            try:
                shutil.move(p, target)
            except Exception as e:
                errors.append(f"{name}: {e}")
        if errors:
            self._json_response({"ok": False, "errors": errors}, status=207)
        else:
            self._json_response({"ok": True})

    def copy_item(self, paths, dest):
        """Copy files/folders into a destination directory."""
        import shutil
        dest = os.path.abspath(dest)
        if not os.path.isdir(dest):
            self.send_error(400, "Destination is not a directory")
            return
        errors = []
        for p in paths:
            p = os.path.abspath(p)
            name = os.path.basename(p)
            if not os.path.exists(p):
                errors.append(f"{name}: not found")
                continue
            target = os.path.join(dest, name)
            if os.path.exists(target):
                if os.path.abspath(target) == os.path.abspath(p):
                    continue
                errors.append(f"{name}: already exists")
                continue
            try:
                if os.path.isdir(p):
                    shutil.copytree(p, target)
                else:
                    shutil.copy2(p, target)
            except Exception as e:
                errors.append(f"{name}: {e}")
        if errors:
            self._json_response({"ok": False, "errors": errors}, status=207)
        else:
            self._json_response({"ok": True})

    def make_directory(self, parent, name):
        """Create a new directory."""
        parent = os.path.abspath(parent)
        if not os.path.isdir(parent):
            self.send_error(400, "Parent is not a directory")
            return
        if not name or "/" in name:
            self.send_error(400, "Invalid name")
            return
        new_path = os.path.join(parent, name)
        if os.path.exists(new_path):
            self.send_error(409, "Already exists")
            return
        try:
            os.makedirs(new_path)
            self._json_response({"ok": True, "path": new_path})
        except Exception as e:
            self.send_error(500, str(e))

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")

        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/":
            self.serve_html()
        elif parsed.path == "/api/ls":
            params = urllib.parse.parse_qs(parsed.query)
            directory = params.get("dir", [os.path.expanduser("~")])[0]
            self.serve_listing(directory)
        elif parsed.path == "/api/favorites":
            self.serve_favorites()
        elif parsed.path == "/api/volumes":
            self.serve_volumes()
        elif parsed.path == "/api/file":
            params = urllib.parse.parse_qs(parsed.query)
            filepath = params.get("path", [""])[0]
            self.serve_file(filepath)
        elif parsed.path == "/api/open":
            params = urllib.parse.parse_qs(parsed.query)
            filepath = params.get("path", [""])[0]
            reveal = params.get("reveal", [""])[0] == "1"
            self.open_file(filepath, reveal=reveal)
        elif parsed.path == "/api/icon":
            params = urllib.parse.parse_qs(parsed.query)
            filepath = params.get("path", [""])[0]
            self.serve_app_icon(filepath)
        elif parsed.path == "/icon.png":
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
            self.serve_file(icon_path)
        else:
            # URL path → file path (e.g., /Users/.../photo.jpg → serve that file)
            filepath = urllib.parse.unquote(parsed.path)
            realpath = os.path.realpath(filepath)
            if os.path.isfile(realpath):
                self.serve_file(realpath)
            elif os.path.isdir(realpath):
                # ディレクトリならUIを返してそのディレクトリを開く
                self.serve_html()
            else:
                self.send_error(404)

    def serve_listing(self, directory):
        try:
            directory = os.path.abspath(os.path.expanduser(directory))
            entries = []
            for name in sorted(os.listdir(directory), key=str.lower):
                full = os.path.join(directory, name)
                try:
                    stat = os.stat(full)
                    is_dir = os.path.isdir(full)
                    # Get file extension
                    ext = os.path.splitext(name)[1].lower()
                    is_bundle = is_dir and ext in BUNDLE_EXTS
                    entry = {
                        "name": name,
                        "path": full,
                        "is_dir": is_dir and not is_bundle,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "ext": ext,
                        "hidden": name.startswith("."),
                    }
                    if is_bundle:
                        entry["is_bundle"] = True
                    if os.path.islink(full):
                        entry["is_symlink"] = True
                    entries.append(entry)
                except (PermissionError, OSError):
                    continue

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
    
            self.end_headers()
            self.wfile.write(json.dumps({
                "dir": directory,
                "parent": str(Path(directory).parent),
                "entries": entries,
            }).encode())
        except PermissionError:
            self.send_error(403, "Permission denied")
        except FileNotFoundError:
            self.send_error(404, "Directory not found")

    def serve_favorites(self):
        try:
            binary = _get_swift_binary()
            result = subprocess.run(
                [binary], capture_output=True, text=True, timeout=5,
            )
            favorites = json.loads(result.stdout) if result.stdout.strip() else []
        except Exception:
            # Fallback
            home = os.path.expanduser("~")
            favorites = []
            for name, sub in [("Desktop", "Desktop"), ("Documents", "Documents"), ("Downloads", "Downloads")]:
                p = os.path.join(home, sub)
                if os.path.isdir(p):
                    favorites.append({"name": name, "path": p})

        self.send_response(200)
        self.send_header("Content-Type", "application/json")

        self.end_headers()
        self.wfile.write(json.dumps(favorites).encode())

    def serve_volumes(self):
        volumes = []
        volumes_dir = "/Volumes"
        if os.path.isdir(volumes_dir):
            for name in sorted(os.listdir(volumes_dir)):
                full = os.path.join(volumes_dir, name)
                if os.path.isdir(full):
                    volumes.append({"name": name, "path": full})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")

        self.end_headers()
        self.wfile.write(json.dumps(volumes).encode())

    def serve_file(self, filepath):
        """Serve a file's content with appropriate Content-Type. Supports Range requests."""
        filepath = os.path.abspath(filepath)
        # Security: only serve actual files
        if not os.path.isfile(filepath):
            self.send_error(404, "File not found")
            return
        try:
            mime, _ = mimetypes.guess_type(filepath)
            if mime is None:
                mime = "application/octet-stream"
            size = os.path.getsize(filepath)

            # Handle Range requests (for video/audio seeking)
            range_header = self.headers.get("Range")
            start = end = None
            if range_header and range_header.startswith("bytes="):
                try:
                    range_spec = range_header[6:].split(",")[0].strip()
                    parts = range_spec.split("-")
                    if not parts[0]:
                        start = max(size - int(parts[1]), 0)
                        end = size - 1
                    else:
                        start = int(parts[0])
                        end = int(parts[1]) if parts[1] else size - 1
                    end = min(end, size - 1)
                    if start >= size or start < 0:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                except (ValueError, IndexError):
                    start = end = None  # fall through to normal 200

            if start is not None:
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "max-age=60")
                self.end_headers()
                with open(filepath, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return

            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "max-age=60")
            self.end_headers()
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except PermissionError:
            self.send_error(403, "Permission denied")
        except Exception as e:
            self.send_error(500, str(e))

    def serve_app_icon(self, filepath):
        """Get the macOS icon for a file/app as PNG."""
        filepath = os.path.abspath(filepath)
        if not os.path.exists(filepath):
            self.send_error(404, "Not found")
            return
        try:
            # Check cache
            if filepath in _icon_cache and os.path.exists(_icon_cache[filepath]):
                self.serve_file(_icon_cache[filepath])
                return

            cache_dir = os.path.join(tempfile.gettempdir(), "wls_cache", "icons")
            os.makedirs(cache_dir, exist_ok=True)

            # Use path hash for cache filename
            path_hash = hashlib.md5(filepath.encode()).hexdigest()[:16]
            png_path = os.path.join(cache_dir, f"{path_hash}.png")

            if not os.path.exists(png_path):
                binary = _get_icon_binary()
                subprocess.run(
                    [binary, filepath, png_path],
                    check=True, capture_output=True, timeout=5,
                )

            _icon_cache[filepath] = png_path
            self.serve_file(png_path)
        except Exception as e:
            self.send_error(500, str(e))

    def open_file(self, filepath, reveal=False):
        try:
            cmd = ["open", "-R", filepath] if reveal else ["open", filepath]
            subprocess.Popen(cmd)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
        except Exception as e:
            self.send_error(500, str(e))

    def serve_html(self):
        html_path = os.path.join(os.path.dirname(__file__), "index.html")
        with open(html_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass  # suppress logs

def _precompile_swift():
    """Pre-compile Swift binaries in background so first request is fast."""
    try:
        _get_swift_binary()
        _get_icon_binary()
    except Exception:
        pass  # Will be retried on first request

if __name__ == "__main__":
    threading.Thread(target=_precompile_swift, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), FinderHandler)
    print(f"Finder browser: http://127.0.0.1:{PORT}")
    server.serve_forever()
