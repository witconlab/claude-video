#!/usr/bin/env python3
"""KakaoTalk exports + screenshots half of /daily.

Both sources are append-only streams the user re-exports or re-syncs every
day, so the script keeps a small state file (<out>/.daily/state.json):

- kakao.last / kakao.last_keys: newest message already collected, so a full
  re-export only yields the messages after it.
- screenshots.seen / floor: screenshot files already collected, and the
  oldest date ever collected (set on the first run, default a week back).
- pending: collected items per day that no daily note has covered yet. The
  model removes a day with `daily.py --mark-noted YYYY-MM-DD` after writing
  that day's note, so a run that dies midway never loses items.

Pure stdlib (macOS `sips` is used only to make HEIC screenshots viewable).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

FIRST_RUN_DAYS = 7

KAKAO_EXTS = {".txt", ".csv", ".zip"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".heif"}
VIEWABLE = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&*+,;=%()]+")

# --- KakaoTalk export formats ---------------------------------------------
# Mobile (Korean):  2026년 10월 7일 오후 9:30, 이름 : 내용      (Android)
#                   2026. 10. 7. 오후 9:30, 이름 : 내용         (iOS)
# Mobile (English): October 7, 2026, 9:30 PM, Name : text   (Android)
#                   Oct 7, 2026 at 9:30 PM, Name : text     (iOS)
# PC/Mac txt:       --------------- 2026년 10월 7일 화요일 ---------------
#                   [이름] [오후 9:30] 내용
# PC/Mac csv:       Date,User,Message / 2026-10-07 21:30:00,이름,"내용"
# Lines that don't start a message continue the previous one (multi-line).

KO_DATE = r"(\d{4})\s*[년.]\s*(\d{1,2})\s*[월.]\s*(\d{1,2})\s*[일.]?"
KO_MOBILE = re.compile(rf"^{KO_DATE}\s*(오전|오후)?\s*(\d{{1,2}}):(\d{{2}})(?::\d{{2}})?\s*,\s*(.*)$")
EN_MOBILE = re.compile(r"^([A-Z][a-z]+\.? \d{1,2}, \d{4}),?\s*(?:at\s+)?(\d{1,2}):(\d{2})\s*([AaPp][Mm]),\s*(.*)$")
PC_DAY = re.compile(rf"^-+\s*{KO_DATE}\s*\S*\s*-+\s*$")
PC_DAY_EN = re.compile(r"^-+\s*(?:[A-Z][a-z]+,\s*)?([A-Z][a-z]+ \d{1,2}, \d{4})\s*-+\s*$")
PC_MSG = re.compile(r"^\[(.+?)\] \[(오전|오후|AM|PM)\s*(\d{1,2}):(\d{2})\] (.*)$")
# Date-only divider lines in mobile exports ("2026년 10월 7일 화요일", "2026. 10. 7. 오후 9:30").
KO_DIVIDER = re.compile(rf"^{KO_DATE}\s*(\S요일)?\s*((오전|오후)\s*)?(\d{{1,2}}:\d{{2}})?\s*$")
EN_DIVIDER = re.compile(r"^(?:[A-Z][a-z]+,\s*)?[A-Z][a-z]+\.? \d{1,2}, \d{4}(?:,?\s*(?:at\s+)?\d{1,2}:\d{2}\s*[AaPp][Mm])?\s*$")


def _hour(h: int, ampm: str | None) -> int:
    if ampm in ("오후", "PM", "pm", "Pm") and h < 12:
        return h + 12
    if ampm in ("오전", "AM", "am", "Am") and h == 12:
        return 0
    return h


def _en_date(text: str) -> date | None:
    text = text.replace(".", "")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _split_sender(rest: str) -> tuple[str, str] | None:
    if " : " not in rest:
        return None
    name, _, text = rest.partition(" : ")
    return name.strip(), text


def parse_kakao_text(text: str) -> list[dict]:
    """Parse any supported KakaoTalk text export into {dt, name, text} dicts."""
    if text.lstrip("﻿").startswith(("Date,User,Message", "Date,User,Message\r")):
        return parse_kakao_csv(text)
    messages: list[dict] = []
    current: dict | None = None
    pc_day: date | None = None

    def start(dt: datetime, name: str, body: str) -> None:
        nonlocal current
        current = {"dt": dt, "name": name, "text": body}
        messages.append(current)

    for raw in text.lstrip("﻿").splitlines():
        line = raw.rstrip("\r")
        m = KO_MOBILE.match(line)
        if m:
            y, mo, d, ampm, h, mi, rest = m.groups()
            sender = _split_sender(rest)
            if sender:
                start(datetime(int(y), int(mo), int(d), _hour(int(h), ampm), int(mi)), *sender)
            else:
                current = None  # system line (join/leave, date stamp with comma)
            continue
        m = EN_MOBILE.match(line)
        if m:
            day = _en_date(m.group(1))
            sender = _split_sender(m.group(5))
            if day and sender:
                dt = datetime(day.year, day.month, day.day, _hour(int(m.group(2)), m.group(4)), int(m.group(3)))
                start(dt, *sender)
            else:
                current = None
            continue
        m = PC_DAY.match(line)
        if m:
            pc_day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            current = None
            continue
        m = PC_DAY_EN.match(line)
        if m:
            pc_day = _en_date(m.group(1))
            current = None
            continue
        m = PC_MSG.match(line)
        if m and pc_day:
            name, ampm, h, mi, body = m.groups()
            start(datetime(pc_day.year, pc_day.month, pc_day.day, _hour(int(h), ampm), int(mi)), name, body)
            continue
        if KO_DIVIDER.match(line) or EN_DIVIDER.match(line):
            current = None
            continue
        if current is not None:
            current["text"] += "\n" + line
    for msg in messages:
        msg["text"] = msg["text"].strip()
    return [m for m in messages if m["text"]]


def parse_kakao_csv(text: str) -> list[dict]:
    messages = []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        try:
            dt = datetime.strptime((row.get("Date") or "").strip()[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        body = (row.get("Message") or "").strip()
        if body:
            messages.append({"dt": dt.replace(second=0), "name": (row.get("User") or "").strip(), "text": body})
    return messages


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_kakao_file(path: Path) -> list[dict]:
    if path.suffix.lower() == ".zip":
        messages: list[dict] = []
        try:
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if Path(name).suffix.lower() in (".txt", ".csv") and not Path(name).name.startswith("."):
                        messages.extend(parse_kakao_text(_decode(zf.read(name))))
        except zipfile.BadZipFile:
            return []
        return messages
    return parse_kakao_text(_decode(path.read_bytes()))


def message_key(msg: dict) -> str:
    raw = f"{msg['dt'].isoformat()}|{msg['name']}|{msg['text']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _files(sources: list[Path], exts: set[str]) -> list[Path]:
    out: list[Path] = []
    for src in sources:
        if src.is_file():
            if src.suffix.lower() in exts:
                out.append(src)
            continue
        if not src.is_dir():
            continue
        for path in src.rglob("*"):
            if any(part.startswith(".") for part in path.relative_to(src).parts):
                continue
            if path.suffix.lower() in exts and path.is_file():
                out.append(path)
    return sorted(out)


def new_kakao_messages(files: list[Path], state: dict, since: date | None) -> list[dict]:
    """Messages newer than state's high-water mark, deduped across files."""
    kstate = state.setdefault("kakao", {})
    last = datetime.fromisoformat(kstate["last"]) if kstate.get("last") else None
    last_keys = set(kstate.get("last_keys") or [])
    if last is None and since is None:
        since = date.today() - timedelta(days=FIRST_RUN_DAYS)

    seen: set[str] = set()
    fresh: list[dict] = []
    for path in files:
        for msg in read_kakao_file(path):
            key = message_key(msg)
            if key in seen:
                continue
            seen.add(key)
            if since and msg["dt"].date() < since:
                continue
            if last and (msg["dt"] < last or (msg["dt"] == last and key in last_keys)):
                continue
            fresh.append({**msg, "key": key})
    fresh.sort(key=lambda m: m["dt"])
    return fresh


