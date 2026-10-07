#!/usr/bin/env python3
"""/voice-notes entry point: find new recordings, transcribe them, hand off to the model.

Flow: scan a source folder (phone voice-memo sync folder) for audio files →
skip any recording a note already cites in its `source:` frontmatter →
transcribe the rest via Whisper (cached under <out>/transcripts/) → print a
JSON manifest. The model then reads each transcript and writes the note.

Pure stdlib + ffmpeg. Whisper key comes from the same place /watch reads it
(GROQ_API_KEY / OPENAI_API_KEY in the env or ~/.config/watch/.env).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import whisper  # noqa: E402


CONFIG_FILE = Path.home() / ".config" / "watch" / ".env"
DEFAULT_OUT = Path.home() / "VoiceNotes"
DEFAULT_LIMIT = 5

AUDIO_EXTS = {
    ".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus", ".amr", ".3gp",
    ".flac", ".webm", ".qta", ".caf", ".mp4",
}

# Where Apple Voice Memos keeps iCloud-synced recordings on a Mac (newest first).
MAC_VOICE_MEMOS_DIRS = [
    Path.home() / "Library" / "Group Containers" / "group.com.apple.VoiceMemos.shared" / "Recordings",
    Path.home() / "Library" / "Application Support" / "com.apple.voicememos" / "Recordings",
]

# Whisper's well-known hallucinations on silence / noise (YouTube-subtitle
# leftovers in its training data). Dropped only on an exact whole-segment match.
HALLUCINATIONS = {
    "시청해주셔서 감사합니다",
    "시청해 주셔서 감사합니다",
    "구독과 좋아요 부탁드립니다",
    "구독과 좋아요 알림설정 부탁드립니다",
    "다음 영상에서 만나요",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
}

# Phone recorders that encode the start time in the filename, e.g. iPhone
# "20261007 093015-1A2B3C4D.m4a", Samsung "음성 261007_093015.m4a".
FILENAME_TIME = re.compile(r"(?<!\d)(\d{8}|\d{6})[ _-](\d{6})(?!\d)")


def read_settings(path: Path | None = None) -> dict[str, str]:
    path = path or CONFIG_FILE
    values: dict[str, str] = {}
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, _, value = raw.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            values[key.strip()] = value
    for key in ("VOICE_NOTES_SOURCE", "VOICE_NOTES_DIR", "VOICE_NOTES_LANGUAGE"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def expand(path: str) -> Path:
    return Path(os.path.expandvars(path)).expanduser()


def resolve_sources(cli: list[str], settings: dict[str, str]) -> tuple[list[Path], str]:
    if cli:
        return [expand(p) for p in cli], "argument"
    if settings.get("VOICE_NOTES_SOURCE"):
        return [expand(p) for p in settings["VOICE_NOTES_SOURCE"].split(os.pathsep) if p], "config"
    found = [d for d in MAC_VOICE_MEMOS_DIRS if d.is_dir()]
    if found:
        return found[:1], "mac-voice-memos"
    return [], "none"


def time_from_filename(name: str) -> datetime | None:
    match = FILENAME_TIME.search(name)
    if not match:
        return None
    day, clock = match.groups()
    fmt = "%Y%m%d%H%M%S" if len(day) == 8 else "%y%m%d%H%M%S"
    try:
        parsed = datetime.strptime(day + clock, fmt)
    except ValueError:
        return None
    return parsed if 2000 <= parsed.year <= 2100 else None


def probe(path: Path) -> dict:
    if shutil.which("ffprobe") is None:
        return {}
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout or "{}").get("format", {})
    except json.JSONDecodeError:
        return {}


def recorded_at(path: Path, fmt: dict) -> datetime:
    """Best guess at when the recording started, in local time.

    Container creation_time (set by iPhone/Android recorders) beats the
    filename, which beats mtime (sync tools often rewrite mtime).
    """
    tag = (fmt.get("tags") or {}).get("creation_time")
    if tag:
        try:
            parsed = datetime.fromisoformat(tag.replace("Z", "+00:00"))
            if parsed.year > 1971:
                return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            pass
    return time_from_filename(path.name) or datetime.fromtimestamp(path.stat().st_mtime)


def find_audio(sources: list[Path]) -> list[Path]:
    files: list[Path] = []
    for src in sources:
        if src.is_file():
            files.append(src)
            continue
        for path in src.rglob("*"):
            if any(part.startswith(".") for part in path.relative_to(src).parts):
                continue
            if path.suffix.lower() in AUDIO_EXTS and path.is_file():
                files.append(path)
    return files


def done_sources(out_dir: Path) -> set[str]:
    """Filenames already cited by a note's `source:` frontmatter line."""
    done: set[str] = set()
    if not out_dir.is_dir():
        return done
    for note in out_dir.rglob("*.md"):
        try:
            head = note.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            continue
        if not head.startswith("---"):
            continue
        front = head.split("\n---", 1)[0]
        for line in front.splitlines():
            if line.startswith("source:"):
                done.add(line.partition(":")[2].strip().strip("\"'"))
    return done


