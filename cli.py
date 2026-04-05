#!/usr/bin/env python3
"""finder-pane CLI — Finder-like file browser for macOS."""

import os
import sys

VERSION = "0.1.0"
DEFAULT_PORT = 8234

USAGE = f"""\
finder-pane {VERSION} — Finder-like file browser for macOS

Usage:
  finder-pane open [PATH]        Open PATH (default: cwd) in a cmux browser pane
  finder-pane start [PORT]       Start the server (default port: {DEFAULT_PORT})
  finder-pane status             Check if the server is running
  finder-pane install-skill      Install Claude Code skill
  finder-pane uninstall-skill    Remove Claude Code skill
  finder-pane version            Show version
  finder-pane help               Show this help
"""

SKILL_DIR = os.path.join(os.path.expanduser("~"), ".claude", "skills", "finder-pane")


def cmd_start(args):
    port = DEFAULT_PORT
    if args:
        try:
            port = int(args[0])
        except ValueError:
            print(f"Invalid port: {args[0]}", file=sys.stderr)
            sys.exit(1)

    server_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
    os.execvp(sys.executable, [sys.executable, server_py, str(port)])


def _is_server_running(port=DEFAULT_PORT):
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/volumes", timeout=2)
        return True
    except Exception:
        return False


def _start_server_background(port=DEFAULT_PORT):
    import subprocess
    server_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
    subprocess.Popen(
        [sys.executable, server_py, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for server to be ready
    import time
    for _ in range(20):
        time.sleep(0.25)
        if _is_server_running(port):
            return True
    return False


def cmd_open(args):
    path = os.path.abspath(args[0]) if args else os.getcwd()

    if not _is_server_running():
        print("Starting server...", file=sys.stderr)
        if not _start_server_background():
            print("Failed to start server", file=sys.stderr)
            sys.exit(1)

    import subprocess
    url = f"http://localhost:{DEFAULT_PORT}{path}"
    subprocess.run(["cmux", "browser", "open", url])


def cmd_status(args):
    import urllib.request
    port = DEFAULT_PORT
    if args:
        try:
            port = int(args[0])
        except ValueError:
            print(f"Invalid port: {args[0]}", file=sys.stderr)
            sys.exit(1)
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/volumes", timeout=2)
        print(f"running on port {port}")
    except Exception:
        print("not running")
        sys.exit(1)


def cmd_install_skill():
    project_root = os.path.dirname(os.path.abspath(__file__))
    skill_source = os.path.join(project_root, "skill")

    if not os.path.isdir(skill_source):
        print(f"Skill directory not found: {skill_source}", file=sys.stderr)
        sys.exit(1)

    skills_parent = os.path.dirname(SKILL_DIR)
    os.makedirs(skills_parent, exist_ok=True)

    if os.path.islink(SKILL_DIR):
        existing_target = os.readlink(SKILL_DIR)
        if existing_target == skill_source:
            print(f"Skill already installed: {SKILL_DIR} -> {skill_source}")
            return
        os.remove(SKILL_DIR)
        print(f"Replaced existing symlink: {existing_target}")

    if os.path.exists(SKILL_DIR):
        print(f"Path already exists (not a symlink): {SKILL_DIR}", file=sys.stderr)
        print("Remove it manually if you want to reinstall.", file=sys.stderr)
        sys.exit(1)

    os.symlink(skill_source, SKILL_DIR)
    print(f"Installed: {SKILL_DIR} -> {skill_source}")


def cmd_uninstall_skill():
    if os.path.islink(SKILL_DIR):
        os.remove(SKILL_DIR)
        print(f"Removed: {SKILL_DIR}")
    elif os.path.exists(SKILL_DIR):
        print(f"Not a symlink, skipping: {SKILL_DIR}", file=sys.stderr)
        sys.exit(1)
    else:
        print("Skill not installed.")


def main():
    args = sys.argv[1:]

    if not args or args[0] == "help":
        print(USAGE)
        sys.exit(0)

    cmd = args[0]

    if cmd == "open":
        cmd_open(args[1:])
    elif cmd == "start":
        cmd_start(args[1:])
    elif cmd == "status":
        cmd_status(args[1:])
    elif cmd == "install-skill":
        cmd_install_skill()
    elif cmd == "uninstall-skill":
        cmd_uninstall_skill()
    elif cmd == "version":
        print(f"finder-pane {VERSION}")
    else:
        print(f"Unknown command: {cmd}\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
