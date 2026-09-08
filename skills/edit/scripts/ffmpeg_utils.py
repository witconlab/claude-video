#!/usr/bin/env python3
"""Shared ffmpeg/ffprobe helpers for /edit.

Pure-stdlib. Every command that shells out to ffmpeg/ffprobe goes through
here so path resolution, error handling, and probing stay consistent across
operations.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REQUIRED_BINARIES = ["ffmpeg", "ffprobe"]


def require_binaries() -> None:
    missing = [b for b in REQUIRED_BINARIES if shutil.which(b) is None]
    if missing:
        raise SystemExit(
            f"Missing required binaries: {', '.join(missing)}. "
            f"Run: python3 {Path(__file__).with_name('setup.py')}"
        )


def run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess command (argv list, never shell=True) and raise with
    stderr on failure."""
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise SystemExit(f"ffmpeg command failed ({' '.join(cmd[:2])}…):\n{stderr[-2000:]}")
    return result


def resolve_input(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"Input file not found: {p}")
    if not p.is_file():
        raise SystemExit(f"Input path is not a file: {p}")
    return p


def default_output(input_path: Path, suffix: str, ext: str | None = None) -> Path:
    """Build a non-colliding output path next to the input file."""
    out_ext = ext if ext is not None else input_path.suffix
    candidate = input_path.with_name(f"{input_path.stem}_{suffix}{out_ext}")
    n = 2
    while candidate.exists():
        candidate = input_path.with_name(f"{input_path.stem}_{suffix}_{n}{out_ext}")
        n += 1
    return candidate


def resolve_output(input_path: Path, out_arg: str | None, suffix: str, ext: str | None = None) -> Path:
    if out_arg:
        p = Path(out_arg).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return default_output(input_path, suffix, ext)


def probe(path: Path) -> dict:
    require_binaries()
    result = run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)

    fps = None
    if v and v.get("avg_frame_rate") and v["avg_frame_rate"] != "0/0":
        num, _, den = v["avg_frame_rate"].partition("/")
        try:
            den_f = float(den) if den else 1.0
            fps = round(float(num) / den_f, 3) if den_f else None
        except ValueError:
            fps = None

    return {
        "duration_seconds": float(fmt.get("duration") or (v or {}).get("duration") or 0.0),
        "width": v.get("width") if v else None,
        "height": v.get("height") if v else None,
        "video_codec": v.get("codec_name") if v else None,
        "audio_codec": a.get("codec_name") if a else None,
        "fps": fps,
        "has_video": v is not None,
        "has_audio": a is not None,
        "size_bytes": int(fmt.get("size") or 0),
    }


def parse_time(value: str | float | int | None) -> float | None:
    """Parse SS, MM:SS, or HH:MM:SS (with optional .ms) into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    raise SystemExit(f"Cannot parse time value: {value!r} (expected SS, MM:SS, or HH:MM:SS)")


def format_time(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def quote_filter_value(raw: str) -> str:
    """Single-quote a value for use inside an ffmpeg filtergraph option
    (e.g. ``subtitles=filename=...``, ``drawtext=textfile=...``).

    Inside single quotes ffmpeg's filter parser stops treating ``:`` and
    ``,`` as option/argument separators, so this sidesteps Windows drive
    letters and punctuation in paths or watermark text. A literal ``'``
    inside the value has to close the quote, emit an escaped quote, and
    reopen it — the standard shell-style escape.
    """
    s = str(raw).replace("\\", "/")
    s = s.replace("'", "'\\''")
    return f"'{s}'"


def atempo_chain(factor: float) -> str:
    """Build an ffmpeg ``atempo`` filter chain for an arbitrary speed factor.

    A single ``atempo`` only accepts 0.5-2.0, so factors outside that range
    are split into a chain of filters (e.g. ``atempo=2.0,atempo=1.5`` for a
    3x speedup) that multiply out to the requested factor.
    """
    if factor <= 0:
        raise SystemExit("speed factor must be greater than zero")
    remaining = factor
    steps: list[float] = []
    while remaining > 2.0:
        steps.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        steps.append(0.5)
        remaining /= 0.5
    steps.append(remaining)
    return ",".join(f"atempo={s:.6f}" for s in steps)
