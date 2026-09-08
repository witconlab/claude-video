---
name: edit
version: "0.1.0"
description: Edit a local video file — trim, merge, compress, change speed, adjust volume, mute, watermark, burn in subtitles, convert to GIF, resize, crop, rotate, extract audio, or grab a thumbnail. Wraps ffmpeg directly; no cloud calls, no API keys.
argument-hint: "<video-path> <what to do>"
allowed-tools: Bash, AskUserQuestion
homepage: https://github.com/bradautomates/claude-video
repository: https://github.com/bradautomates/claude-video
author: bradautomates
license: MIT
user-invocable: true
---

# /edit

You don't have a way to modify a video file; this skill gives you one. A
Python script wraps `ffmpeg` to perform one editing operation at a time —
trim, merge, compress, change speed, adjust volume, mute, watermark, burn in
or embed subtitles, convert to GIF, resize, crop, rotate, extract audio, or
grab a thumbnail frame. Everything runs locally: no cloud calls, no API
keys, no upload of the video anywhere.

This skill only edits **local files**. If the user gives you a URL, use
`/watch` first to download it (or download it yourself), then edit the
downloaded file.

## Resolve `SKILL_DIR` (do this before any command)

Every `python3 ...` command below runs a bundled script under
`SKILL_DIR/scripts/`. Set `SKILL_DIR` to the **absolute path of the
directory containing THIS SKILL.md you just Read** — your harness told you
that path in the Read result. The scripts are always a direct sibling of
this file (`SKILL_DIR/scripts/edit.py`), in every install layout:

```
Read ~/.claude/plugins/cache/claude-video/watch/<ver>/skills/edit/SKILL.md → SKILL_DIR=…/skills/edit
Read ~/.codex/skills/edit/SKILL.md                                         → SKILL_DIR=~/.codex/skills/edit
Read ~/.agents/skills/edit/SKILL.md                                        → SKILL_DIR=~/.agents/skills/edit
```

Substitute that literal path for `${SKILL_DIR}` in every command. Guard once
at the start of a run:

```bash
SKILL_DIR="<absolute path of the directory containing the SKILL.md you Read>"
if [ ! -f "$SKILL_DIR/scripts/edit.py" ]; then
  echo "ERROR: scripts/edit.py not found under SKILL_DIR=$SKILL_DIR" >&2
  exit 1
fi
```

**Python interpreter:** every `python3 ...` command is for macOS/Linux. On
**Windows**, substitute `python`.

## Step 0 — Setup preflight (silent on success)

`/edit` only needs `ffmpeg`/`ffprobe` — no API keys, no config file. Check
once per session:

```bash
python3 "${SKILL_DIR}/scripts/setup.py" --check
```

Exit 0 → nothing to do, proceed silently. Non-zero (`2`) → binaries are
missing; run the installer and confirm it lands before proceeding:

```bash
python3 "${SKILL_DIR}/scripts/setup.py"
```

On macOS with Homebrew this auto-installs `ffmpeg`. On Linux/Windows it
prints the exact install command for the user to run themselves.

## When to use

- User has a local video file and asks to cut, trim, merge, compress,
  speed up/slow down, mute, adjust volume, watermark, caption/burn
  subtitles, convert to GIF, resize, crop, rotate, or extract audio from it.
- User types `/edit <path> <what to do>`.
- Not for analyzing/understanding a video's content — that's `/watch`. Use
  `/edit` only when the user wants the video file itself changed.

## How to invoke

**Step 1 — figure out the operation and parameters from what the user
asked**, e.g. "cut the first 10 seconds off" → `trim` with `--start 10`;
"make it a GIF of the intro" → `gif` with `--start`/`--end`; "compress this
for email" → `compress` with a `--target-size-mb`. If the request is
ambiguous (e.g. "edit this video" with no specifics), ask what they want
done rather than guessing.

**Step 2 — run the script:**

```bash
python3 "${SKILL_DIR}/scripts/edit.py" <operation> <input> [options] [--out <path>]
```

`--out` is optional — every operation defaults to writing next to the input
file with a suffix (e.g. `clip.mp4` → `clip_trim.mp4`), never overwriting
the original.

**Step 3 — report the result.** The script prints a short report with the
output path, before/after duration, resolution, and file size, plus any
notes (e.g. a stream-copy speed/accuracy tradeoff). Relay the output path
to the user; do not re-encode or re-run unless they ask for a change.

### Operations

