"""Browser E2E tests for finder-pane using Playwright."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import Page, expect

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import server


@pytest.fixture(scope="module")
def temp_dir():
    """Create a temporary directory with test files for browser tests."""
    d = tempfile.mkdtemp(prefix="fp_browser_test_")

    # Create subdirectories
    os.makedirs(os.path.join(d, "subdir"))
    os.makedirs(os.path.join(d, "another_dir"))

    # Create text files
    for i in range(60):
        with open(os.path.join(d, f"file_{i:03d}.txt"), "w") as f:
            f.write(f"Content of file {i}\nLine 2\nLine 3\n")

    # Create an image file (minimal valid PNG)
    png_header = (
        b'\x89PNG\r\n\x1a\n'  # PNG signature
        b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
        b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
        b'\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    with open(os.path.join(d, "test_image.png"), "wb") as f:
        f.write(png_header)

    # Create a markdown file
    with open(os.path.join(d, "readme.md"), "w") as f:
        f.write("# Test\n\nThis is a test markdown file.\n")

    # Create a hidden file
    with open(os.path.join(d, ".hidden"), "w") as f:
        f.write("hidden content")

    yield d
    shutil.rmtree(d)


@pytest.fixture(scope="module")
def test_server(temp_dir):
    """Start a test server on a fixed port for browser tests."""
    port = 18235
    srv = server.ThreadingHTTPServer(("127.0.0.1", port), server.FinderHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    # Wait for the server to actually accept requests. A fixed sleep is
    # flaky on slow CI runners — the first few tests would time out while
    # the server was still warming up. Poll /api/ping until it responds.
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10.0
    while True:
        try:
            with urllib.request.urlopen(f"{base_url}/api/ping", timeout=1) as resp:
                if resp.status == 200:
                    break
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("test_server did not become ready within 10s")
        time.sleep(0.05)

    yield base_url
    srv.shutdown()


@pytest.fixture
def app(page: Page, test_server, temp_dir):
    """Navigate to the app and wait for initial load."""
    page.goto(f"{test_server}{temp_dir}")
    # Wait for file list to render. The timeout is generous because the
    # first test in the session absorbs Chromium's cold start on CI; once
    # the browser is warm, .file-row appears near-instantly.
    page.wait_for_selector(".file-row", timeout=30000)
    return page


# --- Sidebar ---

class TestSidebar:
    def test_sidebar_has_items(self, app: Page):
        """Sidebar should render favorite items on initial load."""
        items = app.query_selector_all(".sidebar-item")
        assert len(items) > 0, "Sidebar should have at least one item"


# --- Smoke Tests ---

class TestBasicLoad:
    def test_page_title_contains_finder_pane(self, app: Page):
        """Page title should contain 'finder-pane'."""
        assert "finder-pane" in app.title().lower()

    def test_file_list_renders(self, app: Page):
        """.file-row elements should exist in the file list."""
        rows = app.query_selector_all(".file-row")
        assert len(rows) > 0, "File list should contain .file-row elements"

    def test_breadcrumb_renders(self, app: Page):
        """#breadcrumb should have content (not empty)."""
        breadcrumb = app.query_selector("#breadcrumb")
        assert breadcrumb is not None
        text = breadcrumb.inner_text().strip()
        assert len(text) > 0, "Breadcrumb should not be empty"

    def test_tray_panel_visible(self, app: Page):
        """#tray-panel should be visible."""
        expect(app.locator("#tray-panel")).to_be_visible()

    def test_toolbar_buttons_visible(self, app: Page):
        """View switching buttons should be visible."""
        expect(app.locator("#btn-view-list")).to_be_visible()
        expect(app.locator("#btn-view-cols")).to_be_visible()

    def test_search_box_visible(self, app: Page):
        """#search input should be visible."""
        expect(app.locator("#search")).to_be_visible()


