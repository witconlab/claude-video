"""Assemble the Jeju day-2 vlog: 1920x1080, 30fps, exactly 90s.

usage: python3 build.py plan.json out.mp4 [--bgm music.mp3]

plan.json:
{
  "intro": [{"file": "a.jpg"}],               # behind the title card (5s)
  "chapters": [[{"file": "x.HEIC"}, {"file": "y.MOV", "start": 3.0}], ...],  # one list per CHAPTERS entry
  "outro": [{"file": "stars.jpg"}]            # behind the ending card (5s)
}
Items without "dur" share their section's time evenly.
Video options: "start" (s), "speed" (<1 = slow motion, muted), "rotate" (90/-90/180), "mute".
Photo options: "bright" (brightness factor, e.g. 1.6 for night shots).
"""
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps, ImageFilter, ImageDraw, ImageEnhance

import graphics

W, H, FPS = 1920, 1080, 30
TOTAL, INTRO, OUTRO = 90.0, 5.0, 5.0
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv"}

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True).stdout
    return float(out.strip() or 0)


def is_hdr(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=color_transfer", "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True).stdout
    return out.strip() in ("arib-std-b67", "smpte2084")


def still_frame(src, dst, bright=1.0):
    """Photo -> 2x-size 16:9 still. Portrait photos become a tilted polaroid on a blurred bg."""
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    if bright != 1.0:
        im = ImageEnhance.Brightness(im).enhance(bright)
    BW, BH = W * 2, H * 2
    if im.width / im.height >= 1.3:
        ImageOps.fit(im, (BW, BH), Image.LANCZOS).save(dst, quality=93)
        return
    bg = ImageOps.fit(im, (BW // 8, BH // 8), Image.LANCZOS).filter(ImageFilter.GaussianBlur(6))
    bg = bg.resize((BW, BH), Image.BICUBIC)
    bg = Image.blend(bg, Image.new("RGB", bg.size, (255, 246, 230)), .25)
    fh = int(BH * .74)
    fw = int(im.width * fh / im.height)
    pad = int(BH * .03)
    card = Image.new("RGBA", (fw + pad * 2, fh + pad * 2 + pad * 2), (255, 255, 255, 255))
    card.paste(im.resize((fw, fh), Image.LANCZOS), (pad, pad))
    shadow = Image.new("RGBA", (card.width + 120, card.height + 120), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([60, 70, card.width + 60, card.height + 70], fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(25))
    tilt = (hash(os.path.basename(src)) % 7) - 3
    canvas = bg.convert("RGBA")
    for layer, off in ((shadow, 0), (card, 60)):
        r = layer.rotate(tilt, resample=Image.BICUBIC, expand=True)
        canvas.alpha_composite(r, ((BW - r.width) // 2, (BH - r.height) // 2 - int(BH * .04)))
    canvas.convert("RGB").save(dst, quality=93)


def render_item(item, dur, dst, tmp, idx):
    src = item["file"]
    ext = os.path.splitext(src)[1].lower()
    n = int(round(dur * FPS))
    aout = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    vout = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS)]
    if ext in VIDEO_EXT:
        length = probe_duration(src)
        speed = item.get("speed", 1.0)
        span = dur * speed  # source seconds needed
        start = item.get("start", max(0.0, (length - span) / 2))
        start = max(0.0, min(start, max(0.0, length - span)))
        tone = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
                "zscale=t=bt709:m=bt709:r=tv,format=yuv420p," if is_hdr(src) else "")
        rot = {90: "transpose=1,", -90: "transpose=2,", 180: "hflip,vflip,"}.get(item.get("rotate", 0), "")
        # slow clips down with "speed" < 1; clone the last frame if the source still runs short
        slow = f"setpts=PTS/{speed}," if speed != 1.0 else ""
        vf = (f"[0:v]{tone}{rot}{slow}fps={FPS},tpad=stop_mode=clone:stop_duration={dur:.3f},split[a][b];"
              f"[a]scale={W//8}:{H//8}:force_original_aspect_ratio=increase,crop={W//8}:{H//8},"
              f"gblur=sigma=4,scale={W}:{H}[bg];"
              f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]")
        has_audio = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                                    "stream=index", "-of", "csv=p=0", src],
                                   capture_output=True, text=True).stdout.strip() != ""
        cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", src]
        if has_audio and speed == 1.0 and not item.get("mute"):
            af = f"[0:a]volume={item.get('volume', 0.8)},apad,atrim=0:{dur:.3f}[au]"
        else:
            cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            af = "[1:a]anull[au]"
        cmd += ["-filter_complex", vf + ";" + af, "-map", "[v]", "-map", "[au]",
                "-frames:v", str(n)] + vout + aout + [dst]
    else:
        still = os.path.join(tmp, f"still_{idx}.jpg")
        still_frame(src, still, item.get("bright", 1.0))
        zin = (idx % 2 == 0)
        z = f"1+0.08*on/{n}" if zin else f"1.08-0.08*on/{n}"
        vf = (f"[0:v]zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS},"
              f"setsar=1,format=yuv420p[v]")
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", still, "-f", "lavfi", "-t", f"{dur:.3f}",
               "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", vf, "-map", "[v]", "-map", "1:a",
               "-frames:v", str(n)] + vout + aout + ["-shortest", dst]
    run(cmd)