def advance_kakao(state: dict, fresh: list[dict]) -> None:
    if not fresh:
        return
    kstate = state.setdefault("kakao", {})
    newest = fresh[-1]["dt"]
    keys = {m["key"] for m in fresh if m["dt"] == newest}
    if kstate.get("last") == newest.isoformat():
        keys |= set(kstate.get("last_keys") or [])
    kstate["last"] = newest.isoformat()
    kstate["last_keys"] = sorted(keys)


# --- Screenshots ----------------------------------------------------------
# Galaxy: Screenshot_20261007-093015_KakaoTalk.jpg (app name after the time)
# iPhone (via the Shortcut in SKILL.md): 2026-10-07 09.30.15.png
# macOS:  Screenshot 2026-10-07 at 9.30.15 PM.png / 스크린샷 2026-10-07 오후 9.30.15.png
SHOT_COMPACT = re.compile(r"(?<!\d)(20\d{6})[_-](\d{6})(?!\d)(?:[_-]([^.]+))?")
SHOT_DASHED = re.compile(r"(20\d{2})-(\d{2})-(\d{2})(?:[ _T]+(?:at\s+)?(오전|오후)?\s*(\d{1,2})[.:](\d{2})[.:](\d{2})\s*([AP]M)?)?")


def screenshot_time(path: Path) -> tuple[datetime, str | None]:
    """(taken-at, app name if the filename has one)."""
    m = SHOT_COMPACT.search(path.name)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"), m.group(3)
        except ValueError:
            pass
    m = SHOT_DASHED.search(path.name)
    if m:
        y, mo, d, ko, h, mi, s, en = m.groups()
        try:
            if h is not None:
                return datetime(int(y), int(mo), int(d), _hour(int(h), ko or en), int(mi), int(s)), None
            # Date only (e.g. a dated folder name in the file name): fall
            # through to the file timestamp but keep the stated day.
            stamp = _file_time(path)
            return datetime(int(y), int(mo), int(d), stamp.hour, stamp.minute), None
        except ValueError:
            pass
    return _file_time(path), None


