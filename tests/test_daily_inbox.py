"""/daily inbox: KakaoTalk export parsing, screenshots, pending-state flow."""
from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "daily" / "scripts"))

import daily  # noqa: E402
import inbox  # noqa: E402
import notes  # noqa: E402


ANDROID_KO = """나와의 채팅 님과 카카오톡 대화
저장한 날짜 : 2026년 10월 7일 오후 11:00

2026년 10월 7일 오전 9:05
2026년 10월 7일 오전 9:05, 회원님 : https://example.com/rust-ownership 나중에 읽기
2026년 10월 7일 오후 12:30, 회원님 : 장보기
- 우유
- 계란
2026년 10월 7일 오후 9:00, 회원님 : 사진
"""

IOS_KO = """나와의 채팅 님과 카카오톡 대화
저장한 날짜 : 2026. 10. 7. 오후 11:00

2026. 10. 7. 오전 12:15, 나 : 자정 넘어 메모
2026. 10. 7. 오후 12:00, 나 : 점심 메모
"""

PC_KO = """나와의 채팅 님과 카카오톡 대화
저장한 날짜 : 2026-10-07 23:00:00

--------------- 2026년 10월 7일 화요일 ---------------
[나] [오후 3:15] 강의 자료 링크 https://example.com/slides.pdf
[나] [오후 3:16] 두 줄
메시지
"""

ANDROID_EN = """Chats with yourself
Date Saved : October 7, 2026, 11:00 PM

October 7, 2026, 9:30 PM, Me : english memo
"""

PC_CSV = """Date,User,Message
2026-10-07 21:30:00,"나","csv 메모, 쉼표 포함"
"""


@pytest.mark.parametrize("text, expected", [
    (ANDROID_KO, [
        (datetime(2026, 10, 7, 9, 5), "회원님", "https://example.com/rust-ownership 나중에 읽기"),
        (datetime(2026, 10, 7, 12, 30), "회원님", "장보기\n- 우유\n- 계란"),
        (datetime(2026, 10, 7, 21, 0), "회원님", "사진"),
    ]),
    (IOS_KO, [
        (datetime(2026, 10, 7, 0, 15), "나", "자정 넘어 메모"),
        (datetime(2026, 10, 7, 12, 0), "나", "점심 메모"),
    ]),
    (PC_KO, [
        (datetime(2026, 10, 7, 15, 15), "나", "강의 자료 링크 https://example.com/slides.pdf"),
        (datetime(2026, 10, 7, 15, 16), "나", "두 줄\n메시지"),
    ]),
    (ANDROID_EN, [(datetime(2026, 10, 7, 21, 30), "Me", "english memo")]),
    ("﻿" + PC_CSV, [(datetime(2026, 10, 7, 21, 30), "나", "csv 메모, 쉼표 포함")]),
])
def test_parse_kakao_formats(text, expected):
    got = [(m["dt"], m["name"], m["text"]) for m in inbox.parse_kakao_text(text)]
    assert got == expected


def test_read_kakao_zip_and_cp949(tmp_path):
    archive = tmp_path / "Talk.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("KakaoTalkChats.txt", ANDROID_KO)
        zf.writestr("photo.jpg", b"\xff\xd8")
    assert len(inbox.read_kakao_file(archive)) == 3

    legacy = tmp_path / "old.txt"
    legacy.write_bytes(IOS_KO.encode("cp949"))
    assert len(inbox.read_kakao_file(legacy)) == 2


def test_kakao_high_water_mark(tmp_path):
    export = tmp_path / "a.txt"
    export.write_text(ANDROID_KO, encoding="utf-8")
    state: dict = {}
    since = datetime(2026, 10, 1).date()

    first = inbox.new_kakao_messages([export], state, since)
    assert len(first) == 3
    inbox.advance_kakao(state, first)

    # Same export again (plus a duplicate copy) → nothing new.
    copy = tmp_path / "b.txt"
    copy.write_text(ANDROID_KO, encoding="utf-8")
    assert inbox.new_kakao_messages([export, copy], state, None) == []

    # Next day's full re-export only yields the new tail, including a second
    # message in the same minute as the previous high-water mark.
    export.write_text(ANDROID_KO + "2026년 10월 7일 오후 9:00, 회원님 : 같은 분 다른 메모\n"
                      "2026년 10월 8일 오전 8:00, 회원님 : 다음 날\n", encoding="utf-8")
    fresh = inbox.new_kakao_messages([export], state, None)
    assert [m["text"] for m in fresh] == ["같은 분 다른 메모", "다음 날"]


