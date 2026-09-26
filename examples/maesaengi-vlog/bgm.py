"""Synthesize a 60s lo-fi vlog BGM (+ transition whooshes) as a WAV. Pure stdlib."""
import math
import random
import struct
import sys
import wave

SR = 44100
DUR = 60.0
BPM = 96
BEAT = 60 / BPM
N = int(SR * DUR)
buf = [0.0] * N
rng = random.Random(7)


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def add_tone(t0, dur, freq, amp, decay=3.0, harm=(1.0, 0.35, 0.12)):
    """Soft e-piano-ish tone: a few harmonics with exponential decay."""
    i0 = int(t0 * SR)
    n = int(dur * SR)
    for k in range(n):
        i = i0 + k
        if i >= N:
            break
        tt = k / SR
        env = math.exp(-decay * tt) * min(1.0, tt * 200)
        s = 0.0
        for h, a in enumerate(harm, start=1):
            s += a * math.sin(2 * math.pi * freq * h * tt)
        buf[i] += amp * env * s


def add_kick(t0, amp=0.55):
    i0 = int(t0 * SR)
    ph = 0.0
    for k in range(int(0.3 * SR)):
        i = i0 + k
        if i >= N:
            break
        tt = k / SR
        f = 45 + 90 * math.exp(-tt * 30)
        ph += 2 * math.pi * f / SR
        buf[i] += amp * math.exp(-tt * 11) * math.sin(ph)


def add_noise(t0, dur, amp, attack=0.002, decay=40.0, lp=0.5):
    i0 = int(t0 * SR)
    y = 0.0
    for k in range(int(dur * SR)):
        i = i0 + k
        if i >= N:
            break
        tt = k / SR
        env = min(1.0, tt / attack) * math.exp(-decay * tt)
        y += lp * ((rng.random() * 2 - 1) - y)
        buf[i] += amp * env * y


def add_whoosh(tc, amp=0.22):
    """Filtered-noise swell centred on a scene cut."""
    t0, dur = tc - 0.35, 0.6
    i0 = int(t0 * SR)
    y = 0.0
    for k in range(int(dur * SR)):
        i = i0 + k
        if i < 0 or i >= N:
            continue
        x = k / (dur * SR)
        env = math.sin(math.pi * x) ** 2
        cutoff = 0.05 + 0.4 * env
        y += cutoff * ((rng.random() * 2 - 1) - y)
        buf[i] += amp * env * y


def add_pop(t0, amp=0.25):
    i0 = int(t0 * SR)
    for k in range(int(0.12 * SR)):
        i = i0 + k
        if i >= N:
            break
        tt = k / SR
        f = 500 + 900 * (1 - math.exp(-tt * 40))
        buf[i] += amp * math.exp(-tt * 35) * math.sin(2 * math.pi * f * tt)


# Fmaj7 – Em7 – Dm7 – Cmaj7 (one bar each)
CHORDS = [
    (41, [65, 69, 72, 76]),
    (40, [64, 67, 71, 74]),
    (38, [62, 65, 69, 72]),
    (36, [60, 64, 67, 71]),
]
MELODY = [76, None, 74, 72, None, 69, 72, None, 74, None, 71, 67, None, 69, 71, 72]

bar = BEAT * 4
nbars = int(DUR / bar) + 1
for b in range(nbars):
    t_bar = b * bar
    root, notes = CHORDS[b % 4]
    for n in notes:
        add_tone(t_bar, bar, midi(n), 0.045, decay=1.2)
        add_tone(t_bar + BEAT * 2.5, bar * 0.4, midi(n), 0.03, decay=2.5)
    add_tone(t_bar, bar * 0.9, midi(root), 0.16, decay=1.6, harm=(1.0, 0.25))
    add_tone(t_bar + BEAT * 2, bar * 0.45, midi(root + 7), 0.10, decay=2.5, harm=(1.0, 0.25))
    add_kick(t_bar)
    add_kick(t_bar + BEAT * 2.5, 0.4)
    for q in range(8):
        add_noise(t_bar + q * BEAT / 2 + (0.02 if q % 2 else 0), 0.06, 0.05 if q % 2 else 0.03, decay=70, lp=0.9)
    add_noise(t_bar + BEAT, 0.18, 0.12, decay=22, lp=0.35)
    add_noise(t_bar + BEAT * 3, 0.18, 0.12, decay=22, lp=0.35)
    if b >= 2:  # melody enters after the intro
        for s, m in enumerate(MELODY):
            if m is not None and (b // 4) % 2 == 1 or (m is not None and s % 4 == 0):
                add_tone(t_bar + s * BEAT / 4 * 1.0, BEAT, midi(m + 12), 0.035, decay=4.0, harm=(1.0, 0.1))

for cut in (5, 11, 18.5, 26, 33, 40, 47, 54.5):
    add_whoosh(cut)
for p in (0.6, 0.76, 0.92, 1.1, 5.4, 6.8, 7.1, 7.4, 12.4, 13.4, 21.8, 29.0, 34.2, 41.8, 48.0, 48.25, 48.5, 48.75, 55.0, 55.2, 55.4, 55.6, 55.8, 56.8, 57.1):
    add_pop(p, 0.18)

# Fade in/out, soft-clip and normalize.
peak = 0.0
for i in range(N):
    t = i / SR
    g = min(1.0, t / 0.8) * min(1.0, (DUR - t) / 1.5)
    v = math.tanh(buf[i] * 1.2) * g
    buf[i] = v
    peak = max(peak, abs(v))
scale = 0.85 / peak if peak else 1.0

out = sys.argv[1] if len(sys.argv) > 1 else "bgm.wav"
with wave.open(out, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(b"".join(struct.pack("<h", int(v * scale * 32767)) for v in buf))
print("wrote", out)
