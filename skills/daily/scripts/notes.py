#!/usr/bin/env python3
"""Recordings half of /daily: find new recordings, transcribe them, hand off to the model.

Flow: scan a source folder (phone voice-memo sync folder) for audio files →
skip any recording a note already cites in its `source:` frontmatter →
get a transcript for the rest (the phone's own transcript when there is one,
else Whisper; cached under <out>/transcripts/) → print a JSON manifest. The
model then reads each transcript and writes the note.

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
DEFAULT_OUT = Path.home() / "Daily"
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


SETTING_KEYS = ("DAILY_DIR", "DAILY_RECORDINGS", "DAILY_KAKAO", "DAILY_SCREENSHOTS", "DAILY_LANGUAGE")
LEGACY_KEYS = {
    "VOICE_NOTES_DIR": "DAILY_DIR",
    "VOICE_NOTES_SOURCE": "DAILY_RECORDINGS",
    "VOICE_NOTES_LANGUAGE": "DAILY_LANGUAGE",
}


def split_paths(value: str | None) -> list[Path]:
    return [expand(p) for p in (value or "").split(os.pathsep) if p.strip()]


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
    for key in (*SETTING_KEYS, *LEGACY_KEYS):
        if os.environ.get(key):
            values[key] = os.environ[key]
    # Pre-/daily names still work.
    for legacy, key in LEGACY_KEYS.items():
        if values.get(legacy) and not values.get(key):
            values[key] = values[legacy]
    return values


def expand(path: str) -> Path:
    return Path(os.path.expandvars(path)).expanduser()


def resolve_sources(cli: list[str], settings: dict[str, str]) -> tuple[list[Path], str]:
    if cli:
        return [expand(p) for p in cli], "argument"
    if settings.get("DAILY_RECORDINGS"):
        return split_paths(settings["DAILY_RECORDINGS"]), "config"
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


# --- Built-in phone transcripts -------------------------------------------
# iOS 18+ Voice Memos embeds its on-device transcript in the .m4a as a custom
# `tsrp` atom (seen at moov/trak/udta and moov/trak/mdia/udta). The payload is
# JSON: {"attributedString": {"runs": ["word", 0, "word", 1, ...],
# "attributeTable": [{"timeRange": [start, end]}, ...]}, "locale": {...}}.
# Using it skips the Whisper upload entirely: free, offline, and the text
# the user already saw on their phone.

MP4_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"udta", b"edts"}
BUILTIN_SUFFIXES = {".m4a", ".qta", ".mp4", ".caf"}


def _iter_atoms(buf: bytes, start: int = 0, end: int | None = None):
    end = len(buf) if end is None else end
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(buf[pos:pos + 4], "big")
        kind = buf[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = int.from_bytes(buf[pos + 8:pos + 16], "big")
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def _find_tsrp(buf: bytes, start: int = 0, end: int | None = None) -> bytes | None:
    for kind, body, stop in _iter_atoms(buf, start, end):
        if kind == b"tsrp":
            return buf[body:stop]
        if kind in MP4_CONTAINERS:
            found = _find_tsrp(buf, body, stop)
            if found is not None:
                return found
    return None


def _read_moov(path: Path) -> bytes | None:
    """Return the moov atom's body, seeking past mdat so large files stay cheap."""
    with path.open("rb") as fh:
        while True:
            header = fh.read(8)
            if len(header) < 8:
                return None
            size = int.from_bytes(header[:4], "big")
            kind = header[4:]
            header_len = 8
            if size == 1:
                size = int.from_bytes(fh.read(8), "big")
                header_len = 16
            if kind == b"moov":
                return fh.read() if size == 0 else fh.read(size - header_len)
            if size == 0:
                return None
            if size < header_len:
                return None
            fh.seek(size - header_len, 1)


def apple_transcript(path: Path) -> tuple[list[dict], str | None] | None:
    """Segments from an embedded Voice Memos transcript, or None if absent."""
    if path.suffix.lower() not in BUILTIN_SUFFIXES:
        return None
    try:
        moov = _read_moov(path)
    except OSError:
        return None
    payload = _find_tsrp(moov) if moov else None
    if not payload:
        return None
    brace = payload.find(b"{")
    if brace < 0:
        return None
    try:
        data = json.loads(payload[brace:].rstrip(b"\0").decode("utf-8", errors="replace"))
        runs = data["attributedString"]["runs"]
        table = data["attributedString"].get("attributeTable") or []
    except (ValueError, KeyError, TypeError):
        return None
    locale = (data.get("locale") or {}).get("identifier")

    words: list[tuple[str, float, float]] = []
    text = ""
    for run in runs:
        if isinstance(run, str):
            text += run
        elif isinstance(run, int) and text:
            time_range = table[run].get("timeRange") if 0 <= run < len(table) else None
            if time_range and len(time_range) == 2:
                words.append((text, float(time_range[0]), float(time_range[1])))
            elif words:
                words[-1] = (words[-1][0] + text, words[-1][1], words[-1][2])
            text = ""
    if text:
        if words:
            words[-1] = (words[-1][0] + text, words[-1][1], words[-1][2])
        else:
            words.append((text, 0.0, 0.0))
    segments = group_words(words)
    return (segments, locale) if segments else None


def group_words(words: list[tuple[str, float, float]], max_len: float = 30.0, pause: float = 1.5) -> list[dict]:
    """Merge word-level timings into sentence-ish lines.

    Breaks after sentence-final punctuation, on a pause, or when a line
    passes max_len seconds, so the transcript reads like Whisper's output.
    """
    segments: list[dict] = []
    current: dict | None = None
    for text, start, end in words:
        if current and (start - current["end"] > pause or start - current["start"] > max_len):
            segments.append(current)
            current = None
        if current is None:
            current = {"start": start, "end": end, "text": text}
        else:
            current["text"] += text
            current["end"] = max(current["end"], end)
        if re.search(r"[.!?。？！]\s*$", text):
            segments.append(current)
            current = None
    if current:
        segments.append(current)
    out = []
    for seg in segments:
        seg["text"] = re.sub(r"\s+", " ", seg["text"]).strip()
        if seg["text"]:
            out.append({"start": round(seg["start"], 2), "end": round(seg["end"], 2), "text": seg["text"]})
    return out


