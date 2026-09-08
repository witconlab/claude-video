# claude-video / watch + edit skills

Agent Skills package that gives an agent a video input (`/watch`) and a video editor (`/edit`). Installable across Claude Code (most common host), Codex, Cursor, GitHub Copilot, and 50+ other [Agent Skills](https://agentskills.io) hosts. Pure-stdlib Python that orchestrates `yt-dlp` + `ffmpeg` (and an optional Whisper API for `/watch`).

## Structure

- `skills/watch/SKILL.md` — canonical skill contract the model reads when `/watch` fires. Source of truth for behavior across every host.
- `skills/watch/scripts/watch.py` — entry point; orchestrates download → frames → transcript.
- `skills/watch/scripts/{download,frames,transcribe,whisper,setup,config}.py` — yt-dlp wrapper, ffmpeg frame extraction + auto-fps, caption/Whisper transcription, preflight/installer, shared config.
- `skills/watch/scripts/build-skill.sh` — builds `dist/watch.skill` for claude.ai upload (dev-only).
- `skills/edit/SKILL.md` — canonical skill contract the model reads when `/edit` fires. Edits a **local** video file (trim, merge, compress, speed, volume, mute, watermark, subtitles, GIF, resize, crop, rotate, extract-audio, thumbnail) purely via local `ffmpeg` — no API keys, no config file.
- `skills/edit/scripts/edit.py` — entry point; argparse subcommand per operation, each shelling out to `ffmpeg`/`ffprobe`.
- `skills/edit/scripts/ffmpeg_utils.py` — shared probe/time-parsing/filter-escaping helpers.
- `skills/edit/scripts/setup.py` — preflight/installer for `ffmpeg`/`ffprobe` only (much smaller than watch's — no keys, no `.env`).
- `hooks/` — Claude Code SessionStart setup-status hook (Claude Code only; reports both `/watch` and `/edit` readiness).
- `.claude-plugin/` — `plugin.json` + `marketplace.json` (Claude Code plugin + local marketplace). Both skills ship under the single `watch` plugin.
- `.codex-plugin/plugin.json` — Codex/agents manifest; `"skills": "./skills/"` points the Agent Skills CLI at the self-contained skill folders (picks up both `watch/` and `edit/`).
- `.agents/plugins/marketplace.json` — agents marketplace listing pointing at the repo-root plugin.
- `CLAUDE.md` → `@AGENTS.md` — generic-agent entry point.
- `tests/` — pytest suite (ffmpeg-synthesized clips; no network).

## Orientation

- The product is the slash-command-invoked skills (`/watch <url-or-path> [question]`, `/edit <path> <what to do>`), not a CLI. `scripts/watch.py` / `scripts/edit.py` are implementation. Features must work across every harness the skill installs into, not just Claude Code.
- **Each skill is one self-contained folder: `skills/watch/`, `skills/edit/`.** SKILL.md and `scripts/` are siblings inside each. This is what lets `npx skills add` copy a working skill as a unit — do NOT move a SKILL.md or its `scripts/` back to the repo root, or non-Claude installers will copy SKILL.md without the scripts. The two skills are independent — neither imports the other's `scripts/` — so either can be installed/copied alone.
- **Path resolution is harness-agnostic.** Each SKILL.md resolves `SKILL_DIR` as the directory of the SKILL.md the model just Read, then runs `${SKILL_DIR}/scripts/...`. Do NOT reintroduce `${CLAUDE_SKILL_DIR}` (Claude-Code-only) — it is unset on Codex/Cursor/agents and breaks every script call there.
- **No `commands/` wrapper.** `/watch` and `/edit` are derived from each SKILL.md's frontmatter (`name:` + `user-invocable: true`). A separate command file creates a duplicate slash command.
- **`/watch` analyzes, `/edit` modifies.** `/watch` downloads/reads a video (URL or local) and answers questions about it. `/edit` only touches local files and always writes a new output rather than mutating the input — it never downloads anything itself (point `/watch` at a URL first if the source isn't local yet).

## Install surfaces

| Surface | Install |
|---------|---------|
| Claude Code | `/plugin marketplace add bradautomates/claude-video` then `/plugin install watch@claude-video` |
| Codex / Cursor / Copilot / +50 | `npx skills add bradautomates/claude-video -g` |
| claude.ai (web) | upload `dist/watch.skill` (built by `skills/watch/scripts/build-skill.sh`) |

## Commands

```bash
# Tests (stdlib + pytest; ffmpeg required for frame tests)
.venv/bin/pytest -q                # or: python3 -m pytest -q

# Build the claude.ai upload bundle (archives skills/watch/ as the bundle root)
bash skills/watch/scripts/build-skill.sh   # → dist/watch.skill

# Dev: mirror the working tree into the installed Claude Code plugin cache
./dev-sync.sh                       # --dry-run to preview
```

## Rules

- Keep the version in sync across `skills/watch/SKILL.md` (frontmatter), `.claude-plugin/plugin.json`, and `.codex-plugin/plugin.json` when cutting a release.
- Releasing: tag `vX.Y.Z` and push the tag; `.github/workflows/release.yml` builds `dist/watch.skill` and attaches it to the GitHub release.
- Never commit real API keys or `.env` contents; keys live in `~/.config/watch/.env` (mode `0600`) at runtime.