@pytest.mark.parametrize("name, expected, app", [
    ("Screenshot_20261007_093015_KakaoTalk.jpg", datetime(2026, 10, 7, 9, 30, 15), "KakaoTalk"),
    ("Screenshot_20261007-093015.png", datetime(2026, 10, 7, 9, 30, 15), None),
    ("2026-10-07 09.30.15.png", datetime(2026, 10, 7, 9, 30, 15), None),
    ("Screenshot 2026-10-07 at 9.30.15 PM.png", datetime(2026, 10, 7, 21, 30, 15), None),
    ("스크린샷 2026-10-07 오후 9.30.15.png", datetime(2026, 10, 7, 21, 30, 15), None),
])
def test_screenshot_time_from_name(tmp_path, name, expected, app):
    path = tmp_path / name
    path.write_bytes(b"x")
    assert inbox.screenshot_time(path) == (expected, app)


def test_screenshot_time_falls_back_to_file_time(tmp_path):
    path = tmp_path / "IMG_1234.PNG"
    path.write_bytes(b"x")
    stamp = datetime(2026, 10, 7, 22, 0).timestamp()
    os.utime(path, (stamp, stamp))
    when, app = inbox.screenshot_time(path)
    if not hasattr(path.stat(), "st_birthtime"):
        assert when == datetime(2026, 10, 7, 22, 0)
    assert app is None


def make_args(out: Path, *sources: str, **extra) -> argparse.Namespace:
    args = notes.build_parser().parse_args([*sources, "--out", str(out)])
    args.only = extra.get("only")
    args.mark_noted = extra.get("mark_noted")
    args.list = extra.get("list", False)
    args.since = extra.get("since")
    return args


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "ICLOUD_DRIVE", tmp_path / "no-icloud")
    kakao = tmp_path / "kakao"
    shots = tmp_path / "shots"
    kakao.mkdir()
    shots.mkdir()
    (kakao / "나와의 채팅.txt").write_text(ANDROID_KO.replace("2026년 10월 7일", "{d}"), encoding="utf-8")
    settings = {"DAILY_KAKAO": str(kakao), "DAILY_SCREENSHOTS": str(shots)}
    return tmp_path / "out", kakao, shots, settings


def ko_day(d) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일"


def test_daily_run_collects_and_marks_noted(setup):
    out, kakao, shots, settings = setup
    today = datetime.now().date()
    export = kakao / "나와의 채팅.txt"
    export.write_text(export.read_text(encoding="utf-8").replace("{d}", ko_day(today)), encoding="utf-8")
    (shots / f"Screenshot_{today:%Y%m%d}_101010_Chrome.jpg").write_bytes(b"\xff\xd8")
    old = shots / f"Screenshot_{today - timedelta(days=30):%Y%m%d}_101010.jpg"
    old.write_bytes(b"\xff\xd8")

    # --list previews without touching state.
    report, _ = daily.run(make_args(out, list=True, only=["kakao", "screenshots"]), settings)
    day = report["days"][today.isoformat()]
    assert len(day["kakao"]) == 3 and len(day["screenshots"]) == 1
    assert not inbox.state_path(out).exists()

    report, code = daily.run(make_args(out, only=["kakao", "screenshots"]), settings)
    assert code == 0
    day = report["days"][today.isoformat()]
    assert day["urls"] == ["https://example.com/rust-ownership"]
    assert day["screenshots"][0]["app"] == "Chrome"  # first-run window skips the 30-day-old one
    assert day["note_exists"] is False
    assert day["daily_note"] == str(out / "daily" / f"{today.isoformat()}.md")

    # Not marked yet → still pending on the next run, but not duplicated.
    report, _ = daily.run(make_args(out, only=["kakao", "screenshots"]), settings)
    assert len(report["days"][today.isoformat()]["kakao"]) == 3
    assert report["kakao"]["new_messages"] == 0

    report, _ = daily.run(make_args(out, mark_noted=[today.isoformat()]), settings)
    assert report["marked_noted"] == [today.isoformat()]
    report, _ = daily.run(make_args(out, only=["kakao", "screenshots"]), settings)
    assert report["days"] == {}

    # A new screenshot later the same day shows up alone.
    (shots / f"Screenshot_{today:%Y%m%d}_235959.png").write_bytes(b"\x89PNG")
    report, _ = daily.run(make_args(out, only=["kakao", "screenshots"]), settings)
    assert [len(d.get("screenshots", [])) for d in report["days"].values()] == [1]