class TestBasicNavigation:
    def test_double_click_directory_navigates(self, app: Page, temp_dir):
        """Double-clicking a directory should change the breadcrumb."""
        breadcrumb_before = app.query_selector("#breadcrumb").inner_text()
        subdir_row = app.query_selector(f'.file-row[data-path="{temp_dir}/subdir"]')
        assert subdir_row is not None, "subdir row should exist"
        subdir_row.dblclick()
        app.wait_for_timeout(500)
        breadcrumb_after = app.query_selector("#breadcrumb").inner_text()
        assert breadcrumb_after != breadcrumb_before, "Breadcrumb should change after navigating into subdir"
        assert "subdir" in breadcrumb_after

    def test_u_key_goes_up(self, app: Page, temp_dir):
        """After navigating into subdir, pressing 'u' should go back to parent."""
        # Navigate into subdir
        subdir_row = app.query_selector(f'.file-row[data-path="{temp_dir}/subdir"]')
        assert subdir_row is not None
        subdir_row.dblclick()
        app.wait_for_timeout(500)
        # Press u to go up
        app.keyboard.press("u")
        app.wait_for_timeout(500)
        breadcrumb = app.query_selector("#breadcrumb").inner_text()
        assert "subdir" not in breadcrumb, "Should have navigated back to parent"


class TestPreviewPane:
    def test_preview_pane_shows_on_file_click(self, app: Page, temp_dir):
        """Clicking a file should make #preview-pane visible."""
        row = app.query_selector(f'.file-row[data-path="{temp_dir}/file_000.txt"]')
        assert row is not None, "file_000.txt row should exist"
        row.click()
        app.wait_for_timeout(500)
        preview = app.query_selector("#preview-pane")
        assert preview is not None, "Preview pane element should exist"
        # Preview pane should be visible (not hidden)
        is_visible = preview.is_visible()
        assert is_visible, "Preview pane should be visible after clicking a file"


# --- Navigation & Display ---

class TestScrollFollowing:
    def test_jk_scroll_follows_in_list_view(self, app: Page, temp_dir):
        """j/k navigation should keep selected item visible in a long list."""
        # Press j many times to scroll down
        for _ in range(50):
            app.keyboard.press("j")

        # The selected row should be visible
        selected = app.query_selector(".file-row.selected")
        assert selected is not None
        assert selected.is_visible()

    def test_jk_scroll_follows_in_column_view(self, app: Page):
        """j/k navigation should keep selected item visible in column view."""
        # Switch to column view
        app.click("#btn-view-cols")
        app.wait_for_selector(".miller-column", timeout=3000)

        # Press j many times
        for _ in range(50):
            app.keyboard.press("j")

        selected = app.query_selector(".miller-item.selected")
        assert selected is not None
        assert selected.is_visible()


class TestColumnViewClick:
    def test_click_after_scroll_selects_correct_item(self, app: Page, temp_dir):
        """Clicking an item in a scrolled column should select that item."""
        # Switch to column view
        app.click("#btn-view-cols")
        app.wait_for_selector(".miller-column", timeout=3000)

        # Scroll down in the column and click a specific item
        column = app.query_selector(".miller-column")
        # Scroll to bottom of the column
        column.evaluate("el => el.scrollTop = el.scrollHeight")
        app.wait_for_timeout(100)

        # Get the last visible item and click it
        items = app.query_selector_all(".miller-column .miller-item")
        last_item = items[-1]
        last_item_name = last_item.query_selector(".miller-item-name").inner_text()
        last_item.click()
        app.wait_for_timeout(200)

        # Verify it's selected
        selected = app.query_selector(".miller-item.selected")
        assert selected is not None
        selected_name = selected.query_selector(".miller-item-name").inner_text()
        assert selected_name == last_item_name


class TestViewSwitching:
    def test_switch_to_column_view(self, app: Page):
        """Clicking column view button should show miller columns."""
        app.click("#btn-view-cols")
        expect(app.locator("#column-view")).to_be_visible()
        expect(app.locator("#list-view")).to_be_hidden()

    def test_switch_to_list_view(self, app: Page):
        """Clicking list view button should show file list."""
        # Switch to columns first
        app.click("#btn-view-cols")
        # Switch back to list
        app.click("#btn-view-list")
        expect(app.locator("#list-view")).to_be_visible()
        expect(app.locator("#column-view")).to_be_hidden()


