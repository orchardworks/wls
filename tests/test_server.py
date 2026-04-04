"""Tests for wls server API endpoints."""

import json
import os
import shutil
import tempfile
import threading
import time
import urllib.request
import urllib.error

import pytest

# Import server module
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import server


@pytest.fixture(scope="module")
def test_server():
    """Start a test server on a random port."""
    port = 18234
    srv = server.HTTPServer(("127.0.0.1", port), server.FinderHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture
def temp_dir():
    """Create a temporary directory with test files."""
    d = tempfile.mkdtemp(prefix="wls_test_")
    # Create test files and directories
    os.makedirs(os.path.join(d, "subdir"))
    os.makedirs(os.path.join(d, ".hidden_dir"))
    with open(os.path.join(d, "file.txt"), "w") as f:
        f.write("hello")
    with open(os.path.join(d, "image.png"), "w") as f:
        f.write("fake png")
    with open(os.path.join(d, ".hidden_file"), "w") as f:
        f.write("hidden")
    with open(os.path.join(d, "Makefile"), "w") as f:
        f.write("all:\n\techo hi")
    # Create a fake .app bundle (directory)
    os.makedirs(os.path.join(d, "Test.app", "Contents"))
    # Create a symlink
    os.symlink(os.path.join(d, "file.txt"), os.path.join(d, "link.txt"))
    yield d
    shutil.rmtree(d)


# --- /api/ls ---

class TestListDirectory:
    def test_list_home(self, test_server):
        url = f"{test_server}/api/ls?dir=~"
        data = json.loads(urllib.request.urlopen(url).read())
        assert "dir" in data
        assert "parent" in data
        assert "entries" in data
        assert isinstance(data["entries"], list)

    def test_list_temp_dir(self, test_server, temp_dir):
        url = f"{test_server}/api/ls?dir={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        assert data["dir"] == temp_dir
        names = [e["name"] for e in data["entries"]]
        assert "file.txt" in names
        assert "subdir" in names
        assert "image.png" in names
        assert ".hidden_file" in names
        assert ".hidden_dir" in names
        assert "Makefile" in names

    def test_entry_fields(self, test_server, temp_dir):
        url = f"{test_server}/api/ls?dir={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        txt = next(e for e in data["entries"] if e["name"] == "file.txt")
        assert txt["is_dir"] is False
        assert txt["ext"] == ".txt"
        assert txt["hidden"] is False
        assert txt["size"] == 5
        assert "modified" in txt
        assert "path" in txt

    def test_directory_entry(self, test_server, temp_dir):
        url = f"{test_server}/api/ls?dir={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        subdir = next(e for e in data["entries"] if e["name"] == "subdir")
        assert subdir["is_dir"] is True

    def test_hidden_files(self, test_server, temp_dir):
        url = f"{test_server}/api/ls?dir={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        hidden = next(e for e in data["entries"] if e["name"] == ".hidden_file")
        assert hidden["hidden"] is True
        hidden_dir = next(e for e in data["entries"] if e["name"] == ".hidden_dir")
        assert hidden_dir["hidden"] is True

    def test_bundle_detection(self, test_server, temp_dir):
        """`.app` directories should be detected as bundles, not regular dirs."""
        url = f"{test_server}/api/ls?dir={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        app = next(e for e in data["entries"] if e["name"] == "Test.app")
        assert app["is_dir"] is False, ".app should not be treated as navigable dir"
        assert app.get("is_bundle") is True
        assert app["ext"] == ".app"

    def test_symlink_detection(self, test_server, temp_dir):
        """Symlinks should have is_symlink=True."""
        url = f"{test_server}/api/ls?dir={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        link = next(e for e in data["entries"] if e["name"] == "link.txt")
        assert link.get("is_symlink") is True
        # Regular file should not have is_symlink
        regular = next(e for e in data["entries"] if e["name"] == "file.txt")
        assert "is_symlink" not in regular

    def test_parent_directory(self, test_server, temp_dir):
        url = f"{test_server}/api/ls?dir={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        assert data["parent"] == os.path.dirname(temp_dir)

    def test_nonexistent_directory(self, test_server):
        url = f"{test_server}/api/ls?dir=/nonexistent_dir_xyz"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url)
        assert exc_info.value.code == 404

    def test_sorted_case_insensitive(self, test_server, temp_dir):
        """Entries should be sorted case-insensitively."""
        url = f"{test_server}/api/ls?dir={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        names = [e["name"] for e in data["entries"]]
        assert names == sorted(names, key=str.lower)


# --- /api/rename ---

