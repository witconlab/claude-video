# Changelog

All notable changes to `/watch` and `/edit` are documented here.

## [0.3.0] — 2026-09-08

### Added
- **`/edit` skill** — a second, independent self-contained skill (`skills/edit/`) that edits a local video file purely via local `ffmpeg`. No downloads, no cloud calls, no API keys, no config file. Fourteen operations, each a subcommand of `scripts/edit.py`:
  - `trim` — cut a segment (`--start`/`--end`/`--duration`; fast stream-copy by default, `--exact` for frame-accurate re-encode with automatic fallback if stream-copy fails)
  - `concat` — merge multiple videos in order; tries the fast concat-demuxer stream-copy path first, falling back to a re-encode that normalizes resolution/fps when sources differ
  - `compress` — CRF/preset encode, or a two-pass encode targeting `--target-size-mb`
  - `speed` — change playback speed with pitch-corrected audio (arbitrary factors via a chained `atempo` filter)
  - `volume`, `mute` — adjust or strip the audio track
  - `watermark` — text (via a temp file passed to `drawtext`, avoiding filter-string escaping) or image overlay, at any corner or center
  - `subtitles` — burn in (hardsub) or `--embed` as a toggleable track from `.srt`/`.vtt`/`.ass`
  - `gif` — palette-quantized GIF of the whole clip or a `--start`/`--end` segment
  - `resize`, `crop`, `rotate` — geometry operations
  - `extract-audio` — pull the audio track to `mp3`/`aac`/`wav`/`m4a`
  - `thumbnail` — grab a single frame as a JPEG at a timestamp
  - Every operation writes a new output file (default: alongside the input with a suffix) rather than overwriting the source.
- `skills/edit/scripts/setup.py` — a much smaller preflight/installer than watch's: checks for `ffmpeg`/`ffprobe` only, no API keys or `.env` to manage.
- `skills/edit/scripts/build-skill.sh` and the release workflow now also produce `dist/edit.skill` for claude.ai web uploads.
- SessionStart hook reports `/edit` readiness (ffmpeg-only) alongside `/watch`'s.
- pytest suite (`tests/test_edit.py`) covering every operation against ffmpeg-synthesized clips, plus a shared `audio_clip` fixture in `conftest.py`.

### Changed
- Both skills now ship under the single `watch` Claude Code plugin (`skills: "./skills/"` picks up every self-contained skill folder); install instructions cover both.

## [0.2.0] — 2026-06-29

### Added
- **`--detail` dial** with four modes — `transcript` (captions only, no frames), `efficient` (fast keyframe pass, cap 50), `balanced` (scene-aware, cap 100, default), and `token-burner` (scene-aware, uncapped). Set the default with `WATCH_DETAIL` in `~/.config/watch/.env`.
- **Frame deduplication** (default on; `--no-dedup` to disable). Before the budget cap, a pass downscales each frame to a 16×16 grayscale thumbnail and drops frames whose mean per-pixel difference from the last *kept* frame is within threshold — so the budget goes to distinct content instead of held slides and static recordings. The **Frames** report line shows how many near-duplicates were dropped.
- **Whisper auto-chunking.** Audio over the 25 MB upload cap is split into evenly sized chunks, transcribed per chunk, with segment timestamps shifted back into source time. Partial failures are tolerated — transcription only fails if *every* chunk fails, so length alone no longer breaks it.
- **`--timestamps T1,T2,…`** — grab a frame at each absolute timestamp; reserved against the cap, and the only frames produced under `--detail transcript`.
- **`--no-whisper`** — disable transcription entirely (frames only).
- pytest suite covering config, dedup, download, fixtures, frames, setup, timestamps, watch, and whisper (no network; ffmpeg-synthesized clips).

### Changed
- **Restructured into a self-contained `skills/watch/` package** so `SKILL.md` and its `scripts/` runtime are siblings in one folder. This fixes installs on Codex, Cursor, Copilot, and other Agent Skills hosts: `npx skills add` now copies the skill as a working unit instead of grabbing the root `SKILL.md` without its scripts.
- **Harness-agnostic path resolution** — `SKILL.md` resolves `$SKILL_DIR` from where it was Read instead of the Claude-Code-only `${CLAUDE_SKILL_DIR}`, so script calls work on every host.
- `/watch` is now derived from `SKILL.md` frontmatter; the separate `commands/watch.md` wrapper was dropped to avoid a duplicate slash command.
- `balanced` now full-decodes to detect every scene cut across the whole video. The previous early-exit was faster but kept only the first cuts and dropped the tail of long videos.
- `token-burner` is exempt from the long-video "sparse scan" warning, since it keeps every scene-change frame.
- `--max-frames` is now an override on top of each mode's default cap, rather than a fixed default of 80.

### Fixed
- Non-Claude installs (`npx skills add`) were dead on arrival — the installer copied `SKILL.md` without the `scripts/` it shells out to. The self-contained package layout resolves this.

### Removed
- `V2_PLAN.md` and `V2_CONCERNS.md` planning docs.

## [0.1.3] — 2026-05-09

### Fixed
- Windows: `video.info.json` is read as UTF-8 (#4). Previously `Path.read_text()` defaulted to cp1252 on Windows and crashed on yt-dlp's UTF-8 output, silently dropping Title/Uploader from the report. Same fix applied to `.env` reads/writes in `whisper.py` and `setup.py`.
- `download.py` now logs info.json parse failures to stderr instead of swallowing them.

### Security
- Hardened subprocess argv against option injection (#2): inserted `--` before the URL in the yt-dlp argv, and tightened `is_url` to reject `-`-prefixed sources and require a non-empty netloc. Resolved video/audio paths to absolute via `Path.resolve()` before passing to `ffmpeg`/`ffprobe`, so a relative path starting with `-` can't be misinterpreted as a flag.

## [0.1.2] — 2026-04-24

### Fixed
- Windows console crash: removed the emoji from the long-video warning in `watch.py`; cp1252 consoles couldn't encode it.
- `setup.py` now prints `winget` / `pip` install commands on Windows instead of "unsupported platform" — matches what the README already promised.

### Changed
- `SKILL.md` notes that on Windows the scripts must be invoked with `python`, not `python3` (the latter is the Microsoft Store stub on Windows).

## [0.1.1] — 2026-04-24

### Fixed
- Added `commands/watch.md` shim so `/watch` is callable when installed as a Claude Code plugin. Without it, the plugin loaded but the skill wasn't exposed as a slash command.
- `scripts/build-skill.sh` now strips `commands/` from the claude.ai `.skill` bundle alongside `hooks/` and `.claude-plugin/`.

## [0.1.0] — 2026-04-24

Initial marketplace release.

### Added
- `/watch <url-or-path> [question]` slash command.
- yt-dlp download with native caption extraction (manual + auto-subs).
- ffmpeg frame extraction with auto-scaled fps (≤2 fps, ≤100 frames, duration-aware budget).
- `--start` / `--end` focused mode with denser frame budget and transcript range filtering.
- Whisper fallback (Groq preferred, OpenAI secondary) for videos without captions.
- `setup.py` preflight: silent `--check`, structured `--json`, and installer that auto-runs `brew install` on macOS.
- Session-start hook that prints a one-line status on first run / partial config.
- `.skill` bundle packaging for claude.ai upload via `scripts/build-skill.sh`.
