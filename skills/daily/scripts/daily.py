#!/usr/bin/env python3
"""/daily entry point: collect the day's recordings, KakaoTalk notes-to-self and
screenshots, and print one JSON manifest grouped by day.

- Recordings → notes.run(): transcribed, one note per recording (frontmatter dedup).
- KakaoTalk exports + screenshots → inbox.py: only items newer than last run,
  parked in <out>/.daily/state.json under "pending" until the model writes that
  day's note and calls `daily.py --mark-noted YYYY-MM-DD`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inbox  # noqa: E402
import notes  # noqa: E402

ICLOUD_DRIVE = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"


def default_inbox(out_dir: Path, kind: str) -> Path:
    """iCloud Drive/Daily Inbox/<kind> on a Mac (the iPhone can save there), else <out>/inbox/<kind>."""
    if ICLOUD_DRIVE.is_dir():
        return ICLOUD_DRIVE / "Daily Inbox" / kind
    return out_dir / "inbox" / kind


def route(paths: list[str]) -> dict[str, list[str]]:
    routed: dict[str, list[str]] = {"recordings": [], "kakao": [], "screenshots": []}
    for raw in paths:
        suffix = Path(raw).suffix.lower()
        if suffix in notes.AUDIO_EXTS:
            routed["recordings"].append(raw)
        elif suffix in inbox.KAKAO_EXTS:
            routed["kakao"].append(raw)
        elif suffix in inbox.IMAGE_EXTS:
            routed["screenshots"].append(raw)
        else:
            raise SystemExit(f"don't know what to do with {raw} (folders: set DAILY_RECORDINGS / DAILY_KAKAO / DAILY_SCREENSHOTS)")
    return routed


def main() -> int:
    ap = notes.build_parser()
    ap.description = "Collect recordings, KakaoTalk notes-to-self and screenshots for /daily."
    ap.add_argument("--only", choices=["recordings", "kakao", "screenshots"], action="append",
                    help="Limit this run to some sources (repeatable)")
    ap.add_argument("--mark-noted", nargs="+", metavar="YYYY-MM-DD",
                    help="Days whose daily note now covers their pending KakaoTalk/screenshot items")
    args = ap.parse_args()
    report, code = run(args, notes.read_settings())
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return code


def run(args: argparse.Namespace, settings: dict[str, str]) -> tuple[dict, int]:
    out_dir = notes.output_dir(args, settings)

    if args.mark_noted:
        state = inbox.load_state(out_dir)
        cleared = [d for d in args.mark_noted if state.get("pending", {}).pop(d, None) is not None]
        inbox.save_state(out_dir, state)
        return {"output_dir": str(out_dir), "marked_noted": cleared}, 0

    only = set(args.only or ["recordings", "kakao", "screenshots"])
    routed = route(args.sources)
    if args.sources:
        only &= {k for k, v in routed.items() if v}
    since = date.fromisoformat(args.since) if args.since else None

    report: dict = {
        "output_dir": str(out_dir),
        "output_dir_configured": bool(args.out or settings.get("DAILY_DIR")),
        "daily_dir": str(out_dir / "daily"),
        "learning_queue": str(out_dir / "learning-queue.md"),
        "index": str(out_dir / "index.md"),
        "listing_only": bool(args.list),
        "recordings": None,
        "kakao": None,
        "screenshots": None,
        "days": {},
        "errors": [],
    }
    code = 0

    if "recordings" in only:
        rec_args = argparse.Namespace(**{**vars(args), "sources": routed["recordings"]})
        rec, rec_code = notes.run(rec_args, settings)
        report["recordings"] = {k: rec[k] for k in ("sources", "source_origin", "language", "remaining", "already_done")}
        for err in rec["errors"]:
            # No recordings folder is normal for a /daily run; only report real failures.
            if err["error"] != "no_source" or args.sources:
                report["errors"].append({**err, "kind": "recordings"})
        for item in rec["pending"]:
            report["days"].setdefault(item["recorded_at"][:10], {}).setdefault("recordings", []).append(item)
        if rec_code and any(e["error"] != "no_source" for e in rec["errors"]):
            code = rec_code

    state = inbox.load_state(out_dir)
    fresh_kakao: list[dict] = []
    fresh_shots: list[dict] = []

    if "kakao" in only:
        sources = notes.split_paths(settings.get("DAILY_KAKAO")) if not routed["kakao"] else [Path(p).expanduser() for p in routed["kakao"]]
        if not sources:
            sources = [default_inbox(out_dir, "kakao")]
        files = inbox._files(sources, inbox.KAKAO_EXTS)
        fresh_kakao = inbox.new_kakao_messages(files, state, since)
        report["kakao"] = {"sources": [str(s) for s in sources], "export_files": len(files), "new_messages": len(fresh_kakao),
                           "last_collected": (state.get("kakao") or {}).get("last")}
        if not files:
            report["errors"].append({"error": "no_kakao_export", "kind": "kakao", "detail": f"No .txt/.csv/.zip export in {', '.join(map(str, sources))}"})

    if "screenshots" in only:
        sources = notes.split_paths(settings.get("DAILY_SCREENSHOTS")) if not routed["screenshots"] else [Path(p).expanduser() for p in routed["screenshots"]]
        if not sources:
            sources = [default_inbox(out_dir, "screenshots")]
        try:
            files = inbox._files(sources, inbox.IMAGE_EXTS)
        except PermissionError as exc:
            files = []
            report["errors"].append({"error": "permission_denied", "kind": "screenshots", "detail": str(exc)})
        fresh_shots = inbox.new_screenshots(files, state, since)
        report["screenshots"] = {"sources": [str(s) for s in sources], "new": len(fresh_shots)}

    if args.list:
        preview = {"version": 1}
        inbox.add_pending(preview, fresh_kakao, fresh_shots, out_dir / ".daily" / "cache")
        pending = {**state.get("pending", {})}
        for day, items in preview.get("pending", {}).items():
            merged = {**pending.get(day, {})}
            for kind, entries in items.items():
                merged[kind] = [*merged.get(kind, []), *entries]
            pending[day] = merged
    else:
        inbox.add_pending(state, fresh_kakao, fresh_shots, out_dir / ".daily" / "cache")
        inbox.advance_kakao(state, fresh_kakao)
        if report["kakao"]:
            report["kakao"]["last_collected"] = (state.get("kakao") or {}).get("last")
        if fresh_kakao or fresh_shots or state_needs_save(out_dir):
            inbox.save_state(out_dir, state)
        pending = state.get("pending", {})

    for day, items in pending.items():
        report["days"].setdefault(day, {}).update(inbox.day_summary(items))

    for day, entry in report["days"].items():
        note = out_dir / "daily" / f"{day}.md"
        entry["daily_note"] = str(note)
        entry["note_exists"] = note.exists()
    report["days"] = dict(sorted(report["days"].items()))
    return report, code


def state_needs_save(out_dir: Path) -> bool:
    return not inbox.state_path(out_dir).exists()


if __name__ == "__main__":
    raise SystemExit(main())
