# WITCONLAB showreel

12s · 1920×1080 · 30fps · palette: cream `#F2EBDA`, coral `#E84B2C`, ink `#0E0C0A`.

One coral dot carries through every cut and ends as the O in the logo.

| Time | Technique | Hand-off to the next shot |
|------|-----------|---------------------------|
| 0–2s | Squash & stretch: bounce, spacing chart, anticipation | the ball leaps at the camera and fills the frame with coral |
| 2–4s | Kinetic type: alternating slat push, MOTION → DESIGN | the slats crush into hairlines |
| 4–6s | Procedural terrain: Perlin field with hidden-line removal | the lines dash down to a dot lattice |
| 6–8s | Ripple field: interfering shockwaves on 2,340 dots | the dots spiral into a core and a cream iris opens |
| 8–10s | Liquid SDF: smooth-min metaballs with topographic contours | the blobs merge into the O |
| 10–12s | Logo reveal: letters slide out of slots on each side of the O | — |

All of it is drawn in code, frame by frame, with 8-sample 180° motion blur. The sound is synthesized and timed to the hits.

```bash
node showreel/render.js /tmp/frames --samples 8      # headless Chromium (Playwright), ~40s
python3 showreel/sound.py /tmp/sfx.wav
ffmpeg -framerate 30 -i /tmp/frames/f_%04d.png -i /tmp/sfx.wav -c:v libx264 -crf 14 -tune animation \
  -pix_fmt yuv420p -vf "scale=out_color_matrix=bt709:out_range=tv" -colorspace bt709 \
  -color_primaries bt709 -color_trc bt709 -c:a aac -b:a 192k -movflags +faststart showreel/witconlab-showreel.mp4
```

Fonts: Inter Display Black and Inter, loaded from `/usr/share/fonts/opentype/inter/`.