def clean_segments(segments: list[dict]) -> list[dict]:
    """Drop known silence hallucinations and collapse repetition loops."""
    out: list[dict] = []
    for seg in segments:
        text = seg["text"].strip()
        key = re.sub(r"[\s.!?,~…]+$", "", text).lower()
        if key in HALLUCINATIONS:
            continue
        if out and out[-1]["text"] == text:
            out[-1]["end"] = seg["end"]
            continue
        out.append({**seg, "text": text})
    return out


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def transcript_text(segments: list[dict]) -> str:
    return "".join(f"[{fmt_ts(seg['start'])}] {seg['text']}\n" for seg in segments)


def transcript_stem(when: datetime, source: Path) -> str:
    digest = hashlib.sha1(source.name.encode("utf-8")).hexdigest()[:6]
    return f"{when:%Y-%m-%d_%H%M}_{digest}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Transcribe new voice recordings for /voice-notes.")
    ap.add_argument("sources", nargs="*", help="Audio files or folders (default: VOICE_NOTES_SOURCE or Mac Voice Memos)")
    ap.add_argument("--out", help="Notes folder (default: VOICE_NOTES_DIR or ~/VoiceNotes)")
    ap.add_argument("--since", help="Only recordings on/after YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Max recordings to transcribe this run (default {DEFAULT_LIMIT}, 0 = no limit)")
    ap.add_argument("--language", help="Whisper language hint, e.g. ko (default: VOICE_NOTES_LANGUAGE or auto-detect)")
    ap.add_argument("--whisper", choices=["groq", "openai"], help="Force a Whisper backend")
    ap.add_argument("--list", action="store_true", help="Only list pending recordings; transcribe nothing")
    ap.add_argument("--redo", action="store_true", help="Include recordings that already have a note")
    args = ap.parse_args()

    settings = read_settings()
    out_dir = expand(args.out or settings.get("VOICE_NOTES_DIR") or str(DEFAULT_OUT))
    language = args.language or settings.get("VOICE_NOTES_LANGUAGE") or None
    sources, source_origin = resolve_sources(args.sources, settings)
    since = date.fromisoformat(args.since) if args.since else None

    report: dict = {
        "output_dir": str(out_dir),
        "output_dir_configured": bool(args.out or settings.get("VOICE_NOTES_DIR")),
        "sources": [str(s) for s in sources],
        "source_origin": source_origin,
        "language": language,
        "pending": [],
        "remaining": 0,
        "already_done": 0,
        "errors": [],
    }

    if not sources:
        report["errors"].append({"error": "no_source", "detail": "No source given, VOICE_NOTES_SOURCE unset, and no Mac Voice Memos folder found."})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    try:
        files = find_audio(sources)
    except PermissionError as exc:
        report["errors"].append({"error": "permission_denied", "detail": str(exc)})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    missing = [str(s) for s in sources if not s.exists()]
    for path in missing:
        report["errors"].append({"error": "not_found", "source": path})

    done = set() if args.redo else done_sources(out_dir)
    candidates = []
    for path in files:
        if path.name in done:
            report["already_done"] += 1
            continue
        fmt = probe(path)
        when = recorded_at(path, fmt)
        if since and when.date() < since:
            continue
        candidates.append((when, path, float(fmt.get("duration") or 0.0)))
    candidates.sort()

    if args.limit > 0 and len(candidates) > args.limit:
        report["remaining"] = len(candidates) - args.limit
        candidates = candidates[: args.limit]

    transcripts = out_dir / "transcripts"
    backend = args.whisper
    api_key = None
    if candidates and not args.list:
        backend, api_key = whisper.load_api_key(args.whisper)
        if not api_key:
            report["errors"].append({"error": "no_api_key", "detail": "Set GROQ_API_KEY or OPENAI_API_KEY in ~/.config/watch/.env"})
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        transcripts.mkdir(parents=True, exist_ok=True)

    for when, path, duration in candidates:
        stem = transcript_stem(when, path)
        transcript_path = transcripts / f"{stem}.txt"
        item = {
            "source": path.name,
            "source_path": str(path),
            "recorded_at": when.isoformat(timespec="minutes"),
            "duration_seconds": round(duration),
            "duration": fmt_ts(duration),
            "transcript_path": str(transcript_path),
            "note_dir": str(out_dir / f"{when:%Y-%m}"),
            "note_prefix": f"{when:%Y-%m-%d_%H%M}",
        }
        if args.list:
            report["pending"].append(item)
            continue
        if not transcript_path.exists():
            print(f"[voice-notes] transcribing {path.name} ({fmt_ts(duration)})…", file=sys.stderr)
            try:
                with tempfile.TemporaryDirectory(prefix="voice-notes-") as tmp:
                    segments, _ = whisper.transcribe_video(
                        str(path), Path(tmp) / "audio.mp3", backend=backend, api_key=api_key, language=language,
                    )
            except SystemExit as exc:
                report["errors"].append({"error": "transcribe_failed", "source": path.name, "detail": str(exc)})
                continue
            # An empty transcript is still written (and the item still returned)
            # so the model files a stub note and the silence isn't re-billed.
            transcript_path.write_text(transcript_text(clean_segments(segments)), encoding="utf-8")
        item["empty"] = transcript_path.stat().st_size == 0
        report["pending"].append(item)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