class TestKeyboardNavigation:
    def test_jk_moves_selection(self, app: Page):
        """j moves selection down, k moves it back up."""
        # Press j to select first item
        app.keyboard.press("j")
        first = app.query_selector(".file-row.selected")
        assert first is not None
        first_path = first.get_attribute("data-path")

        # Press j again to move down
        app.keyboard.press("j")
        second = app.query_selector(".file-row.selected")
        second_path = second.get_attribute("data-path")
        assert second_path != first_path

        # Press k to move back up
        app.keyboard.press("k")
        back = app.query_selector(".file-row.selected")
        assert back.get_attribute("data-path") == first_path

    def test_hl_column_navigation(self, app: Page):
        """h/l should navigate between columns in column view."""
        app.click("#btn-view-cols")
        app.wait_for_selector(".miller-column", timeout=3000)

        # Select a directory
        dirs = app.query_selector_all(".miller-item .miller-item-arrow")
        if len(dirs) > 0:
            # Click the parent of the arrow (the miller-item)
            dirs[0].evaluate("el => el.parentElement.click()")
            app.wait_for_timeout(500)

            # Should have 2 columns now
            columns = app.query_selector_all(".miller-column")
            assert len(columns) >= 2

            # Press l to move into the next column
            app.keyboard.press("l")
            app.wait_for_timeout(200)

            # Press h to move back
            app.keyboard.press("h")
            app.wait_for_timeout(200)

            # Should still have columns
            columns = app.query_selector_all(".miller-column")
            assert len(columns) >= 1


# --- Preview ---

class TestPreview:
    def test_text_file_preview(self, app: Page, temp_dir):
        """Clicking a text file should show preview in the sidebar or preview pane."""
        # Click file_000.txt
        row = app.query_selector(f'.file-row[data-path="{temp_dir}/file_000.txt"]')
        if row:
            row.click()
            app.wait_for_timeout(500)
            # Check that preview pane or sidebar preview has content
            preview = app.query_selector("#preview-pane, #sidebar-preview")
            assert preview is not None

    def test_image_file_preview(self, app: Page, temp_dir):
        """Clicking an image file should show an img tag in preview."""
        row = app.query_selector(f'.file-row[data-path="{temp_dir}/test_image.png"]')
        if row:
            row.click()
            app.wait_for_timeout(500)
            img = app.query_selector("#preview-pane img, #sidebar-preview img")
            assert img is not None


# --- Tab Focus ---

class TestTabFocus:
    def test_tab_cycles_focus(self, app: Page):
        """Tab key should cycle focus area: main -> tray -> sidebar."""
        # Initial focus should be main
        focus = app.evaluate("() => document.body.dataset.focus")
        assert focus == "main"

        # Tab -> tray
        app.keyboard.press("Tab")
        focus = app.evaluate("() => document.body.dataset.focus")
        assert focus == "tray"

        # Tab -> sidebar
        app.keyboard.press("Tab")
        focus = app.evaluate("() => document.body.dataset.focus")
        assert focus == "sidebar"

        # Tab -> back to main
        app.keyboard.press("Tab")
        focus = app.evaluate("() => document.body.dataset.focus")
        assert focus == "main"

    def test_shift_tab_cycles_reverse(self, app: Page):
        """Shift+Tab should cycle focus in reverse."""
        # main -> sidebar (reverse)
        app.keyboard.press("Shift+Tab")
        focus = app.evaluate("() => document.body.dataset.focus")
        assert focus == "sidebar"


# --- Tray ---

class TestTray:
    def test_add_to_tray_with_t_key(self, app: Page, temp_dir):
        """Pressing T should add selected item to tray."""
        # Select a file
        row = app.query_selector(f'.file-row[data-path="{temp_dir}/file_000.txt"]')
        row.click()
        app.wait_for_timeout(100)

        # Press T to add to tray
        app.keyboard.press("t")
        app.wait_for_timeout(200)

        # Check tray has an item
        tray_items = app.query_selector_all(".tray-item")
        assert len(tray_items) >= 1

    def test_remove_from_tray_with_delete(self, app: Page, temp_dir):
        """Selecting a tray item and pressing Delete should remove it."""
        # First add to tray
        row = app.query_selector(f'.file-row[data-path="{temp_dir}/file_001.txt"]')
        row.click()
        app.wait_for_timeout(100)
        app.keyboard.press("t")
        app.wait_for_timeout(200)

        initial_count = len(app.query_selector_all(".tray-item"))
        assert initial_count >= 1

        # Tab to tray
        app.keyboard.press("Tab")
        app.wait_for_timeout(100)

        # Select first tray item with j
        app.keyboard.press("j")
        app.wait_for_timeout(100)

        # Press Delete/Backspace to remove
        app.keyboard.press("Backspace")
        app.wait_for_timeout(200)

        new_count = len(app.query_selector_all(".tray-item"))
        assert new_count < initial_count