def split(items, total):
    fixed = sum(i["dur"] for i in items if "dur" in i)
    free = [i for i in items if "dur" not in i]
    each = (total - fixed) / len(free) if free else 0
    out, acc = [], 0.0
    for k, it in enumerate(items):
        d = it.get("dur", each)
        # snap to frames so the section stays exact
        end = total if k == len(items) - 1 else round((acc + d) * FPS) / FPS
        out.append((it, end - acc))
        acc = end
    return out


def main():
    plan_path, out = sys.argv[1], sys.argv[2]
    bgm = sys.argv[sys.argv.index("--bgm") + 1] if "--bgm" in sys.argv else None
    plan = json.load(open(plan_path))
    base = os.path.dirname(os.path.abspath(plan_path))
    for sec in [plan["intro"], plan["outro"], *plan["chapters"]]:
        for it in sec:
            it["file"] = os.path.join(base, it["file"])

    # chapters share whatever the intro and outro leave of the 90 s
    CHAPTER = (TOTAL - INTRO - OUTRO) / len(plan["chapters"])
    tmp = tempfile.mkdtemp(prefix="vlog_", dir=os.path.dirname(os.path.abspath(out)))
    sections = [(plan["intro"], INTRO)] + [(c, CHAPTER) for c in plan["chapters"]] + [(plan["outro"], OUTRO)]
    segs, idx = [], 0
    for items, total in sections:
        for it, d in split(items, total):
            dst = os.path.join(tmp, f"seg_{idx:03d}.mp4")
            print(f"[seg {idx:02d}] {os.path.basename(it['file'])} {d:.2f}s", flush=True)
            render_item(it, d, dst, tmp, idx)
            segs.append(dst)
            idx += 1

    listing = os.path.join(tmp, "list.txt")
    with open(listing, "w") as f:
        f.writelines(f"file '{s}'\n" for s in segs)
    base_mp4 = os.path.join(tmp, "base.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", base_mp4])

    total = INTRO + OUTRO + CHAPTER * len(plan["chapters"])
    starts = [INTRO + CHAPTER * i for i in range(len(plan["chapters"]))]
    tl = {"total": total, "intro": INTRO, "outro": OUTRO,
          "chapters": [[s, s + CHAPTER] for s in starts]}
    ovdir = os.path.join(tmp, "overlay")
    print("[overlay] rendering motion graphics", flush=True)
    graphics.render(tl, ovdir)

    cmd = ["ffmpeg", "-y", "-i", base_mp4, "-framerate", str(FPS), "-i", os.path.join(ovdir, "ov_%05d.png")]
    fc = "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", bgm]
        fc += (f";[2:a]atrim=0:{total},volume=0.55,afade=t=in:d=1,afade=t=out:st={total-2.5}:d=2.5[m];"
               f"[0:a][m]amix=inputs=2:duration=first:normalize=0[a]")
        amap = "[a]"
    else:
        amap = "0:a"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", amap, "-t", str(total),
            "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    print("[final] compositing", flush=True)
    run(cmd)
    print("done:", out, probe_duration(out))


if __name__ == "__main__":
    main()