def _file_time(path: Path) -> datetime:
    st = path.stat()
    return datetime.fromtimestamp(getattr(st, "st_birthtime", None) or st.st_mtime)


def shot_key(path: Path) -> str:
    st = path.stat()
    return hashlib.sha1(f"{path.name}|{st.st_size}".encode("utf-8")).hexdigest()[:16]


def viewable_path(path: Path, cache: Path) -> Path | None:
    """A path the model's image reader can open (HEIC → JPEG via macOS sips)."""
    if path.suffix.lower() in VIEWABLE:
        return path
    if shutil.which("sips") is None:
        return None
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{shot_key(path)}.jpg"
    if not out.exists():
        result = subprocess.run(
            ["sips", "-s", "format", "jpeg", str(path), "--out", str(out)],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not out.exists():
            return None
    return out


def new_screenshots(files: list[Path], state: dict, since: date | None) -> list[dict]:
    sstate = state.setdefault("screenshots", {})
    seen = set(sstate.get("seen") or [])
    # The first run fixes a floor so a sync folder holding years of old
    # screenshots never floods in later; an explicit --since overrides it.
    if "floor" not in sstate:
        sstate["floor"] = (since or date.today() - timedelta(days=FIRST_RUN_DAYS)).isoformat()
    if since is None:
        since = date.fromisoformat(sstate["floor"])
    fresh = []
    for path in files:
        key = shot_key(path)
        if key in seen:
            continue
        when, app = screenshot_time(path)
        if since and when.date() < since:
            continue
        fresh.append({"path": path, "dt": when, "app": app, "key": key})
    fresh.sort(key=lambda s: s["dt"])
    return fresh


# --- macOS Photos ---------------------------------------------------------
# With iCloud Photos on, every iPhone screenshot is already in the Mac's Photos
# library ("스크린샷" media type). osxphotos (third-party CLI) exports them with
# the capture time in the filename, which screenshot_time() parses back.
PHOTOS_FILENAME = "{created.strftime,%Y-%m-%d %H.%M.%S}"


def export_photos_screenshots(dest: Path, from_date: date) -> dict | None:
    """Export new screenshots from Photos.app into dest. Returns an error dict or None."""
    exe = shutil.which("osxphotos")
    if exe is None:
        return {"error": "osxphotos_missing", "detail": "Install with: brew install pipx && pipx install osxphotos"}
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe, "export", str(dest),
        "--screenshot",
        "--from-date", from_date.isoformat(),
        "--filename", PHOTOS_FILENAME,
        "--update",            # only new photos; state lives in dest/.osxphotos_export.db
        "--download-missing",  # originals kept only in iCloud ("Optimize Mac Storage")
        "--no-progress",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        return {"error": "photos_export_failed", "detail": " / ".join(tail)}
    return None


# --- State ----------------------------------------------------------------

def state_path(out_dir: Path) -> Path:
    return out_dir / ".daily" / "state.json"


def load_state(out_dir: Path) -> dict:
    path = state_path(out_dir)
    if not path.exists():
        return {"version": 1}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Keep the unreadable file for inspection instead of silently starting over.
        path.replace(path.with_suffix(".corrupt.json"))
        return {"version": 1}


def save_state(out_dir: Path, state: dict) -> None:
    path = state_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def add_pending(state: dict, kakao: list[dict], shots: list[dict], cache: Path) -> None:
    pending = state.setdefault("pending", {})
    for msg in kakao:
        day = pending.setdefault(msg["dt"].date().isoformat(), {})
        day.setdefault("kakao", []).append({
            "time": msg["dt"].strftime("%H:%M"),
            "name": msg["name"],
            "text": msg["text"],
        })
    for shot in shots:
        day = pending.setdefault(shot["dt"].date().isoformat(), {})
        view = viewable_path(shot["path"], cache)
        entry = {"time": shot["dt"].strftime("%H:%M"), "path": str(shot["path"])}
        if shot["app"]:
            entry["app"] = shot["app"]
        if view is None:
            entry["unviewable"] = True
        elif view != shot["path"]:
            entry["view_path"] = str(view)
        day.setdefault("screenshots", []).append(entry)
    seen = state.setdefault("screenshots", {}).setdefault("seen", [])
    seen.extend(s["key"] for s in shots)


def day_summary(day: dict) -> dict:
    kakao = day.get("kakao") or []
    urls: list[str] = []
    for msg in kakao:
        for url in URL_RE.findall(msg["text"]):
            url = url.rstrip(").,]")
            if url not in urls:
                urls.append(url)
    return {**day, "urls": urls}
