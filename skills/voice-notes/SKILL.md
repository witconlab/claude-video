---
name: voice-notes
version: "0.2.0"
description: Turn phone voice memos and lecture recordings into organized local Markdown notes. Finds new recordings in a synced folder (iPhone Voice Memos on a Mac by default), uses the phone's own transcript when there is one (iPhone Voice Memos built-in transcript, or a Galaxy Transcript assist export) and otherwise transcribes with the Whisper API, and writes one dated note per recording, either lecture notes or a daily-memo summary with to-dos. Use when the user wants recordings, voice memos, lectures, or meetings summarized or organized into notes.
argument-hint: "[file-or-folder] [lecture|daily] [--since YYYY-MM-DD]"
allowed-tools: Bash, Read, Write, Edit, Glob, AskUserQuestion
homepage: https://github.com/bradautomates/claude-video
repository: https://github.com/bradautomates/claude-video
author: bradautomates
license: MIT
user-invocable: true
---

# /voice-notes

Turns audio recordings into Markdown notes on the user's disk. A bundled script finds recordings that don't have a note yet and gets a transcript for each one. It tries these sources in order:

1. **Sidecar text file**: `<recording name>.txt` next to the audio, e.g. a Galaxy Voice Recorder *Transcript assist* export.
2. **iPhone Voice Memos built-in transcript** (iOS 18+): stored inside the `.m4a` file itself and read directly. It costs nothing and uploads nothing.
3. **Whisper API**: only for recordings that have neither of the above. It caches each transcript under `<notes>/transcripts/`, then prints a JSON manifest. You read each transcript and write the note.

## Resolve `SKILL_DIR` (do this before any command)

Set `SKILL_DIR` to the **absolute path of the directory containing this SKILL.md** (the path your harness showed when you Read it). Scripts live at `SKILL_DIR/scripts/`. Do not use any harness-specific variable such as `${CLAUDE_SKILL_DIR}`.

```bash
SKILL_DIR="<absolute path of the directory containing the SKILL.md you Read>"
[ -f "$SKILL_DIR/scripts/notes.py" ] || { echo "ERROR: scripts/notes.py not found under $SKILL_DIR" >&2; exit 1; }
```

On Windows, use `python` instead of `python3`.

## Step 0: First-run setup

The script needs `ffmpeg`/`ffprobe`. A Whisper key (`GROQ_API_KEY`, preferred, or `OPENAI_API_KEY`, read from the environment or from `~/.config/watch/.env`, the same file `/watch` uses) is needed only for recordings without a phone transcript. Without a key, those recordings come back as `needs_whisper` errors and everything else still works. If `ffmpeg` is missing, help the user install it. If a key is needed, ask for one and write it into that file (mode `0600`).

Settings, also in `~/.config/watch/.env` (bare `KEY=value` lines with no trailing comments):

| Key | Meaning | Default |
|-----|---------|---------|
| `VOICE_NOTES_SOURCE` | Folder(s) where recordings land, `:`-separated (`;` on Windows) | Mac Voice Memos folder if present |
| `VOICE_NOTES_DIR` | Where notes are written | `~/VoiceNotes` |
| `VOICE_NOTES_LANGUAGE` | Whisper language hint, e.g. `ko` | auto-detect |

If the manifest shows `output_dir_configured: false`, this is the first run. Ask with `AskUserQuestion` before writing anything:
1. **Where do recordings land?** Offer the options that fit the user's phone:
   - **iPhone + Mac**: Voice Memos syncs over iCloud on its own. Leave `VOICE_NOTES_SOURCE` unset and the script finds the folder. The terminal app may need **Full Disk Access** (System Settings → Privacy & Security) to read it.
   - **Android (Samsung Voice Recorder, etc.)**: recordings don't sync to the computer on their own. Suggest auto-uploading the recorder folder (`Recordings/Voice Recorder`) to Google Drive or OneDrive, or using Syncthing, then set `VOICE_NOTES_SOURCE` to the synced folder on the computer.
     Optional: in the recorder app, run *Transcribe* (Galaxy AI *Transcript assist*), share the transcript as a text file, and save it next to the recording under the same name with `.txt` (`음성 261007_093015.m4a` → `음성 261007_093015.txt`). The script then uses that text and skips Whisper.
   - **Both phones**: list both folders in `VOICE_NOTES_SOURCE`, separated by `:` (`;` on Windows), e.g. `VOICE_NOTES_SOURCE=~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings:~/GoogleDrive/Voice Recorder`.
   - **Manual**: the user copies files into a folder (e.g. `~/VoiceNotes/inbox`), and that folder becomes `VOICE_NOTES_SOURCE`.
2. **Where should notes go?** Default `~/VoiceNotes`. An Obsidian vault subfolder works well.
3. **Main recording language?** Set `VOICE_NOTES_LANGUAGE=ko` for Korean. A fixed hint transcribes more accurately than auto-detect.

Write the answers into `~/.config/watch/.env`, then continue.

## Step 1: Parse the request

- A file or folder path → pass it as the source (overrides `VOICE_NOTES_SOURCE`).
- `lecture` / `강의` or `daily` / `일상` / `메모` → force that note type for this run. Otherwise pick the type per recording (Step 3).
- A date ("since Monday", "오늘 것만") → `--since YYYY-MM-DD`.
- "All of them" / "전부" → `--limit 0`. The default is 5 recordings per run, which keeps a first run on a years-old Voice Memos library from transcribing everything. On a first run, run `--list` first and confirm the backlog with the user.

