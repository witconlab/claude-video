#!/usr/bin/env python3
"""/edit entry point: dispatch one video-editing operation to ffmpeg.

Each subcommand does one thing (trim, merge, compress, ...), writes an
output file next to the input (or at --out), and prints a short markdown
report to stdout so Claude can relay the result. Pure-stdlib Python plus
subprocess calls to ffmpeg/ffprobe — no cloud calls, no API keys.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from ffmpeg_utils import (  # noqa: E402
    atempo_chain,
    default_output,
    format_time,
    human_size,
    parse_time,
    probe,
    quote_filter_value,
    require_binaries,
    resolve_input,
    resolve_output,
    run,
)

FFMPEG_BASE = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]

POSITIONS = {
    "tl": "10:10",
    "tr": "W-w-10:10",
    "bl": "10:H-h-10",
    "br": "W-w-10:H-h-10",
    "center": "(W-w)/2:(H-h)/2",
}


def _report(op: str, inp: Path, out: Path, notes: list[str]) -> None:
    before = probe(inp)
    after = probe(out) if out.exists() else None
    print(f"# edit: {op}")
    print()
    print(f"- **Input:** `{inp}` ({format_time(before['duration_seconds'])}, "
          f"{before['width']}x{before['height']}, {human_size(before['size_bytes'])})")
    if after:
        print(f"- **Output:** `{out}` ({format_time(after['duration_seconds'])}, "
              f"{after['width']}x{after['height']}, {human_size(after['size_bytes'])})")
    else:
        print(f"- **Output:** `{out}`")
    for note in notes:
        print(f"- {note}")
    print()


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def op_trim(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    start = parse_time(args.start) or 0.0
    end = parse_time(args.end)
    duration = parse_time(args.duration)
    if end is not None and duration is not None:
        raise SystemExit("pass either --end or --duration, not both")
    if end is not None:
        span = end - start
    elif duration is not None:
        span = duration
    else:
        span = None
    if span is not None and span <= 0:
        raise SystemExit("trim range must be positive (--end must be after --start)")

    out = resolve_output(inp, args.out, "trim")
    notes: list[str] = []

    def build(reencode: bool) -> list[str]:
        cmd = [*FFMPEG_BASE, "-ss", f"{start:.3f}", "-i", str(inp)]
        if span is not None:
            cmd += ["-t", f"{span:.3f}"]
        if reencode:
            cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c", "copy"]
        cmd.append(str(out))
        return cmd

    if args.exact:
        run(build(reencode=True))
    else:
        try:
            run(build(reencode=False))
        except SystemExit:
            notes.append("Stream copy failed (codec doesn't support cutting mid-GOP) — re-encoded instead.")
            run(build(reencode=True))
        else:
            notes.append(
                "Stream-copied for speed — cut points may snap to the nearest keyframe "
                "(off by up to ~1 GOP). Pass --exact for frame-accurate re-encoded cuts."
            )
    return out, notes


def op_concat(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    extra_inputs = [resolve_input(p) for p in args.inputs]
    all_inputs = [inp, *extra_inputs]
    out = resolve_output(inp, args.out, "concat")
    notes: list[str] = []

    # Fast path: concat demuxer + stream copy. Only safe when every input
    # shares codec/resolution/fps, which the demuxer itself will refuse
    # (non-zero exit) if not — so we just try it and fall back.
    with tempfile.TemporaryDirectory() as td:
        filelist = Path(td) / "concat.txt"
        filelist.write_text(
            "".join(f"file '{str(p).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for p in all_inputs),
            encoding="utf-8",
        )
        try:
            run([*FFMPEG_BASE, "-f", "concat", "-safe", "0", "-i", str(filelist), "-c", "copy", str(out)])
            notes.append("Stream-copied via the concat demuxer (inputs share compatible codecs/resolution).")
            return out, notes
        except SystemExit:
            if out.exists():
                out.unlink()

    # Fallback: normalize every input to a common resolution/fps and
    # re-encode. Uses the first input's resolution as the target unless
    # --width/--height override it.
    probes = [probe(p) for p in all_inputs]
    target_w = args.width or max(p["width"] or 0 for p in probes) or 1280
    target_h = args.height or max(p["height"] or 0 for p in probes) or 720
    if target_w % 2:
        target_w += 1
    if target_h % 2:
        target_h += 1
    all_have_audio = all(p["has_audio"] for p in probes)
    if not all_have_audio:
        notes.append("One or more inputs had no audio track — output audio was dropped.")

    cmd = [*FFMPEG_BASE]
    for p in all_inputs:
        cmd += ["-i", str(p)]
    filt_parts = []
    concat_inputs = []
    for i in range(len(all_inputs)):
        filt_parts.append(
            f"[{i}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]"
        )
        concat_inputs.append(f"[v{i}]")
        if all_have_audio:
            filt_parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
            concat_inputs.append(f"[a{i}]")
    n_streams = 2 if all_have_audio else 1
    filt = ";".join(filt_parts) + ";" + "".join(concat_inputs) + f"concat=n={len(all_inputs)}:v=1:a={1 if all_have_audio else 0}[outv]" + ("[outa]" if all_have_audio else "")
    cmd += ["-filter_complex", filt, "-map", "[outv]"]
    if all_have_audio:
        cmd += ["-map", "[outa]"]
    cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast"]
    if all_have_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd.append(str(out))
    run(cmd)
    notes.append(f"Re-encoded and normalized all inputs to {target_w}x{target_h} to merge mismatched sources.")
    return out, notes


def op_compress(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    out = resolve_output(inp, args.out, "compressed")
    notes: list[str] = []

    if args.target_size_mb:
        meta = probe(inp)
        duration = meta["duration_seconds"] or 1.0
        audio_kbps = 128 if meta["has_audio"] else 0
        total_kbps = (args.target_size_mb * 8192) / duration
        video_kbps = max(100, int(total_kbps - audio_kbps))
        notes.append(f"Two-pass encode targeting ~{args.target_size_mb}MB (video bitrate ~{video_kbps}kbps).")
        with tempfile.TemporaryDirectory() as td:
            passlog = str(Path(td) / "pass")
            null_device = "NUL" if sys.platform == "win32" else "/dev/null"
            run([
                *FFMPEG_BASE, "-i", str(inp),
                "-c:v", "libx264", "-b:v", f"{video_kbps}k", "-preset", "medium",
                "-pass", "1", "-passlogfile", passlog, "-an", "-f", "mp4", null_device,
            ])
            cmd = [*FFMPEG_BASE, "-i", str(inp), "-c:v", "libx264", "-b:v", f"{video_kbps}k", "-preset", "medium",
                   "-pass", "2", "-passlogfile", passlog]
            if meta["has_audio"]:
                cmd += ["-c:a", "aac", "-b:a", f"{audio_kbps}k"]
            else:
                cmd += ["-an"]
            cmd.append(str(out))
            run(cmd)
    else:
        crf = args.crf if args.crf is not None else 28
        preset = args.preset or "medium"
        cmd = [*FFMPEG_BASE, "-i", str(inp), "-c:v", "libx264", "-crf", str(crf), "-preset", preset]
        meta = probe(inp)
        if meta["has_audio"]:
            cmd += ["-c:a", "aac", "-b:a", "128k"]
        cmd.append(str(out))
        run(cmd)
        notes.append(f"CRF {crf} (lower = higher quality/larger file; 18-28 is typical), preset {preset}.")
    return out, notes


def op_speed(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    factor = args.factor
    if factor <= 0:
        raise SystemExit("--factor must be greater than zero")
    out = resolve_output(inp, args.out, f"{factor}x")
    meta = probe(inp)
    vf = f"setpts={1/factor:.6f}*PTS"
    cmd = [*FFMPEG_BASE, "-i", str(inp), "-vf", vf]
    notes = []
    if meta["has_audio"] and not args.no_audio_pitch_fix:
        cmd += ["-af", atempo_chain(factor)]
    elif meta["has_audio"]:
        cmd += ["-an"]
        notes.append("Audio dropped (--no-audio-pitch-fix without a tempo filter would desync it).")
    cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast"]
    if meta["has_audio"] and not args.no_audio_pitch_fix:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd.append(str(out))
    run(cmd)
    notes.append(f"Speed x{factor} (video + audio tempo, pitch-corrected).")
    return out, notes


def op_volume(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    meta = probe(inp)
    if not meta["has_audio"]:
        raise SystemExit("Input has no audio stream to adjust.")
    if args.db is not None:
        expr = f"{args.db}dB"
    elif args.factor is not None:
        expr = str(args.factor)
    else:
        raise SystemExit("pass --db or --factor")
    out = resolve_output(inp, args.out, "volume")
    run([*FFMPEG_BASE, "-i", str(inp), "-af", f"volume={expr}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)])
    return out, [f"Volume adjusted by {expr}."]


def op_mute(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    out = resolve_output(inp, args.out, "muted")
    try:
        run([*FFMPEG_BASE, "-i", str(inp), "-an", "-c:v", "copy", str(out)])
    except SystemExit:
        run([*FFMPEG_BASE, "-i", str(inp), "-an", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", str(out)])
    return out, ["Audio track removed."]


def op_watermark(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    if not args.text and not args.image:
        raise SystemExit("pass --text or --image")
    if args.text and args.image:
        raise SystemExit("pass --text or --image, not both")
    out = resolve_output(inp, args.out, "watermark")
    pos = POSITIONS.get(args.position, POSITIONS["br"])
    notes: list[str] = []

    if args.text:
        with tempfile.TemporaryDirectory() as td:
            textfile = Path(td) / "watermark.txt"
            textfile.write_text(args.text, encoding="utf-8")
            x, y = pos.split(":")
            vf = (
                f"drawtext=textfile={quote_filter_value(textfile)}:"
                f"fontcolor=white:fontsize={args.font_size}:"
                f"box=1:boxcolor=black@0.4:boxborderw=8:x={x}:y={y}"
            )
            cmd = [*FFMPEG_BASE, "-i", str(inp), "-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "veryfast"]
            meta = probe(inp)
            if meta["has_audio"]:
                cmd += ["-c:a", "copy"]
            cmd.append(str(out))
            run(cmd)
        notes.append(f"Burned in text watermark at {args.position}.")
    else:
        image = resolve_input(args.image)
        x, y = pos.split(":")
        filt = f"[1:v]scale={args.image_width}:-1[wm];[0:v][wm]overlay={x}:{y}"
        cmd = [*FFMPEG_BASE, "-i", str(inp), "-i", str(image), "-filter_complex", filt,
               "-c:v", "libx264", "-crf", "18", "-preset", "veryfast"]
        meta = probe(inp)
        if meta["has_audio"]:
            cmd += ["-c:a", "copy"]
        cmd.append(str(out))
        run(cmd)
        notes.append(f"Overlaid image watermark at {args.position} ({args.image_width}px wide).")
    return out, notes


def op_subtitles(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    sub = resolve_input(args.srt)
    out = resolve_output(inp, args.out, "subtitled")
    notes: list[str] = []

    if args.embed:
        ext = out.suffix.lower()
        sub_codec = "mov_text" if ext in (".mp4", ".m4v", ".mov") else "srt"
        run([
            *FFMPEG_BASE, "-i", str(inp), "-i", str(sub),
            "-map", "0", "-map", "1", "-c", "copy", "-c:s", sub_codec, str(out),
        ])
        notes.append(f"Embedded as a selectable subtitle track ({sub_codec}) — stream-copied, no re-encode.")
    else:
        vf = f"subtitles=filename={quote_filter_value(sub)}"
        cmd = [*FFMPEG_BASE, "-i", str(inp), "-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "veryfast"]
        meta = probe(inp)
        if meta["has_audio"]:
            cmd += ["-c:a", "copy"]
        cmd.append(str(out))
        run(cmd)
        notes.append("Subtitles burned into the video (hardsub, always visible). Pass --embed for a toggleable track.")
    return out, notes


def op_gif(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    start = parse_time(args.start)
    end = parse_time(args.end)
    out = resolve_output(inp, args.out, "clip", ext=".gif")
    seek = []
    if start is not None:
        seek += ["-ss", f"{start:.3f}"]
    dur = []
    if end is not None:
        span = end - (start or 0.0)
        if span <= 0:
            raise SystemExit("--end must be after --start")
        dur = ["-t", f"{span:.3f}"]

    vf = f"fps={args.fps},scale={args.width}:-1:flags=lanczos"
    with tempfile.TemporaryDirectory() as td:
        palette = Path(td) / "palette.png"
        run([*FFMPEG_BASE, *seek, "-i", str(inp), *dur, "-vf", f"{vf},palettegen", str(palette)])
        run([
            *FFMPEG_BASE, *seek, "-i", str(inp), *dur, "-i", str(palette),
            "-lavfi", f"{vf}[x];[x][1:v]paletteuse", str(out),
        ])
    return out, [f"{args.fps}fps, {args.width}px wide, palette-optimized GIF."]


def op_resize(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    if not args.width and not args.height and not args.scale:
        raise SystemExit("pass --width, --height, and/or --scale")
    out = resolve_output(inp, args.out, "resized")
    if args.scale:
        vf = f"scale=iw*{args.scale}:ih*{args.scale}"
    elif args.width and args.height:
        vf = f"scale={args.width}:{args.height}"
    elif args.width:
        vf = f"scale={args.width}:-2"
    else:
        vf = f"scale=-2:{args.height}"
    cmd = [*FFMPEG_BASE, "-i", str(inp), "-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "veryfast"]
    meta = probe(inp)
    if meta["has_audio"]:
        cmd += ["-c:a", "copy"]
    cmd.append(str(out))
    run(cmd)
    return out, [f"Resized with filter `{vf}`."]


def op_crop(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    out = resolve_output(inp, args.out, "cropped")
    vf = f"crop={args.width}:{args.height}:{args.x}:{args.y}"
    cmd = [*FFMPEG_BASE, "-i", str(inp), "-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "veryfast"]
    meta = probe(inp)
    if meta["has_audio"]:
        cmd += ["-c:a", "copy"]
    cmd.append(str(out))
    run(cmd)
    return out, [f"Cropped to {args.width}x{args.height} at offset ({args.x},{args.y})."]


ROTATE_MAP = {90: "transpose=1", 180: "transpose=1,transpose=1", 270: "transpose=2"}


def op_rotate(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    degrees = args.degrees
    if args.ccw and degrees == 90:
        vf = "transpose=2"
    elif args.ccw and degrees == 270:
        vf = "transpose=1"
    else:
        vf = ROTATE_MAP.get(degrees)
    if vf is None:
        raise SystemExit("--degrees must be one of: 90, 180, 270")
    out = resolve_output(inp, args.out, f"rot{degrees}")
    cmd = [*FFMPEG_BASE, "-i", str(inp), "-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "veryfast"]
    meta = probe(inp)
    if meta["has_audio"]:
        cmd += ["-c:a", "copy"]
    cmd.append(str(out))
    run(cmd)
    return out, [f"Rotated {degrees}°{' counter-clockwise' if args.ccw else ' clockwise'}."]


AUDIO_CODECS = {"mp3": ("libmp3lame", "-q:a", "2"), "aac": ("aac", "-b:a", "192k"),
                "wav": ("pcm_s16le", "-ar", "44100"), "m4a": ("aac", "-b:a", "192k")}


def op_extract_audio(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    meta = probe(inp)
    if not meta["has_audio"]:
        raise SystemExit("Input has no audio stream to extract.")
    fmt = args.format
    codec, *extra = AUDIO_CODECS[fmt]
    out = resolve_output(inp, args.out, "audio", ext=f".{fmt}")
    run([*FFMPEG_BASE, "-i", str(inp), "-vn", "-c:a", codec, *extra, str(out)])
    return out, [f"Extracted audio as {fmt}."]


def op_thumbnail(inp: Path, args: argparse.Namespace) -> tuple[Path, list[str]]:
    at = parse_time(args.at) or 0.0
    out = resolve_output(inp, args.out, "thumb", ext=".jpg")
    run([*FFMPEG_BASE, "-ss", f"{at:.3f}", "-i", str(inp), "-frames:v", "1", "-q:v", "2", str(out)])
    return out, [f"Frame captured at t={format_time(at)}."]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="edit", description="Edit a local video file with ffmpeg.")
    sub = ap.add_subparsers(dest="op", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("input", help="Path to the source video")
        p.add_argument("--out", default=None, help="Output path (default: alongside input)")

    p = sub.add_parser("trim", help="Cut a segment out of a video")
    common(p)
    p.add_argument("--start", default=None, help="Start time (SS, MM:SS, HH:MM:SS)")
    p.add_argument("--end", default=None, help="End time")
    p.add_argument("--duration", default=None, help="Duration instead of --end")
    p.add_argument("--exact", action="store_true", help="Re-encode for frame-accurate cuts (slower)")

    p = sub.add_parser("concat", help="Merge multiple videos into one, in order")
    common(p)
    p.add_argument("inputs", nargs="+", help="Additional video paths, appended after `input` in order")
    p.add_argument("--width", type=int, default=None, help="Force output width if re-encoding is needed")
    p.add_argument("--height", type=int, default=None, help="Force output height if re-encoding is needed")

    p = sub.add_parser("compress", help="Reduce file size")
    common(p)
    p.add_argument("--crf", type=int, default=None, help="Quality (18=near-lossless .. 28=default .. 35=small)")
    p.add_argument("--preset", default=None, help="ffmpeg preset (default medium)")
    p.add_argument("--target-size-mb", type=float, default=None, help="Two-pass encode to hit an approx target size")

    p = sub.add_parser("speed", help="Change playback speed (video + pitch-corrected audio)")
    common(p)
    p.add_argument("--factor", type=float, required=True, help="e.g. 2.0 = 2x faster, 0.5 = half speed")
    p.add_argument("--no-audio-pitch-fix", action="store_true", help="Drop audio instead of tempo-shifting it")

    p = sub.add_parser("volume", help="Adjust audio volume")
    common(p)
    p.add_argument("--db", type=float, default=None, help="Change in dB, e.g. 6 or -10")
    p.add_argument("--factor", type=float, default=None, help="Linear multiplier, e.g. 1.5 or 0.5")

    p = sub.add_parser("mute", help="Remove the audio track")
    common(p)

    p = sub.add_parser("watermark", help="Overlay text or an image watermark")
    common(p)
    p.add_argument("--text", default=None, help="Text watermark")
    p.add_argument("--image", default=None, help="Image watermark (PNG with alpha recommended)")
    p.add_argument("--position", choices=list(POSITIONS), default="br")
    p.add_argument("--font-size", type=int, default=24)
    p.add_argument("--image-width", type=int, default=150)

    p = sub.add_parser("subtitles", help="Burn in or embed a subtitle file (.srt/.vtt/.ass)")
    common(p)
    p.add_argument("--srt", required=True, help="Subtitle file path")
    p.add_argument("--embed", action="store_true", help="Embed as a toggleable track instead of burning in")

    p = sub.add_parser("gif", help="Convert a video (or a segment) to an optimized GIF")
    common(p)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--width", type=int, default=480)

    p = sub.add_parser("resize", help="Change resolution")
    common(p)
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--scale", type=float, default=None, help="Scale factor, e.g. 0.5")

    p = sub.add_parser("crop", help="Crop to a region")
    common(p)
    p.add_argument("--width", type=int, required=True)
    p.add_argument("--height", type=int, required=True)
    p.add_argument("--x", type=int, default=0)
    p.add_argument("--y", type=int, default=0)

    p = sub.add_parser("rotate", help="Rotate 90/180/270 degrees")
    common(p)
    p.add_argument("--degrees", type=int, required=True, choices=[90, 180, 270])
    p.add_argument("--ccw", action="store_true", help="Counter-clockwise instead of clockwise (90/270 only)")

    p = sub.add_parser("extract-audio", help="Pull the audio track out to its own file")
    common(p)
    p.add_argument("--format", choices=list(AUDIO_CODECS), default="mp3")

    p = sub.add_parser("thumbnail", help="Grab a single frame as a JPEG")
    common(p)
    p.add_argument("--at", default="0", help="Timestamp (SS, MM:SS, HH:MM:SS)")

    return ap


OPS = {
    "trim": op_trim,
    "concat": op_concat,
    "compress": op_compress,
    "speed": op_speed,
    "volume": op_volume,
    "mute": op_mute,
    "watermark": op_watermark,
    "subtitles": op_subtitles,
    "gif": op_gif,
    "resize": op_resize,
    "crop": op_crop,
    "rotate": op_rotate,
    "extract-audio": op_extract_audio,
    "thumbnail": op_thumbnail,
}


def main() -> int:
    require_binaries()
    args = build_parser().parse_args()
    inp = resolve_input(args.input)
    handler = OPS[args.op]
    out, notes = handler(inp, args)
    _report(args.op, inp, out, notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