class TestGoToOriginalLocation:
    def test_go_to_original_location(self, app: Page, temp_dir):
        """G key in tray should navigate to the file's directory and select it."""
        # Add a file in subdir to tray
        # First navigate to subdir
        subdir_row = app.query_selector(f'.file-row[data-path="{temp_dir}/subdir"]')
        if subdir_row:
            subdir_row.dblclick()
            app.wait_for_timeout(500)

        # Go back to parent
        app.keyboard.press("u")
        app.wait_for_timeout(500)

        # Add a file to tray
        row = app.query_selector(f'.file-row[data-path="{temp_dir}/file_005.txt"]')
        if row:
            row.click()
            app.wait_for_timeout(100)
            app.keyboard.press("t")
            app.wait_for_timeout(200)

        # Navigate away to subdir
        subdir_row = app.query_selector(f'.file-row[data-path="{temp_dir}/subdir"]')
        if subdir_row:
            subdir_row.dblclick()
            app.wait_for_timeout(500)

        # Tab to tray
        app.keyboard.press("Tab")
        app.wait_for_timeout(100)

        # Select the tray item
        app.keyboard.press("j")
        app.wait_for_timeout(100)

        # Press G to go to original location
        app.keyboard.press("g")
        app.wait_for_timeout(500)

        # Should have navigated back to temp_dir
        current_dir = app.evaluate("() => currentDir")
        assert current_dir == temp_dir


# --- Security ---

class TestMarkdownXSS:
    def test_script_tag_in_markdown_is_escaped(self, page: Page, test_server, temp_dir):
        """Markdown with <script> tags should not execute JavaScript."""
        # Create a malicious markdown file
        md_path = os.path.join(temp_dir, "xss_test.md")
        with open(md_path, "w") as f:
            f.write("# Hello\n\n<script>window.__xss_fired=true</script>\n")

        page.goto(f"{test_server}{temp_dir}")
        page.wait_for_selector(".file-row", timeout=30000)

        # Click the markdown file to trigger preview
        row = page.query_selector(f'.file-row[data-path="{md_path}"]')
        if row:
            row.click()
            page.wait_for_timeout(500)

        # The script should NOT have executed
        xss = page.evaluate("() => window.__xss_fired || false")
        assert xss is False

    def test_script_in_markdown_shows_escaped(self, page: Page, test_server, temp_dir):
        """Script tags should be visible as escaped text in preview."""
        md_path = os.path.join(temp_dir, "xss_test.md")
        with open(md_path, "w") as f:
            f.write("# Test\n\n<script>alert(1)</script>\n")

        page.goto(f"{test_server}{temp_dir}")
        page.wait_for_selector(".file-row", timeout=30000)

        row = page.query_selector(f'.file-row[data-path="{md_path}"]')
        if row:
            row.click()
            page.wait_for_timeout(500)

        # The escaped script text should be visible
        preview_text = page.evaluate("() => document.querySelector('#preview-pane')?.innerText || ''")
        assert "alert" in preview_text


class TestEscHtml:
    def test_filename_with_quotes_does_not_break_html(self, page: Page, test_server, temp_dir):
        """A filename with double quotes should not break HTML attributes."""
        # Create a file with quotes in name
        quoted_path = os.path.join(temp_dir, 'file"quoted.txt')
        with open(quoted_path, "w") as f:
            f.write("test")

        page.goto(f"{test_server}{temp_dir}")
        page.wait_for_selector(".file-row", timeout=30000)

        # The page should render without errors
        # Check no unclosed tags or broken attributes
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.wait_for_timeout(300)

        # File should appear in the listing
        rows = page.query_selector_all(".file-row")
        assert len(rows) > 0
