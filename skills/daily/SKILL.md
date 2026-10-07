---
name: daily
version: "0.2.0"
description: Organize the day's captured material into local Markdown notes. Collects voice memos and lecture recordings (iPhone Voice Memos, Galaxy Voice Recorder; uses the phone's own transcript or Whisper), KakaoTalk "chat with myself" exports, and screenshots from both phones. Writes one note per recording plus a daily note that sorts everything into things to study, interests, links, and to-dos, and keeps a running learning queue. Use when the user wants their recordings, memos-to-self, or screenshots summarized or organized.
argument-hint: "[file ...] [--since YYYY-MM-DD] [--only recordings|kakao|screenshots]"
allowed-tools: Bash, Read, Write, Edit, Glob, WebFetch, AskUserQuestion
homepage: https://github.com/bradautomates/claude-video
repository: https://github.com/bradautomates/claude-video
author: bradautomates
license: MIT
user-invocable: true
---

# /daily

The user captures things all day in three ways: voice recordings (lectures, memos), KakaoTalk messages sent to themselves (나와의 채팅), and screenshots of things to look into later. `/daily` collects whatever is new from all three and turns it into notes on their disk:

```
<DAILY_DIR>/                         (default ~/Daily)
├── daily/2026-10-07.md              ← one note per day (Step 4)
├── recordings/2026-10/…md           ← one note per recording (Step 3)
├── learning-queue.md                ← running list of things to study (Step 5)
├── index.md                         ← table of recording notes
├── transcripts/                     ← cached transcripts
└── .daily/state.json                ← what has been collected (don't edit)
```

## Resolve `SKILL_DIR` (do this before any command)

Set `SKILL_DIR` to the **absolute path of the directory containing this SKILL.md** (the path your harness showed when you Read it). Scripts live at `SKILL_DIR/scripts/`. Do not use any harness-specific variable such as `${CLAUDE_SKILL_DIR}`.

```bash
SKILL_DIR="<absolute path of the directory containing the SKILL.md you Read>"
[ -f "$SKILL_DIR/scripts/daily.py" ] || { echo "ERROR: scripts/daily.py not found under $SKILL_DIR" >&2; exit 1; }
```

On Windows, use `python` instead of `python3`.

## Step 0: First-run setup

Requirements: `ffmpeg`/`ffprobe` (for recordings). A Whisper key (`GROQ_API_KEY`, preferred, or `OPENAI_API_KEY`) is needed only for recordings without a phone transcript. The script reads keys and settings from the environment or from `~/.config/watch/.env` (shared with `/watch`; mode `0600`; bare `KEY=value` lines, no trailing comments).

| Key | Meaning | Default |
|-----|---------|---------|
| `DAILY_DIR` | Where notes go | `~/Daily` |
| `DAILY_RECORDINGS` | Recording folder(s) | Mac Voice Memos folder if present |
| `DAILY_KAKAO` | Folder(s) where KakaoTalk exports are saved | `iCloud Drive/Daily Inbox/kakao` on a Mac, else `<DAILY_DIR>/inbox/kakao` |
| `DAILY_SCREENSHOTS` | Screenshot folder(s) | `iCloud Drive/Daily Inbox/screenshots` on a Mac, else `<DAILY_DIR>/inbox/screenshots` |
| `DAILY_PHOTOS` | `true` → pull screenshots out of the Mac Photos library each run (needs `osxphotos`) | off |
| `DAILY_LANGUAGE` | Whisper language hint, e.g. `ko` | auto-detect |

Separate multiple folders with `:` (`;` on Windows). The older `VOICE_NOTES_DIR` / `VOICE_NOTES_SOURCE` / `VOICE_NOTES_LANGUAGE` names still work.

If the manifest shows `output_dir_configured: false`, this is the first run. Ask (with `AskUserQuestion`) only what you can't infer, then write the answers into `~/.config/watch/.env`. Walk the user through whichever of these capture routes they use:

