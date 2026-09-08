"""End-to-end coverage of edit.py operations against ffmpeg-synthesized clips."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

EDIT = Path(__file__).resolve().parent.parent / "skills" / "edit" / "scripts" / "edit.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(EDIT), *args], capture_output=True, text=True,
    )


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    return json.loads(result.stdout or "{}")


def _has_stream(meta: dict, kind: str) -> bool:
    return any(s.get("codec_type") == kind for s in meta.get("streams", []))


def _duration(meta: dict) -> float:
    return float(meta.get("format", {}).get("duration") or 0.0)


def test_trim_shortens_duration(cut_clip: Path, tmp_path: Path):
    out = tmp_path / "trimmed.mp4"
    proc = _run("trim", str(cut_clip), "--start", "0", "--end", "2", "--exact", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()
    assert _duration(_probe(out)) <= 2.5


def test_trim_stream_copy_falls_back_message(cut_clip: Path, tmp_path: Path):
    out = tmp_path / "trimmed_copy.mp4"
    proc = _run("trim", str(cut_clip), "--start", "0", "--end", "2", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()


def test_mute_removes_audio(audio_clip: Path, tmp_path: Path):
    out = tmp_path / "muted.mp4"
    proc = _run("mute", str(audio_clip), "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert not _has_stream(_probe(out), "audio")


def test_volume_requires_audio(cut_clip: Path, tmp_path: Path):
    out = tmp_path / "vol.mp4"
    proc = _run("volume", str(cut_clip), "--db", "6", "--out", str(out))
    assert proc.returncode != 0
    assert "no audio" in proc.stderr.lower()


def test_volume_adjusts_audio(audio_clip: Path, tmp_path: Path):
    out = tmp_path / "louder.mp4"
    proc = _run("volume", str(audio_clip), "--db", "6", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert _has_stream(_probe(out), "audio")


def test_resize_changes_width(cut_clip: Path, tmp_path: Path):
    out = tmp_path / "resized.mp4"
    proc = _run("resize", str(cut_clip), "--width", "160", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    meta = _probe(out)
    v = next(s for s in meta["streams"] if s["codec_type"] == "video")
    assert v["width"] == 160


def test_rotate_90_swaps_dimensions(cut_clip: Path, tmp_path: Path):
    orig = _probe(cut_clip)
    ov = next(s for s in orig["streams"] if s["codec_type"] == "video")
    out = tmp_path / "rotated.mp4"
    proc = _run("rotate", str(cut_clip), "--degrees", "90", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    meta = _probe(out)
    v = next(s for s in meta["streams"] if s["codec_type"] == "video")
    assert v["width"] == ov["height"]
    assert v["height"] == ov["width"]


def test_speed_2x_halves_duration(cut_clip: Path, tmp_path: Path):
    orig_duration = _duration(_probe(cut_clip))
    out = tmp_path / "fast.mp4"
    proc = _run("speed", str(cut_clip), "--factor", "2.0", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    new_duration = _duration(_probe(out))
    assert new_duration < orig_duration * 0.7


def test_extract_audio_produces_audio_only(audio_clip: Path, tmp_path: Path):
    out = tmp_path / "audio.mp3"
    proc = _run("extract-audio", str(audio_clip), "--format", "mp3", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    meta = _probe(out)
    assert _has_stream(meta, "audio")
    assert not _has_stream(meta, "video")


def test_thumbnail_produces_jpeg(cut_clip: Path, tmp_path: Path):
    out = tmp_path / "thumb.jpg"
    proc = _run("thumbnail", str(cut_clip), "--at", "1", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()
    assert out.stat().st_size > 0


def test_gif_produces_output(cut_clip: Path, tmp_path: Path):
    out = tmp_path / "clip.gif"
    proc = _run("gif", str(cut_clip), "--start", "0", "--end", "1", "--fps", "5", "--width", "160", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()
    assert out.stat().st_size > 0


def test_crop_produces_requested_dimensions(cut_clip: Path, tmp_path: Path):
    out = tmp_path / "cropped.mp4"
    proc = _run("crop", str(cut_clip), "--width", "100", "--height", "80", "--x", "10", "--y", "10", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    v = next(s for s in _probe(out)["streams"] if s["codec_type"] == "video")
    assert v["width"] == 100
    assert v["height"] == 80


def test_watermark_text_burns_in(cut_clip: Path, tmp_path: Path):
    out = tmp_path / "watermarked.mp4"
    proc = _run("watermark", str(cut_clip), "--text", "hello: world", "--position", "br", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()


def test_concat_merges_two_clips(cut_clip: Path, static_clip: Path, tmp_path: Path):
    out = tmp_path / "merged.mp4"
    proc = _run("concat", str(cut_clip), str(static_clip), "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    merged_duration = _duration(_probe(out))
    expected = _duration(_probe(cut_clip)) + _duration(_probe(static_clip))
    assert merged_duration >= expected * 0.8


def test_missing_input_errors_clearly(tmp_path: Path):
    proc = _run("trim", str(tmp_path / "nope.mp4"), "--start", "0", "--end", "1")
    assert proc.returncode != 0
    assert "not found" in proc.stderr.lower()