## Step 2: Run the script

```bash
python3 "${SKILL_DIR}/scripts/notes.py" [source ...] [--since YYYY-MM-DD] [--limit N] [--language ko]
```

Other flags: `--out DIR`, `--whisper groq|openai`, `--list` (show what would be processed and which transcript source each would use, without transcribing), `--redo` (include recordings that already have a note), `--force-whisper` (ignore phone and cached transcripts and re-transcribe with Whisper. Use it when the user says a phone transcript was poor).

Progress goes to stderr. Stdout is JSON:

```json
{
  "output_dir": "/Users/me/VoiceNotes",
  "pending": [
    {"source": "20261007 093015-1A2B.m4a", "recorded_at": "2026-10-07T09:30",
     "duration": "01:12:44", "transcript_path": ".../transcripts/2026-10-07_0930_ab12cd.txt",
     "note_dir": ".../2026-10", "note_prefix": "2026-10-07_0930",
     "transcript_source": "apple-voice-memos (ko_KR)", "empty": false}
  ],
  "remaining": 12, "already_done": 40, "errors": []
}
```

Errors to handle:
- `no_source`: ask the user where recordings land (Step 0, question 1).
- `permission_denied` on the Mac Voice Memos folder: tell the user to grant Full Disk Access to their terminal app, then rerun.
- `no_api_key` / `needs_whisper`: these recordings have no phone transcript and no key is set. Process the rest, then offer to add a key (Step 0).
- `transcribe_failed`: report it and continue with the rest. The next run retries it.

## Step 3: Write one note per pending recording

Read each `transcript_path`. Whisper and iPhone transcripts have lines like `[HH:MM:SS] text`. A `sidecar` transcript is whatever the phone exported (it may carry speaker labels like `화자 1`; keep speaker attribution in the note). Phone transcripts are usually sparser in punctuation and weaker on technical terms than Whisper. Fix obvious mis-hearings from context, and mark the unsure ones. Long lectures can be big; read in ranges if needed. Pick the type:

- **lecture**: one speaker explaining material, class/course vocabulary, usually 20+ minutes.
- **daily**: personal memos, ideas, errands, conversations, meetings.

Write `<note_dir>/<note_prefix> <short title>.md`, where the title is 2–6 words from the content (strip `/ \ : * ? " < > |`). Never overwrite an existing file; add ` (2)` instead. Write the note in the recording's language.

**Frontmatter is mandatory.** The `source:` line is how the script knows a recording is done. Without it, the recording gets transcribed again next run.

```markdown
---
source: <source filename, exactly as in the manifest>
recorded: <recorded_at>
duration: <duration>
type: lecture | daily
transcript_source: <transcript_source>
tags: [<2–5 topic tags>]
transcript: transcripts/<transcript filename>
---
```

**lecture** body:

```markdown
# <강의 제목 / 주제>

## 한눈에 보기
<3–5문장 요약>

## 목차
- [00:00:00] <섹션>
- [00:14:20] <섹션>

## 핵심 내용
### <개념/섹션>
- <설명, 예시, 공식은 그대로>

## 용어 정리
| 용어 | 뜻 |
|------|----|

## 시험·과제 포인트
- <"시험에 나온다", "중요하다", "과제" 등 강조된 부분과 공지 사항, 타임스탬프 포함>

## 다시 들어볼 부분
- [HH:MM:SS] <불명확하거나 복잡했던 부분>
```

**daily** body:

```markdown
# <제목>

## 요약
<2–4문장>

## 할 일
- [ ] <할 일> (기한이 언급됐으면 기한)

## 아이디어·메모
- <생각, 아이디어, 기억할 것>

## 일정·약속
- <날짜/시간 + 내용>  (없으면 섹션 생략)
```

Leave out sections with nothing in them; don't pad. Cite timestamps for important claims. Ground everything in the transcript. If speech is garbled or ambiguous, say so instead of guessing. Whisper can still hallucinate stray lines in silent stretches ("시청해주셔서 감사합니다" and the like). Ignore lines that clearly don't fit.

If `empty: true` (silence or noise), write a stub note: frontmatter with `type: empty` and one line saying no speech was detected.

## Step 4: Update the index and report

Append one row per new note to `<output_dir>/index.md`. Create it with this header if missing:

```markdown
| 날짜 | 유형 | 제목 | 길이 |
|------|------|------|------|
| 2026-10-07 09:30 | lecture | [자료구조 3강](2026-10/2026-10-07_0930%20자료구조%203강.md) | 01:12:44 |
```

Then tell the user briefly which notes you created (title + path), every open to-do collected across the daily notes, and whether `remaining` > 0 (run again, or with `--limit 0`, to keep going). Don't paste whole notes into chat.

## Running it every day

The skill only runs when invoked. For a daily automatic pass, the user can schedule a headless run, e.g. macOS/Linux cron at 23:00:

```cron
0 23 * * * cd ~ && claude -p "/voice-notes" --allowedTools "Bash Read Write Edit Glob" >> ~/VoiceNotes/.cron.log 2>&1
```

Set this up only when the user asks, and show them the line before installing it.
