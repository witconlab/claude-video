"""/daily recordings: discovery, dedup, transcript caching, manifest."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
NOTES_SCRIPTS = REPO / "skills" / "daily" / "scripts"
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
    # /daily ships its own copy so the skill folder stays self-contained.
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
    for key in (*notes.SETTING_KEYS, *notes.LEGACY_KEYS):
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
    assert [e["error"] for e in report["errors"]] == ["no_api_key", "needs_whisper"]


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


# --- Built-in phone transcripts -------------------------------------------

def atom(kind: bytes, body: bytes) -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + kind + body


def inject_tsrp(path: Path, payload: dict) -> Path:
    """Append moov/trak/udta/tsrp the way iOS Voice Memos does (moov sits after mdat)."""
    buf = bytearray(path.read_bytes())
    tsrp = atom(b"udta", atom(b"tsrp", json.dumps(payload, ensure_ascii=False).encode("utf-8")))
    pos = 0
    while pos < len(buf):
        size = int.from_bytes(buf[pos:pos + 4], "big")
        if buf[pos + 4:pos + 8] == b"moov":
            inner = pos + 8
            while inner < pos + size:
                isize = int.from_bytes(buf[inner:inner + 4], "big")
                if buf[inner + 4:inner + 8] == b"trak":
                    buf[inner + isize:inner + isize] = tsrp
                    buf[inner:inner + 4] = (isize + len(tsrp)).to_bytes(4, "big")
                    buf[pos:pos + 4] = (size + len(tsrp)).to_bytes(4, "big")
                    path.write_bytes(bytes(buf))
                    return path
                inner += isize
        pos += size
    raise AssertionError("no moov/trak in synthesized clip")


APPLE_PAYLOAD = {
    "attributedString": {
        "runs": ["오늘은 ", 0, "자료구조 ", 1, "수업입니다. ", 2, "스택을 ", 3, "배웁니다.", 4],
        "attributeTable": [
            {"timeRange": [0.0, 0.5]}, {"timeRange": [0.5, 1.0]}, {"timeRange": [1.0, 1.6]},
            {"timeRange": [4.0, 4.4]}, {"timeRange": [4.4, 5.0]},
        ],
    },
    "locale": {"identifier": "ko_KR", "current": 0},
}


def test_apple_transcript_from_tsrp_atom(tmp_path):
    path = inject_tsrp(make_audio(tmp_path / "memo.m4a"), APPLE_PAYLOAD)
    segments, locale = notes.apple_transcript(path)
    assert locale == "ko_KR"
    assert segments == [
        {"start": 0.0, "end": 1.6, "text": "오늘은 자료구조 수업입니다."},
        {"start": 4.0, "end": 5.0, "text": "스택을 배웁니다."},
    ]
    # The injected atom must not break normal probing.
    assert float(notes.probe(path)["duration"]) > 0


def test_apple_transcript_absent(tmp_path):
    assert notes.apple_transcript(make_audio(tmp_path / "plain.m4a")) is None
    junk = tmp_path / "junk.m4a"
    junk.write_bytes(b"not an mp4 at all")
    assert notes.apple_transcript(junk) is None


def test_group_words_breaks_on_pause_and_length():
    words = [("a ", 0.0, 0.5), ("b ", 0.6, 1.0), ("c ", 5.0, 5.5), ("d", 40.0, 40.5)]
    assert [s["text"] for s in notes.group_words(words)] == ["a b", "c", "d"]


def test_main_uses_phone_transcripts_without_whisper(isolated, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(whisper, "load_api_key", lambda preferred=None: (None, None))
    src = tmp_path / "memos"
    src.mkdir()
    inject_tsrp(make_audio(src / "20261007 093015-IPHONE.m4a"), APPLE_PAYLOAD)
    make_audio(src / "음성 261007_140000.m4a")
    (src / "음성 261007_140000.txt").write_text("\ufeff화자 1 00:00\n회의 내용입니다\n", encoding="utf-8")
    out = tmp_path / "out"

    code, report = run_main(monkeypatch, capsys, [str(src), "--out", str(out), "--list"])
    assert [p["transcript_source"] for p in report["pending"]] == ["apple-voice-memos (ko_KR)", "sidecar"]

    code, report = run_main(monkeypatch, capsys, [str(src), "--out", str(out)])
    assert code == 0 and report["errors"] == [] and isolated == []
    iphone, galaxy = report["pending"]
    assert iphone["transcript_source"] == "apple-voice-memos (ko_KR)"
    assert Path(iphone["transcript_path"]).read_text(encoding="utf-8") == (
        "[00:00:00] 오늘은 자료구조 수업입니다.\n[00:00:04] 스택을 배웁니다.\n"
    )
    assert galaxy["transcript_source"] == "sidecar"
    assert Path(galaxy["transcript_path"]).read_text(encoding="utf-8") == "화자 1 00:00\n회의 내용입니다\n"

    # Origin survives the cache on the next run.
    _, report = run_main(monkeypatch, capsys, [str(src), "--out", str(out)])
    assert report["pending"][0]["transcript_source"] == "apple-voice-memos (ko_KR)"


def test_force_whisper_ignores_phone_transcript(isolated, monkeypatch, capsys, tmp_path):
    src = tmp_path / "memos"
    src.mkdir()
    inject_tsrp(make_audio(src / "memo.m4a"), APPLE_PAYLOAD)
    out = tmp_path / "out"
    run_main(monkeypatch, capsys, [str(src), "--out", str(out)])
    assert isolated == []
    _, report = run_main(monkeypatch, capsys, [str(src), "--out", str(out), "--force-whisper"])
    assert isolated == [("memo.m4a", None)]
    assert report["pending"][0]["transcript_source"] == "whisper (groq)"