def sidecar_transcript(path: Path) -> str | None:
    """Text exported next to the recording (e.g. Galaxy Transcript assist → .txt)."""
    for candidate in (path.with_suffix(".txt"), path.with_name(path.name + ".txt")):
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8-sig", errors="replace").strip()
            except OSError:
                continue
            if text:
                return text + "\n"
    return None


def builtin_transcript(path: Path) -> tuple[str, str] | None:
    """(transcript text, origin) from the phone's own transcription, if any."""
    text = sidecar_transcript(path)
    if text:
        return text, "sidecar"
    found = apple_transcript(path)
    if found:
        segments, locale = found
        return transcript_text(segments), f"apple-voice-memos{f' ({locale})' if locale else ''}"
    return None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Transcribe new voice recordings for /daily.")
    ap.add_argument("sources", nargs="*", help="Audio files or folders (default: DAILY_RECORDINGS or Mac Voice Memos)")
    ap.add_argument("--out", help="Output root (default: DAILY_DIR or ~/Daily)")
    ap.add_argument("--since", help="Only recordings on/after YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Max recordings to transcribe this run (default {DEFAULT_LIMIT}, 0 = no limit)")
    ap.add_argument("--language", help="Whisper language hint, e.g. ko (default: DAILY_LANGUAGE or auto-detect)")
    ap.add_argument("--whisper", choices=["groq", "openai"], help="Force a Whisper backend")
    ap.add_argument("--list", action="store_true", help="Only list pending items; change nothing")
    ap.add_argument("--redo", action="store_true", help="Include recordings that already have a note")
    ap.add_argument("--force-whisper", action="store_true", help="Ignore phone transcripts and cached ones; re-transcribe with Whisper")
    return ap


def output_dir(args: argparse.Namespace, settings: dict[str, str]) -> Path:
    return expand(args.out or settings.get("DAILY_DIR") or str(DEFAULT_OUT))


def main() -> int:
    args = build_parser().parse_args()
    report, code = run(args, read_settings())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


def run(args: argparse.Namespace, settings: dict[str, str]) -> tuple[dict, int]:
    out_dir = output_dir(args, settings)
    language = args.language or settings.get("DAILY_LANGUAGE") or None
    sources, source_origin = resolve_sources(args.sources, settings)
    since = date.fromisoformat(args.since) if args.since else None

    report: dict = {
        "output_dir": str(out_dir),
        "output_dir_configured": bool(args.out or settings.get("DAILY_DIR")),
        "sources": [str(s) for s in sources],
        "source_origin": source_origin,
        "language": language,
        "pending": [],
        "remaining": 0,
        "already_done": 0,
        "errors": [],
    }

    if not sources:
        report["errors"].append({"error": "no_source", "detail": "No source given, DAILY_RECORDINGS unset, and no Mac Voice Memos folder found."})
        return report, 1

    try:
        files = find_audio(sources)
    except PermissionError as exc:
        report["errors"].append({"error": "permission_denied", "detail": str(exc)})
        return report, 1
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
    backend, api_key = args.whisper, None
    key_missing = False

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
            "note_dir": str(out_dir / "recordings" / f"{when:%Y-%m}"),
            "note_prefix": f"{when:%Y-%m-%d_%H%M}",
        }
        builtin = None if args.force_whisper else builtin_transcript(path)
        if args.list:
            item["transcript_source"] = builtin[1] if builtin else "whisper"
            report["pending"].append(item)
            continue

        origin_path = transcript_path.with_suffix(".source")
        if transcript_path.exists() and not args.force_whisper:
            origin = origin_path.read_text(encoding="utf-8").strip() if origin_path.exists() else "whisper"
        elif builtin:
            text, origin = builtin
            transcripts.mkdir(parents=True, exist_ok=True)
            transcript_path.write_text(text, encoding="utf-8")
        else:
            if api_key is None and not key_missing:
                backend, api_key = whisper.load_api_key(args.whisper)
                if not api_key:
                    key_missing = True
                    report["errors"].append({"error": "no_api_key", "detail": "Set GROQ_API_KEY or OPENAI_API_KEY in ~/.config/watch/.env"})
            if key_missing:
                report["errors"].append({"error": "needs_whisper", "source": path.name})
                continue
            print(f"[daily] transcribing {path.name} ({fmt_ts(duration)})…", file=sys.stderr)
            try:
                with tempfile.TemporaryDirectory(prefix="daily-") as tmp:
                    segments, backend = whisper.transcribe_video(
                        str(path), Path(tmp) / "audio.mp3", backend=backend, api_key=api_key, language=language,
                    )
            except SystemExit as exc:
                report["errors"].append({"error": "transcribe_failed", "source": path.name, "detail": str(exc)})
                continue
            origin = f"whisper ({backend})"
            transcripts.mkdir(parents=True, exist_ok=True)
            # An empty transcript is still written (and the item still returned)
            # so the model files a stub note and the silence isn't re-billed.
            transcript_path.write_text(transcript_text(clean_segments(segments)), encoding="utf-8")
        origin_path.write_text(origin + "\n", encoding="utf-8")
        item["transcript_source"] = origin
        item["empty"] = transcript_path.stat().st_size == 0
        report["pending"].append(item)

    return report, (1 if key_missing and not report["pending"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