**Recordings**
- *iPhone + Mac*: Voice Memos syncs over iCloud (turn on iCloud → Voice Memos on both devices). Leave `DAILY_RECORDINGS` unset. The app running the agent needs **Full Disk Access** (System Settings → Privacy & Security → Full Disk Access; open it directly with `open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"`), then a full restart of that app.
- *Galaxy*: auto-upload `Recordings/Voice Recorder` to Google Drive with a sync app (FolderSync, Autosync for Google Drive) or Syncthing, and add the synced Mac folder to `DAILY_RECORDINGS`. If the user runs *Transcript assist* and saves the transcript as `<recording name>.txt` next to the audio, Whisper is skipped.

**KakaoTalk 나와의 채팅**: there is no API, so the user exports the chat once a day. Each export is the whole history; the script only takes messages newer than the last run, so overlapping exports are fine.
- *Mac KakaoTalk* (easiest): open 나와의 채팅 → menu (≡) → 대화 내보내기 (wording varies a little by version). Save the file into the `DAILY_KAKAO` folder.
- *Phone*: 나와의 채팅 → ≡ → ⚙︎ 설정 → 대화 내용 내보내기 → 텍스트만 보내기. On iPhone choose "파일에 저장" → iCloud Drive → Daily Inbox → kakao. On Galaxy, save to the synced Drive folder.
- `.txt`, `.csv` and `.zip` exports from Android, iOS, Windows and Mac (Korean or English UI) are all understood. Photos sent to the chat appear only as "사진".

**Screenshots**
- *iPhone + Mac (recommended)*: with iCloud Photos on, every iPhone screenshot is already in the Mac's Photos library (the 스크린샷 media type). Set `DAILY_PHOTOS=true` and install [osxphotos](https://github.com/RhetTbull/osxphotos) (`brew install pipx && pipx install osxphotos`). Each run then exports new screenshots into `<DAILY_DIR>/inbox/photos-screenshots/`, named by capture time, so each one lands on the right day. Nothing to do on the phone. Checks:
  - The app running the agent needs Full Disk Access (the Photos library is protected).
  - iCloud Photos must actually be syncing. If the iPhone's 사진 → 모음 shows **동기화가 일시 정지됨** (low battery or Low Power Mode), tap it to resume, or new screenshots won't reach the Mac.
  - `photos_export_failed` usually means Full Disk Access is missing or Photos needs to be opened once.
- *iPhone without that*: a Shortcuts automation copies the day's screenshots into iCloud Drive. Shortcuts → 자동화 → `+` → 특정 시간 (e.g. 23:30, 매일, **즉시 실행**) → actions: **사진 찾기** (*스크린샷임* is true, *촬영일* is *오늘*) → **각 항목을 반복** { **날짜 포맷** of the item's *촬영일* with custom format `yyyy-MM-dd HH.mm.ss` → **이름 변경** the item to that text → **파일 저장** to iCloud Drive/Daily Inbox/screenshots, *저장 위치 묻기* off }. The rename keeps the capture time. Without it every screenshot is dated by when the shortcut ran. Use either this or `DAILY_PHOTOS`, not both, or screenshots get collected twice.
- *Galaxy*: sync `DCIM/Screenshots` (or `Pictures/Screenshots`) the same way as recordings, and add that folder to `DAILY_SCREENSHOTS`. Galaxy names screenshots `Screenshot_YYYYMMDD_HHMMSS_<App>.jpg`, so you'll also know which app each came from.

The first run only collects the last 7 days of KakaoTalk messages and screenshots. Pass `--since YYYY-MM-DD` to reach further back. To organize an existing screenshot backlog by date, go a month at a time (`--only screenshots --since 2026-09-01`), because every screenshot is an image you have to look at. Each day still gets its own daily note.

## Step 1: Parse the request

- File paths → pass them. Audio goes to recordings, `.txt/.csv/.zip` to KakaoTalk, images to screenshots.
- "녹음만", "카톡만", "스크린샷만" → `--only recordings|kakao|screenshots` (repeatable).
- A date → `--since YYYY-MM-DD`. "녹음 전부" → `--limit 0` (recordings default to 5 per run).
- To preview without changing anything, use `--list`.