def test_daily_run_without_any_sources_is_quiet(setup, monkeypatch):
    out, kakao, shots, _ = setup
    monkeypatch.setattr(notes, "MAC_VOICE_MEMOS_DIRS", [])
    report, code = daily.run(make_args(out), {})
    assert code == 0
    assert [e["error"] for e in report["errors"]] == ["no_kakao_export"]
    assert report["kakao"]["sources"] == [str(out / "inbox" / "kakao")]


def test_route_positional_sources(tmp_path):
    routed = daily.route(["a.m4a", "chat.txt", "chat.zip", "shot.PNG"])
    assert routed == {"recordings": ["a.m4a"], "kakao": ["chat.txt", "chat.zip"], "screenshots": ["shot.PNG"]}
    with pytest.raises(SystemExit):
        daily.route(["notes.docx"])


def test_corrupt_state_is_set_aside(tmp_path):
    path = inbox.state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert inbox.load_state(tmp_path) == {"version": 1}
    assert path.with_suffix(".corrupt.json").exists()


# --- macOS Photos export (osxphotos) --------------------------------------

def fake_osxphotos(tmp_path: Path, monkeypatch, exit_code: int = 0) -> Path:
    """Stand-in osxphotos that drops one dated screenshot and logs its argv."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "osxphotos.log"
    script = bindir / "osxphotos"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        f"[ {exit_code} -ne 0 ] && {{ echo 'boom' >&2; exit {exit_code}; }}\n"
        'touch "$2/$(date +%Y-%m-%d) 09.30.15.png"\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return log


def test_photos_export_feeds_screenshots(setup, tmp_path, monkeypatch):
    out, _, _, settings = setup
    settings = {**settings, "DAILY_PHOTOS": "true"}
    log = fake_osxphotos(tmp_path, monkeypatch)

    report, _ = daily.run(make_args(out, list=True, only=["screenshots"]), settings)
    assert not log.exists()  # --list never exports

    report, code = daily.run(make_args(out, only=["screenshots"], since="2026-09-01"), settings)
    assert code == 0 and report["errors"] == []
    argv = log.read_text().split()
    assert argv[:2] == ["export", str(out / "inbox" / "photos-screenshots")]
    assert "--screenshot" in argv and "--update" in argv
    assert argv[argv.index("--from-date") + 1] == "2026-09-01"
    today = datetime.now().date().isoformat()
    shot = report["days"][today]["screenshots"][0]
    assert shot["time"] == "09:30" and shot["path"].endswith(f"{today} 09.30.15.png")


def test_photos_export_errors_are_reported(setup, tmp_path, monkeypatch):
    out, _, _, settings = setup
    settings = {**settings, "DAILY_PHOTOS": "1"}
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    report, _ = daily.run(make_args(out, only=["screenshots"]), settings)
    assert report["errors"][0]["error"] == "osxphotos_missing"

    fake_osxphotos(tmp_path, monkeypatch, exit_code=1)
    report, _ = daily.run(make_args(out, only=["screenshots"]), settings)
    assert report["errors"][0]["error"] == "photos_export_failed"
    assert "boom" in report["errors"][0]["detail"]
