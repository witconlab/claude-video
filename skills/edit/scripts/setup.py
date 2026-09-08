#!/usr/bin/env python3
"""Setup / preflight for /edit.

Unlike /watch, /edit needs no API keys and no persistent config — it only
wraps ffmpeg/ffprobe, which either run locally or don't. So this is a much
smaller version of watch's setup.py: check for the two binaries, offer to
install them, done.

Modes:
  setup.py --check   Silent preflight. Exit 0 if ready, 2 if binaries missing.
  setup.py --json    Machine-readable status for Claude to parse.
  setup.py           Installer. Auto-installs deps where possible.
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys

REQUIRED_BINARIES = ["ffmpeg", "ffprobe"]


def _which(name: str) -> str | None:
    return shutil.which(name)


def _check_binaries() -> list[str]:
    return [b for b in REQUIRED_BINARIES if not _which(b)]


def _install_macos(missing: list[str]) -> tuple[bool, str]:
    if _which("brew") is None:
        return False, (
            "Homebrew is not installed. Install it from https://brew.sh, then re-run setup. "
            "Or install manually: `brew install ffmpeg`"
        )
    if "ffmpeg" not in missing and "ffprobe" not in missing:
        return True, "nothing to install"
    print("[setup] running: brew install ffmpeg", file=sys.stderr)
    result = subprocess.run(["brew", "install", "ffmpeg"])
    if result.returncode != 0:
        return False, f"brew install failed with exit code {result.returncode}"
    return True, "installed via brew: ffmpeg"


def _install_hint_linux() -> str:
    return "apt: `sudo apt install ffmpeg` or dnf: `sudo dnf install ffmpeg`"


def _install_hint_windows() -> str:
    return "winget: `winget install Gyan.FFmpeg`"


def _status() -> dict:
    missing = _check_binaries()
    return {
        "status": "ready" if not missing else "needs_install",
        "can_proceed": not missing,
        "missing_binaries": missing,
        "platform": platform.system(),
    }


def cmd_check() -> int:
    s = _status()
    if s["can_proceed"]:
        return 0
    sys.stderr.write(
        f"[edit] setup incomplete (missing binaries: {', '.join(s['missing_binaries'])}). "
        f"Run: python3 {__file__}\n"
    )
    sys.stderr.flush()
    return 2


def cmd_json() -> int:
    json.dump(_status(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_install() -> int:
    missing = _check_binaries()
    if not missing:
        print("[setup] ffmpeg/ffprobe already installed. /edit is ready.")
        return 0

    system = platform.system()
    if system == "Darwin":
        ok, msg = _install_macos(missing)
        print(f"[setup] {msg}", file=sys.stderr if not ok else sys.stdout)
        if not ok:
            return 2
        still_missing = _check_binaries()
        if still_missing:
            print(f"[setup] still missing after install: {', '.join(still_missing)}", file=sys.stderr)
            return 2
        print("[setup] ready. /edit is fully set up.")
        return 0
    if system == "Linux":
        print("[setup] ffmpeg missing on Linux — please install:", file=sys.stderr)
        print("  " + _install_hint_linux(), file=sys.stderr)
        return 2
    if system == "Windows":
        print("[setup] ffmpeg missing on Windows — please install:", file=sys.stderr)
        print("  " + _install_hint_windows(), file=sys.stderr)
        return 2
    print(f"[setup] unsupported platform ({system}) for auto-install. Install ffmpeg manually.", file=sys.stderr)
    return 2


def main() -> int:
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--check":
            return cmd_check()
        if arg == "--json":
            return cmd_json()
    return cmd_install()


if __name__ == "__main__":
    raise SystemExit(main())