| Operation | Purpose | Key options |
|---|---|---|
| `trim` | Cut a segment out | `--start`, `--end` or `--duration`, `--exact` (frame-accurate re-encode; default is fast stream-copy snapped to keyframes) |
| `concat` | Merge multiple videos in order | positional extra inputs after the first, `--width`/`--height` to force a resolution when sources differ |
| `compress` | Shrink file size | `--crf` (18=near-lossless … 28=default … 35=small), `--preset`, or `--target-size-mb` for a two-pass encode |
| `speed` | Change playback speed | `--factor` (e.g. `2.0`, `0.5`); audio pitch-corrected by default |
| `volume` | Adjust audio level | `--db` (e.g. `6`, `-10`) or `--factor` (e.g. `1.5`) |
| `mute` | Strip the audio track | — |
| `watermark` | Overlay text or an image | `--text` or `--image`, `--position` (`tl`/`tr`/`bl`/`br`/`center`) |
| `subtitles` | Burn in or embed captions | `--srt <file>` (.srt/.vtt/.ass), `--embed` for a toggleable track instead of hardsub |
| `gif` | Convert (a segment) to an optimized GIF | `--start`, `--end`, `--fps` (default 10), `--width` (default 480) |
| `resize` | Change resolution | `--width`/`--height` (either alone keeps aspect) or `--scale` |
| `crop` | Crop to a region | `--width`, `--height`, `--x`, `--y` |
| `rotate` | Rotate 90/180/270° | `--degrees`, `--ccw` for counter-clockwise |
| `extract-audio` | Pull the audio track out | `--format` (`mp3`/`aac`/`wav`/`m4a`) |
| `thumbnail` | Grab a single frame as JPEG | `--at <timestamp>` |

Every operation accepts `--out <path>` to control the output location.

### Examples

```bash
# Cut 0:10–0:25 out of a clip
python3 "${SKILL_DIR}/scripts/edit.py" trim video.mp4 --start 10 --end 25

# Merge three clips in order
python3 "${SKILL_DIR}/scripts/edit.py" concat part1.mp4 part2.mp4 part3.mp4

# Compress for email, aiming for ~10MB
python3 "${SKILL_DIR}/scripts/edit.py" compress video.mp4 --target-size-mb 10

# 2x speed with pitch-corrected audio
python3 "${SKILL_DIR}/scripts/edit.py" speed video.mp4 --factor 2.0

# Burn in subtitles from an SRT
python3 "${SKILL_DIR}/scripts/edit.py" subtitles video.mp4 --srt captions.srt

# GIF of the first 3 seconds
python3 "${SKILL_DIR}/scripts/edit.py" gif video.mp4 --start 0 --end 3 --width 400
```

### Chaining operations

Each operation writes a new file rather than mutating in place, so chained
edits (e.g. trim, then watermark, then compress) are three script calls,
each fed the previous step's output path.

## Failure modes and handling

- **Setup preflight failed** → run `python3 "${SKILL_DIR}/scripts/setup.py"`
  (auto-installs `ffmpeg` via brew on macOS; prints the command elsewhere).
- **Input not found / not a video** → the script errors immediately with the
  resolved path it looked for. Confirm the path with the user rather than
  guessing an alternative.
- **`trim`/`concat` stream-copy fails** → the script automatically falls
  back to a re-encode and notes it in the report; no action needed.
- **`concat` sources have different resolutions/codecs** → the fast
  stream-copy path is skipped automatically and the script re-encodes,
  normalizing every input to a common resolution (the largest among them,
  or `--width`/`--height` if given).
- **Output file already exists** → operations never overwrite; a numeric
  suffix (`_2`, `_3`, …) is added automatically unless `--out` is given
  explicitly (which does overwrite).

## Security & Permissions

**What this skill does:**
- Runs `ffmpeg` / `ffprobe` locally against the file(s) you point it at
- Writes one new output file per operation, next to the input by default
  (or at `--out`)
- For `watermark --text`, writes the text to a temporary file passed to
  ffmpeg's `drawtext` filter (avoids shell/filter-string escaping issues)
  and removes it afterward

**What this skill does NOT do:**
- Does not upload video, audio, or any file content anywhere — everything
  is local `ffmpeg`/`ffprobe` execution
- Does not read or write any config file or API key — there is none to manage
- Does not overwrite the input file — every operation produces a new output
- Does not touch remote URLs — point `/watch` at a URL first if you need to
  download before editing

**Bundled scripts:** `scripts/edit.py` (entry point + all operations),
`scripts/ffmpeg_utils.py` (probe, time parsing, filter-string escaping),
`scripts/setup.py` (preflight + installer)

Review scripts before first use to verify behavior.