## Step 2: Run the collector

```bash
python3 "${SKILL_DIR}/scripts/daily.py" [file ...] [--since YYYY-MM-DD] [--only …] [--limit N] [--list]
```

Recording-only flags: `--language ko`, `--whisper groq|openai`, `--redo`, `--force-whisper` (ignore the phone transcript, e.g. when it was poor). Progress goes to stderr; stdout is JSON:

```json
{
  "output_dir": "/Users/me/Daily",
  "learning_queue": "/Users/me/Daily/learning-queue.md",
  "recordings": {"remaining": 0, "already_done": 40, …},
  "kakao": {"export_files": 1, "new_messages": 6, "last_collected": "2026-10-07T21:40:00"},
  "screenshots": {"new": 9},
  "days": {
    "2026-10-07": {
      "recordings": [{"source": "20261007 093015-1A2B.m4a", "transcript_path": "…", "note_dir": "…/recordings/2026-10",
                      "note_prefix": "2026-10-07_0930", "transcript_source": "apple-voice-memos (ko_KR)", "empty": false, …}],
      "kakao": [{"time": "09:05", "name": "나", "text": "https://… 나중에 읽기"}],
      "screenshots": [{"time": "10:10", "path": "…/Screenshot_20261007_101010_Chrome.jpg", "app": "Chrome"}],
      "urls": ["https://…"],
      "daily_note": "/Users/me/Daily/daily/2026-10-07.md",
      "note_exists": false
    }
  },
  "errors": []
}
```

`days` holds everything not yet covered by a daily note, including items left over from an earlier run that stopped midway. Process every day listed.

Errors:
- `no_kakao_export`: nothing exported yet. Remind the user of the daily export (Step 0) and carry on.
- `permission_denied`: Full Disk Access (Step 0).
- `no_api_key` / `needs_whisper`: some recordings need Whisper and no key is set. Do the rest, then offer to add a key.
- `transcribe_failed`: report it; the next run retries it.

## Step 3: One note per recording

For each `days[*].recordings[*]`: read `transcript_path`. Whisper and iPhone transcripts look like `[HH:MM:SS] text`. A `sidecar` transcript is whatever the phone exported, possibly with speaker labels such as `화자 1`; keep who said what. Phone transcripts have less punctuation and more mis-heard technical terms than Whisper. Fix the obvious ones from context and mark the uncertain ones. Read long lectures in ranges.

Pick the type:
- **lecture**: one speaker teaching material, usually 20+ minutes.
- **memo**: personal memos, ideas, errands, conversations, meetings.

Write `<note_dir>/<note_prefix> <2–6 word title>.md` (strip `/ \ : * ? " < > |`). Never overwrite an existing file; add ` (2)` instead. Write in the recording's language. **The frontmatter is mandatory.** The `source:` line is how the next run knows this recording is done.

```markdown
---
source: <source, exactly as in the manifest>
recorded: <recorded_at>
duration: <duration>
type: lecture | memo
transcript_source: <transcript_source>
tags: [<2–5 topic tags>]
transcript: ../../transcripts/<transcript filename>
---
```

Lecture body: `## 한눈에 보기` (3–5 sentences) · `## 목차` (`- [HH:MM:SS] 섹션`) · `## 핵심 내용` (per concept; keep formulas and examples) · `## 용어 정리` (table) · `## 시험·과제 포인트` (anything stressed as important, exams, homework, announcements, with timestamps) · `## 다시 들어볼 부분`.

Memo body: `## 요약` · `## 할 일` (`- [ ]`, with any deadline) · `## 아이디어·메모` · `## 일정·약속`.

Leave out empty sections. Ground everything in the transcript and cite timestamps. Ignore stray Whisper hallucinations in silent stretches ("시청해주셔서 감사합니다"). If `empty: true`, write a stub with `type: empty` and one line saying no speech was detected.

Append a row per recording note to `index.md`, creating it if missing:

