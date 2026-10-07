"""/voice-notes: recording discovery, dedup, transcript caching, manifest."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
NOTES_SCRIPTS = REPO / "skills" / "voice-notes" / "scripts"
sys.path.insert(0, str(NOTES_SCRIPTS))

import notes  # noqa: E402
import whisper  # noqa: E402


def make_audio(path: Path, seconds: float = 1.0, creation_time: str | None = None) -> Path:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-t", str(seconds), "-i", "sine=frequency=440",
        "-c:a", "aac",
    ]
    if creation_time:
        cmd += ["-metadata", f"creation_time={creation_time}"]
    subprocess.run([*cmd, str(path)], check=True, capture_output=True)
    return path


def test_whisper_copy_matches_watch():
    # voice-notes ships its own copy so the skill folder stays self-contained.
    watch_copy = REPO / "skills" / "watch" / "scripts" / "whisper.py"
    assert (NOTES_SCRIPTS / "whisper.py").read_text() == watch_copy.read_text()


def test_language_hint_is_sent(monkeypatch, tmp_path):
    captured = {}

    def fake_multipart(fields, file_path):
        captured.update(fields)
        raise SystemExit("stop")

    monkeypatch.setattr(whisper, "_build_multipart", fake_multipart)
    with pytest.raises(SystemExit):
        whisper._post_whisper("http://x", "k", "m", tmp_path / "a.mp3", "ko")
    assert captured["language"] == "ko"

    captured.clear()
    with pytest.raises(SystemExit):
        whisper._post_whisper("http://x", "k", "m", tmp_path / "a.mp3")
    assert "language" not in captured


class TestTimeFromFilename:
    def test_iphone(self):
        assert notes.time_from_filename("20261007 093015-1A2B3C4D.m4a") == datetime(2026, 10, 7, 9, 30, 15)

    def test_samsung_short_year(self):
        assert notes.time_from_filename("음성 261007_093015.m4a") == datetime(2026, 10, 7, 9, 30, 15)

    def test_no_timestamp(self):
        assert notes.time_from_filename("lecture.m4a") is None

    def test_invalid_date(self):
        assert notes.time_from_filename("20261399 093015.m4a") is None


def test_recorded_at_prefers_container_tag(tmp_path):
    path = make_audio(tmp_path / "20200101 000000.m4a", creation_time="2026-10-07T00:30:00Z")
    when = notes.recorded_at(path, notes.probe(path))
    expected = datetime.fromisoformat("2026-10-07T00:30:00+00:00").astimezone().replace(tzinfo=None)
    assert when == expected


def test_done_sources_reads_frontmatter(tmp_path):
    (tmp_path / "2026-10").mkdir()
    (tmp_path / "2026-10" / "a.md").write_text("---\nsource: rec 1.m4a\ntype: daily\n---\n# x\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# no frontmatter\nsource: fake.m4a\n", encoding="utf-8")
    assert notes.done_sources(tmp_path) == {"rec 1.m4a"}


def test_clean_segments_drops_hallucinations_and_repeats():
    segs = [
        {"start": 0, "end": 1, "text": "안녕하세요"},
        {"start": 1, "end": 2, "text": "시청해주셔서 감사합니다."},
        {"start": 2, "end": 3, "text": "네"},
        {"start": 3, "end": 4, "text": "네"},
    ]
    assert notes.clean_segments(segs) == [
        {"start": 0, "end": 1, "text": "안녕하세요"},
        {"start": 2, "end": 4, "text": "네"},
    ]


def test_find_audio_skips_hidden_and_non_audio(tmp_path):
    make_audio(tmp_path / "a.m4a")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / ".trash").mkdir()
    make_audio(tmp_path / ".trash" / "b.m4a")
    assert [p.name for p in notes.find_audio([tmp_path])] == ["a.m4a"]


def run_main(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["notes.py", *argv])
    code = notes.main()
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(notes, "CONFIG_FILE", tmp_path / "missing.env")
    for key in ("VOICE_NOTES_SOURCE", "VOICE_NOTES_DIR", "VOICE_NOTES_LANGUAGE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(whisper, "load_api_key", lambda preferred=None: ("groq", "test-key"))
    calls = []

    def fake_transcribe(path, audio_out, backend=None, api_key=None, language=None):
        calls.append((Path(path).name, language))
        return [{"start": 0.0, "end": 1.0, "text": "오늘 할 일은 장보기"}], backend

    monkeypatch.setattr(whisper, "transcribe_video", fake_transcribe)
    return calls


def test_main_transcribes_caches_and_dedups(isolated, monkeypatch, capsys, tmp_path):
    src = tmp_path / "memos"
    src.mkdir()
    make_audio(src / "20261007 093015-AAAA.m4a")
    make_audio(src / "20261008 101500-BBBB.m4a")
    out = tmp_path / "out"

    code, report = run_main(monkeypatch, capsys, [str(src), "--out", str(out), "--language", "ko"])
    assert code == 0
    assert [p["source"] for p in report["pending"]] == ["20261007 093015-AAAA.m4a", "20261008 101500-BBBB.m4a"]
    assert isolated == [("20261007 093015-AAAA.m4a", "ko"), ("20261008 101500-BBBB.m4a", "ko")]
    first = report["pending"][0]
    assert first["note_prefix"] == "2026-10-07_0930"
    assert Path(first["transcript_path"]).read_text(encoding="utf-8") == "[00:00:00] 오늘 할 일은 장보기\n"
    assert first["empty"] is False

    # Cached transcript is reused without another API call.
    isolated.clear()
    _, report = run_main(monkeypatch, capsys, [str(src), "--out", str(out)])
    assert len(report["pending"]) == 2 and isolated == []

    # A note citing the source marks it done.
    note_dir = Path(first["note_dir"])
    note_dir.mkdir(parents=True)
    (note_dir / "2026-10-07_0930 장보기.md").write_text(
        f"---\nsource: {first['source']}\ntype: daily\n---\n", encoding="utf-8"
    )
    _, report = run_main(monkeypatch, capsys, [str(src), "--out", str(out)])
    assert [p["source"] for p in report["pending"]] == ["20261008 101500-BBBB.m4a"]
    assert report["already_done"] == 1


def test_main_limit_since_and_list(isolated, monkeypatch, capsys, tmp_path):
    src = tmp_path / "memos"
    src.mkdir()
    for name in ("20261001 080000-A.m4a", "20261005 080000-B.m4a", "20261006 080000-C.m4a"):
        make_audio(src / name)
    out = tmp_path / "out"

    _, report = run_main(monkeypatch, capsys, [str(src), "--out", str(out), "--since", "2026-10-02", "--limit", "1", "--list"])
    assert [p["source"] for p in report["pending"]] == ["20261005 080000-B.m4a"]
    assert report["remaining"] == 1
    assert isolated == []
    assert not (out / "transcripts").exists()


def test_main_reports_missing_key(isolated, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(whisper, "load_api_key", lambda preferred=None: (None, None))
    src = tmp_path / "memos"
    src.mkdir()
    make_audio(src / "a.m4a")
    code, report = run_main(monkeypatch, capsys, [str(src), "--out", str(tmp_path / "out")])
    assert code == 1
    assert report["errors"][0]["error"] == "no_api_key"


def test_settings_file_supplies_defaults(isolated, monkeypatch, capsys, tmp_path):
    src = tmp_path / "memos"
    src.mkdir()
    make_audio(src / "a.m4a")
    env = tmp_path / "watch.env"
    env.write_text(
        f"VOICE_NOTES_SOURCE={src}\nVOICE_NOTES_DIR=\"{tmp_path / 'notes'}\"\nVOICE_NOTES_LANGUAGE=ko  # korean\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(notes, "CONFIG_FILE", env)
    _, report = run_main(monkeypatch, capsys, [])
    assert report["source_origin"] == "config"
    assert report["output_dir"] == str(tmp_path / "notes")
    assert report["output_dir_configured"] is True
    assert isolated == [("a.m4a", "ko")]
