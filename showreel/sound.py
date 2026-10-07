"""Synthesize the reel's sound design, synced to the animation's hit points.

    python3 showreel/sound.py out.wav
"""
import sys
import wave

import numpy as np

SR = 48000
DUR = 12.0
N = int(SR * DUR)
rng = np.random.default_rng(7)
mix = np.zeros((N, 2))


def place(sig, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    sig = sig[: max(0, N - i)]
    l, r = np.sqrt(0.5 * (1 - pan)), np.sqrt(0.5 * (1 + pan))
    mix[i:i + len(sig), 0] += sig * gain * l
    mix[i:i + len(sig), 1] += sig * gain * r


def tt(d):
    return np.arange(int(d * SR)) / SR


def thump(f0=140, f1=48, d=0.45, decay=9):
    t = tt(d)
    f = f1 + (f0 - f1) * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * decay)


def click(d=0.02):
    t = tt(d)
    return rng.standard_normal(len(t)) * np.exp(-t * 300)


def lowpass(x, a):
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += a[i] * (v - acc) if hasattr(a, '__len__') else a * (v - acc)
        y[i] = acc
    return y


def whoosh(d, rise=True):
    t = tt(d)
    u = t / d
    shape = u ** 2 if rise else (1 - u) ** 2
    cutoff = 0.02 + 0.25 * (u if rise else 1 - u)
    return lowpass(rng.standard_normal(len(t)), cutoff) * shape * 3


def blip(freq, d=0.35, decay=12):
    t = tt(d)
    return (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)) * np.exp(-t * decay) * np.minimum(1, t * 400)


def pad(freqs, d, attack=0.3):
    t = tt(d)
    env = np.minimum(1, t / attack) * np.exp(-t * 1.2)
    return sum(np.sin(2 * np.pi * f * t + k) for k, f in enumerate(freqs)) / len(freqs) * env


# 01 bounces (each one softer), anticipation, leap
for ti, g in zip([0.30, 0.80, 1.12, 1.28], [0.9, 0.65, 0.45, 0.25]):
    place(thump(160, 60, 0.3, 14), ti, g)
    place(click(), ti, 0.15 * g)
place(whoosh(0.34), 1.66, 0.5)

# scene cuts
for c in [2, 4, 6, 8, 10]:
    place(thump(), c, 1.0)
    place(click(0.03), c, 0.25)

# 02 slats in, push, crush
for i in range(9):
    place(whoosh(0.12, rise=False), 2.0 + i * 0.03, 0.10, pan=(-1) ** i * 0.6)
place(whoosh(0.4), 2.95, 0.45)
place(whoosh(0.35, rise=False), 3.55, 0.3)

# 03 terrain drone
place(pad([55, 82.4, 110, 164.8], 2.0, 0.4), 4.0, 0.55)

# 04 ripples, then implosion
for (x, t0), f in zip([(960, 0.0), (430, 0.30), (1490, 0.52), (1300, 0.78), (640, 0.98)], [880, 660, 990, 740, 1320]):
    place(blip(f), 6.0 + t0, 0.25, pan=(x - 960) / 960)
place(whoosh(0.6), 7.35, 0.6)

# 05 liquid split / merge
for k, f in enumerate([523, 587, 659, 784, 880, 1047]):
    place(blip(f, 0.25, 18), 8.12 + k * 0.05, 0.12, pan=np.sin(k * 1.7) * 0.7)
place(whoosh(0.45), 9.25, 0.35)

# 06 logo hit + resolving chord, rule tick
place(thump(120, 40, 1.2, 4), 10.0, 1.0)
place(pad([110, 164.8, 220, 277.2, 329.6, 440], 2.0, 0.02), 10.06, 0.6)
place(blip(1760, 0.2, 25), 11.05, 0.12)

# fades + soft limiter
mix[: int(0.01 * SR)] *= np.linspace(0, 1, int(0.01 * SR))[:, None]
mix[-int(0.4 * SR):] *= np.linspace(1, 0, int(0.4 * SR))[:, None]
mix = np.tanh(mix * 1.1) * 0.85

with wave.open(sys.argv[1], 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype('<i2').tobytes())