class TestRename:
    def test_rename_file(self, test_server, temp_dir):
        src = os.path.join(temp_dir, "file.txt")
        assert os.path.exists(src)
        data = json.dumps({"path": src, "name": "renamed.txt"}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/rename",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["ok"] is True
        assert not os.path.exists(src)
        assert os.path.exists(os.path.join(temp_dir, "renamed.txt"))

    def test_rename_nonexistent(self, test_server, temp_dir):
        data = json.dumps({"path": os.path.join(temp_dir, "nope.txt"), "name": "x.txt"}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/rename",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 404

    def test_rename_invalid_name_with_slash(self, test_server, temp_dir):
        src = os.path.join(temp_dir, "image.png")
        data = json.dumps({"path": src, "name": "bad/name.png"}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/rename",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400

    def test_rename_conflict(self, test_server, temp_dir):
        """Renaming to an existing name should fail with 409."""
        data = json.dumps({"path": os.path.join(temp_dir, "image.png"), "name": "Makefile"}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/rename",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 409


# --- /api/move ---

class TestMove:
    def test_move_file(self, test_server, temp_dir):
        src = os.path.join(temp_dir, "image.png")
        dest = os.path.join(temp_dir, "subdir")
        data = json.dumps({"paths": [src], "dest": dest}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/move",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["ok"] is True
        assert not os.path.exists(src)
        assert os.path.exists(os.path.join(dest, "image.png"))

    def test_move_to_nondir(self, test_server, temp_dir):
        src = os.path.join(temp_dir, "Makefile")
        data = json.dumps({"paths": [src], "dest": os.path.join(temp_dir, "file.txt")}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/move",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400

    def test_move_conflict(self, test_server, temp_dir):
        """Moving a file where target already exists should return 207 with errors."""
        # Create a file in subdir with same name
        with open(os.path.join(temp_dir, "subdir", "Makefile"), "w") as f:
            f.write("conflict")
        src = os.path.join(temp_dir, "Makefile")
        data = json.dumps({"paths": [src], "dest": os.path.join(temp_dir, "subdir")}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/move",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["ok"] is False
        assert len(resp["errors"]) == 1
        assert "already exists" in resp["errors"][0]


# --- /api/copy ---

class TestCopy:
    def test_copy_file(self, test_server, temp_dir):
        src = os.path.join(temp_dir, "Makefile")
        dest = os.path.join(temp_dir, "subdir")
        data = json.dumps({"paths": [src], "dest": dest}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/copy",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["ok"] is True
        # Original still exists
        assert os.path.exists(src)
        # Copy exists
        assert os.path.exists(os.path.join(dest, "Makefile"))

    def test_copy_directory(self, test_server, temp_dir):
        # Create a dir with content to copy
        src_dir = os.path.join(temp_dir, ".hidden_dir")
        with open(os.path.join(src_dir, "inner.txt"), "w") as f:
            f.write("inner")
        dest = os.path.join(temp_dir, "subdir")
        data = json.dumps({"paths": [src_dir], "dest": dest}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/copy",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["ok"] is True
        assert os.path.exists(os.path.join(dest, ".hidden_dir", "inner.txt"))


# --- /api/mkdir ---

class TestMkdir:
    def test_create_folder(self, test_server, temp_dir):
        data = json.dumps({"dir": temp_dir, "name": "new_folder"}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/mkdir",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["ok"] is True
        assert resp["path"] == os.path.join(temp_dir, "new_folder")
        assert os.path.isdir(os.path.join(temp_dir, "new_folder"))

    def test_create_folder_conflict(self, test_server, temp_dir):
        """Creating a folder with an existing name should fail with 409."""
        data = json.dumps({"dir": temp_dir, "name": "subdir"}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/mkdir",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 409

    def test_create_folder_invalid_name(self, test_server, temp_dir):
        data = json.dumps({"dir": temp_dir, "name": "bad/name"}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/mkdir",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400

    def test_create_folder_bad_parent(self, test_server, temp_dir):
        data = json.dumps({"dir": os.path.join(temp_dir, "nonexistent"), "name": "x"}).encode()
        req = urllib.request.Request(
            f"{test_server}/api/mkdir",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400


# --- /api/volumes ---

class TestVolumes:
    def test_volumes(self, test_server):
        url = f"{test_server}/api/volumes"
        data = json.loads(urllib.request.urlopen(url).read())
        assert isinstance(data, list)
        # macOS should always have at least one volume
        assert len(data) > 0
        assert "name" in data[0]
        assert "path" in data[0]


# --- /api/open ---

class TestOpen:
    def test_open_file(self, test_server, temp_dir):
        filepath = os.path.join(temp_dir, "Makefile")
        url = f"{test_server}/api/open?path={urllib.parse.quote(filepath)}"
        resp = urllib.request.urlopen(url)
        data = json.loads(resp.read())
        assert data["ok"] is True

    def test_open_with_reveal(self, test_server, temp_dir):
        filepath = os.path.join(temp_dir, "Makefile")
        url = f"{test_server}/api/open?path={urllib.parse.quote(filepath)}&reveal=1"
        resp = urllib.request.urlopen(url)
        data = json.loads(resp.read())
        assert data["ok"] is True


# --- /api/file ---

class TestServeFile:
    def test_serve_file(self, test_server, temp_dir):
        filepath = os.path.join(temp_dir, "Makefile")
        url = f"{test_server}/api/file?path={urllib.parse.quote(filepath)}"
        resp = urllib.request.urlopen(url)
        content = resp.read().decode()
        assert "all:" in content

    def test_serve_nonexistent_file(self, test_server):
        url = f"{test_server}/api/file?path=/nonexistent_xyz"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url)
        assert exc_info.value.code == 404

    def test_range_request(self, test_server, temp_dir):
        """Range request should return 206 with partial content."""
        filepath = os.path.join(temp_dir, "Makefile")
        url = f"{test_server}/api/file?path={urllib.parse.quote(filepath)}"
        req = urllib.request.Request(url, headers={"Range": "bytes=0-3"})
        resp = urllib.request.urlopen(req)
        assert resp.status == 206
        content = resp.read()
        assert len(content) == 4
        assert content == b"all:"
        assert "Content-Range" in resp.headers

    def test_accept_ranges_header(self, test_server, temp_dir):
        """Normal file response should include Accept-Ranges header."""
        filepath = os.path.join(temp_dir, "Makefile")
        url = f"{test_server}/api/file?path={urllib.parse.quote(filepath)}"
        resp = urllib.request.urlopen(url)
        assert resp.headers.get("Accept-Ranges") == "bytes"


# --- /api/info ---

class TestInfo:
    def test_file_info(self, test_server, temp_dir):
        filepath = os.path.join(temp_dir, "file.txt")
        url = f"{test_server}/api/info?path={urllib.parse.quote(filepath)}"
        data = json.loads(urllib.request.urlopen(url).read())
        assert data["name"] == "file.txt"
        assert data["path"] == filepath
        assert data["size"] == 5
        assert data["is_dir"] is False
        assert "created" in data
        assert "modified" in data
        assert "permissions" in data
        assert "owner" in data

    def test_dir_info(self, test_server, temp_dir):
        url = f"{test_server}/api/info?path={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        assert data["is_dir"] is True
        assert "item_count" in data
        assert data["item_count"] > 0

    def test_symlink_info(self, test_server, temp_dir):
        filepath = os.path.join(temp_dir, "link.txt")
        url = f"{test_server}/api/info?path={urllib.parse.quote(filepath)}"
        data = json.loads(urllib.request.urlopen(url).read())
        assert data["is_symlink"] is True
        assert "symlink_target" in data

    def test_nonexistent_info(self, test_server):
        url = f"{test_server}/api/info?path=/nonexistent_xyz"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url)
        assert exc_info.value.code == 404


# --- CORS ---

class TestCORS:
    def test_no_cors_header_on_listing(self, test_server):
        url = f"{test_server}/api/ls?dir=~"
        resp = urllib.request.urlopen(url)
        assert resp.headers.get("Access-Control-Allow-Origin") is None

    def test_no_cors_header_on_file(self, test_server, temp_dir):
        filepath = os.path.join(temp_dir, "Makefile")
        url = f"{test_server}/api/file?path={urllib.parse.quote(filepath)}"
        resp = urllib.request.urlopen(url)
        assert resp.headers.get("Access-Control-Allow-Origin") is None


# --- BUNDLE_EXTS ---

class TestBundleExts:
    def test_bundle_exts_contains_app(self):
        assert ".app" in server.BUNDLE_EXTS

    def test_bundle_exts_contains_framework(self):
        assert ".framework" in server.BUNDLE_EXTS

    def test_bundle_exts_contains_xcodeproj(self):
        assert ".xcodeproj" in server.BUNDLE_EXTS

    def test_regular_dir_not_bundle(self, test_server, temp_dir):
        url = f"{test_server}/api/ls?dir={urllib.parse.quote(temp_dir)}"
        data = json.loads(urllib.request.urlopen(url).read())
        subdir = next(e for e in data["entries"] if e["name"] == "subdir")
        assert subdir["is_dir"] is True
        assert "is_bundle" not in subdir


# --- Serve HTML ---

class TestServeHtml:
    def test_root_returns_html(self, test_server):
        resp = urllib.request.urlopen(f"{test_server}/")
        content_type = resp.headers.get("Content-Type", "")
        assert "text/html" in content_type
        body = resp.read().decode()
        assert "<!DOCTYPE html>" in body


import urllib.parse
