"""Synthesize the male-announcer narration track from script.js with Supertonic 3.

    python3 narration.py out/narration.wav [--voice M1] [--samples]

Each line is placed at its caption start time. If a line runs longer than its
caption window it is re-synthesized faster (up to 1.35x) so lines never overlap.
--samples writes one test sentence per male voice (M1..M5) to out/voice-*.wav.

Needs `pip install supertonic`; the first run downloads the model from
huggingface.co (~400MB, cached in ~/.cache/supertonic3).
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from supertonic import TTS

HERE = Path(__file__).resolve().parent
DURATION = 60.0
MAX_SPEED = 1.35


def load_script():
    src = (HERE / "script.js").read_text(encoding="utf-8")
    body = re.search(r"window\.CAPTIONS\s*=\s*(\[.*\]);", src, re.S).group(1)
    return json.loads(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(HERE / "out" / "narration.wav"))
    ap.add_argument("--voice", default="M1", help="Supertonic voice style (male: M1..M5)")
    ap.add_argument("--speed", type=float, default=1.05)
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--samples", action="store_true")
    args = ap.parse_args()

    tts = TTS(model="supertonic-3")
    sr = tts.sample_rate

    if args.samples:
        line = "겨울 바다의 초록 보약, 매생이. 그 효능을 일 분 만에 알려드립니다."
        for name in [v for v in tts.voice_style_names if v.startswith("M")]:
            wav, _ = tts.synthesize(line, voice_style=tts.get_voice_style(name), lang="ko",
                                    speed=args.speed, total_steps=args.steps)
            p = Path(args.out).parent / f"voice-{name}.wav"
            sf.write(str(p), wav.squeeze(), sr)
            print("wrote", p)
        return

    style = tts.get_voice_style(args.voice)
    track = np.zeros(int(DURATION * sr), dtype=np.float32)
    for c in load_script():
        text = c.get("say", c["text"]).replace("{", "").replace("}", "").replace("|", " ")
        window = c["b"] - c["a"] - 0.15
        speed = args.speed
        while True:
            wav, _ = tts.synthesize(text, voice_style=style, lang="ko", speed=speed,
                                    total_steps=args.steps)
            wav = np.trim_zeros(wav.squeeze().astype(np.float32), "fb")
            dur = len(wav) / sr
            if dur <= window or speed >= MAX_SPEED:
                break
            speed = min(MAX_SPEED, speed * dur / window + 0.02)
        i0 = int(c["a"] * sr)
        seg = wav[: len(track) - i0]
        track[i0 : i0 + len(seg)] += seg
        flag = "  (over window!)" if dur > window else ""
        print(f"{c['a']:5.1f}s  {dur:4.2f}s/{window:4.2f}s  x{speed:.2f}  {text}{flag}")

    peak = float(np.max(np.abs(track))) or 1.0
    track *= 0.9 / peak
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.out, track, sr)
    print("wrote", args.out)


if __name__ == "__main__":
    sys.exit(main())