```markdown
| 날짜 | 유형 | 제목 | 길이 |
|------|------|------|------|
| 2026-10-07 09:30 | lecture | [자료구조 3강](recordings/2026-10/2026-10-07_0930%20자료구조%203강.md) | 01:12:44 |
```

## Step 4: The daily note

For each day in `days`:

1. **Look at every screenshot.** Read `view_path` if present, else `path`, about 10 per batch. Skip entries marked `unviewable` but mention the count. For each one, work out what it is (article, post, product, code, lecture slide, chat, map, schedule…) and why the user probably saved it. Don't copy passwords, card or account numbers, verification codes, or other people's private details into the note. Describe such a screenshot generically ("결제 화면").
2. **Read the KakaoTalk messages.** Messages from the same few minutes are often one thought: group them. "사진", "동영상", and "파일: …" are attachments the export can't include. Note them only if the surrounding text gives them meaning.
3. **Links**: for the day's `urls`, if WebFetch is available, fetch up to ~10 and write one line on what each is. If a fetch fails, keep the bare link and don't guess. Skip links already summarized in an existing note.
4. **Recordings**: link the notes you wrote in Step 3.

Write or update `daily_note`. If `note_exists`, **add** the new items to the existing sections. Don't rewrite or delete what's there (the user may have edited it). Use the user's language. Omit empty sections:

```markdown
---
date: 2026-10-07
sources: {kakao: 6, screenshots: 9, recordings: 1}
---
# 2026-10-07 (화)

## 한 줄 요약
<what this day's captures were mostly about>

## 📚 공부할 것
- **Rust 소유권** — 블로그 글 스크린샷 (Chrome, 10:10) + 카톡 링크 [제목](url): <한 줄 요약>

## 💡 관심사·아이디어
- …

## 🔗 링크
- [제목](url) — <한 줄 요약> (카톡 09:05)

## ✅ 할 일
- [ ] 장보기: 우유, 계란 (카톡 12:30)

## 📅 일정
- …

## 🎙 녹음
- [[2026-10-07_0930 자료구조 3강]] — 강의, 1시간 12분

## 🖼 스크린샷 모음
- 10:10 Chrome: Rust 소유권 설명 글 → 공부할 것
- 14:22 인스타그램: 카페 추천 게시물 → 관심사
```

Merge items that are about the same thing (a screenshot of an article plus a KakaoTalk link to it is one entry). Each item says where it came from (카톡 time, screenshot app/time, recording).

**Then mark the day done** (only after the note is saved):

```bash
python3 "${SKILL_DIR}/scripts/daily.py" --mark-noted 2026-10-07 [more days …]
```

If you skip this, the same KakaoTalk messages and screenshots come back next run.

## Step 5: Learning queue

Append each new "공부할 것" item to `learning_queue`, creating it with `# 학습 목록` if missing: `- [ ] <주제> — <source/link> (from [[YYYY-MM-DD]])`. Before adding, check for an existing open item on the same topic; if there is one, append the new source to it instead of duplicating. Never remove or uncheck items. The user checks them off.

## Step 6: Report

Tell the user briefly: per day, how many recordings, messages, and screenshots went in; the notes created (paths); the new 할 일 and 공부할 것 items; and anything that needs them (no KakaoTalk export today, `remaining` recordings, missing key). Don't paste whole notes into chat.

## Running it every day

The skill runs only when invoked. For an automatic nightly pass after the iPhone Shortcut (e.g. 23:30), schedule a headless run at 23:45 with cron:

```cron
45 23 * * * cd ~ && claude -p "/daily" --allowedTools "Bash Read Write Edit Glob WebFetch" >> ~/Daily/.cron.log 2>&1
```

On macOS, `/usr/sbin/cron` also needs **Full Disk Access** (System Settings → Privacy & Security → Full Disk Access → `+` → ⌘⇧G → `/usr/sbin/cron`). Otherwise scheduled runs fail with `permission_denied` while manual runs work. The Mac must be awake at that time. The KakaoTalk export stays a manual step. If it's missed, the next export catches up, since the script only takes messages newer than the last run.

Set this up only when the user asks, and show them the line before installing it.
