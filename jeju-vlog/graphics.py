"""Cute motion-graphics overlay for the Jeju day-2 vlog.

Renders a transparent RGBA PNG sequence (1920x1080, 30fps) that is composited
on top of the edited footage by build.py.
"""
import math
import os
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1920, 1080, 30
HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "fonts", "Jua-Regular.ttf")

CREAM = (255, 249, 236, 255)
INK = (74, 52, 40, 255)
ORANGE = (255, 140, 40, 255)
LEAF = (88, 170, 80, 255)
WHITE = (255, 255, 255, 255)

CHAPTERS = [
    # label, sub, color, icon
    ("굿모닝 조식", "든든하게 시작!", (255, 196, 70, 255), "sun"),
    ("해녀 변신 촬영", "오늘은 해녀 3인방", (70, 170, 230, 255), "camera"),
    ("산굼부리", "억새 사이로 산책", (150, 190, 90, 255), "mountain"),
    ("교래손칼국수", "점심은 후루룩", (240, 150, 90, 255), "bowl"),
    ("보롬사진관 4컷", "찰칵! 찰칵! 찰칵! 찰칵!", (240, 120, 160, 255), "grid"),
    ("협재해수욕장", "에메랄드 바다", (60, 200, 200, 255), "wave"),
    ("바다이야기 횟집", "저녁은 싱싱한 회", (90, 140, 230, 255), "fish"),
    ("성이시돌목장", "별 보러 가자", (120, 100, 200, 255), "star"),
]


def font(size):
    return ImageFont.truetype(FONT, size)


# ---------- easing ----------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out_back(t, s=1.9):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_out_cubic(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_cubic(t):
    t = clamp(t)
    return t ** 3


# ---------- drawing helpers (draw at 2x for smooth edges) ----------
def star_points(cx, cy, r_out, r_in, n=5, rot=-math.pi / 2):
    pts = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = rot + i * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw_icon(d, kind, cx, cy, s, color=WHITE):
    """Simple doodle icons, s = half-size."""
    lw = max(2, int(s * 0.16))
    if kind == "sun":
        d.ellipse([cx - s * .45, cy - s * .45, cx + s * .45, cy + s * .45], fill=color)
        for i in range(8):
            a = i * math.pi / 4
            d.line([cx + s * .62 * math.cos(a), cy + s * .62 * math.sin(a),
                    cx + s * .92 * math.cos(a), cy + s * .92 * math.sin(a)], fill=color, width=lw)
    elif kind == "camera":
        d.rounded_rectangle([cx - s * .9, cy - s * .5, cx + s * .9, cy + s * .7], radius=s * .2, fill=color)
        d.rounded_rectangle([cx - s * .35, cy - s * .75, cx + s * .35, cy - s * .4], radius=s * .1, fill=color)
        d.ellipse([cx - s * .38, cy - s * .28, cx + s * .38, cy + s * .48], fill=(0, 0, 0, 0))
        d.ellipse([cx - s * .22, cy - s * .12, cx + s * .22, cy + s * .32], fill=color)
    elif kind == "mountain":
        d.polygon([(cx - s, cy + s * .7), (cx - s * .1, cy - s * .7), (cx + s * .8, cy + s * .7)], fill=color)
        d.polygon([(cx - s * .1, cy + s * .7), (cx + s * .45, cy - s * .2), (cx + s, cy + s * .7)], fill=color)
    elif kind == "bowl":
        d.pieslice([cx - s * .95, cy - s * .7, cx + s * .95, cy + s * .9], 0, 180, fill=color)
        for dx in (-.4, 0, .4):
            d.arc([cx + s * dx - s * .15, cy - s * .9, cx + s * dx + s * .15, cy - s * .1], 100, 260, fill=color, width=lw)
    elif kind == "grid":
        g = s * .08
        for ix in (0, 1):
            for iy in (0, 1):
                x0 = cx - s * .8 + ix * (s * .8 + g)
                y0 = cy - s * .8 + iy * (s * .8 + g)
                d.rounded_rectangle([x0, y0, x0 + s * .72, y0 + s * .72], radius=s * .12, fill=color)
    elif kind == "wave":
        for row in (-.35, .3):
            pts = []
            for i in range(41):
                x = cx - s + i * (2 * s / 40)
                pts.append((x, cy + s * row + math.sin(i / 40 * math.pi * 4) * s * .2))
            d.line(pts, fill=color, width=lw + 2, joint="curve")
    elif kind == "fish":
        d.ellipse([cx - s * .8, cy - s * .45, cx + s * .45, cy + s * .45], fill=color)
        d.polygon([(cx + s * .3, cy), (cx + s, cy - s * .5), (cx + s, cy + s * .5)], fill=color)
        d.ellipse([cx - s * .5, cy - s * .15, cx - s * .3, cy + s * .05], fill=(0, 0, 0, 0))
    elif kind == "star":
        d.polygon(star_points(cx, cy, s * .95, s * .42), fill=color)


def tangerine(size):
    """Jeju 귤 mascot with a face, pre-rendered at 2x then downsampled."""
    S = size * 2
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    body = [S * .08, S * .2, S * .92, S * .96]
    d.ellipse(body, fill=ORANGE, outline=INK, width=int(S * .035))
    # leaf + stem
    d.ellipse([S * .5, S * .04, S * .86, S * .24], fill=LEAF, outline=INK, width=int(S * .03))
    d.line([S * .5, S * .22, S * .52, S * .1], fill=INK, width=int(S * .035))
    # face
    e = S * .045
    for ex in (.36, .64):
        d.ellipse([S * ex - e, S * .52 - e, S * ex + e, S * .52 + e], fill=INK)
    d.arc([S * .42, S * .52, S * .58, S * .68], 20, 160, fill=INK, width=int(S * .03))
    for bx in (.25, .75):
        d.ellipse([S * bx - S * .07, S * .62, S * bx + S * .07, S * .7], fill=(255, 110, 110, 200))
    return im.resize((size, size), Image.LANCZOS)


def text_with_outline(d, xy, text, f, fill, outline, ow, anchor="la"):
    d.text(xy, text, font=f, fill=fill, anchor=anchor, stroke_width=ow, stroke_fill=outline)


def sticker(label, sub, color, icon, num):
    """Chapter sticker (rendered once, 2x)."""
    k = 2
    f1, f2, fn = font(64 * k), font(34 * k), font(40 * k)
    tw = max(f1.getlength(label), f2.getlength(sub))
    w = int(150 * k + tw + 60 * k)
    h = int(170 * k)
    im = Image.new("RGBA", (w + 24 * k, h + 24 * k), (0, 0, 0, 0))
    # drop shadow
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([14 * k, 18 * k, w + 10 * k, h + 14 * k], radius=48 * k, fill=(0, 0, 0, 90))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(8 * k)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([6 * k, 6 * k, w, h], radius=48 * k, fill=CREAM, outline=INK, width=5 * k)
    # icon badge
    bx, by, br = 6 * k + 82 * k, 6 * k + h / 2 - 3 * k, 58 * k
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=color, outline=INK, width=5 * k)
    draw_icon(d, icon, bx, by, br * .62)
    # step number bubble
    nx, ny, nr = bx + br * .78, by - br * .78, 24 * k
    d.ellipse([nx - nr, ny - nr, nx + nr, ny + nr], fill=INK)
    d.text((nx, ny + 2 * k), str(num), font=font(30 * k), fill=CREAM, anchor="mm")
    tx = 6 * k + 160 * k
    d.text((tx, 6 * k + 30 * k), label, font=f1, fill=INK, anchor="la")
    d.text((tx, 6 * k + 108 * k), sub, font=f2, fill=color[:3] + (255,), anchor="la")
    return im.resize((im.width // k, im.height // k), Image.LANCZOS)


def paste_center(base, im, cx, cy, scale=1.0, rot=0.0, alpha=1.0):
    if scale <= 0.01 or alpha <= 0.01:
        return
    w, h = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    t = im.resize((w, h), Image.BILINEAR)
    if rot:
        t = t.rotate(rot, resample=Image.BICUBIC, expand=True)
    if alpha < 1:
        a = t.getchannel("A").point(lambda v: int(v * alpha))
        t.putalpha(a)
    base.alpha_composite(t, (int(cx - t.width / 2), int(cy - t.height / 2)))


# ---------- scenes ----------
class Overlay:
    def __init__(self, timeline):
        """timeline: dict with intro, outro durations and chapter (start, end) secs."""
        self.tl = timeline
        self.total = timeline["total"]
        self.mascot = tangerine(150)
        self.mascot_s = tangerine(64)
        self.stickers = [sticker(c[0], c[1], c[2], c[3], i + 1) for i, c in enumerate(CHAPTERS)]
        self.icon_cache = {}
        self.badge = self._badge()

    def _badge(self):
        k = 2
        im = Image.new("RGBA", (300 * k, 96 * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([4 * k, 4 * k, 296 * k, 92 * k], radius=44 * k, fill=ORANGE, outline=INK, width=4 * k)
        d.text((150 * k, 50 * k), "JEJU DAY 2", font=font(46 * k), fill=WHITE, anchor="mm",
               stroke_width=3 * k, stroke_fill=INK)
        return im.resize((300, 96), Image.LANCZOS)

    def frame(self, n):
        t = n / FPS
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        tl = self.tl
        if t < tl["intro"]:
            self.intro(im, t)
        elif t >= self.total - tl["outro"]:
            self.outro(im, t - (self.total - tl["outro"]))
        else:
            ci = max(i for i, (s, e) in enumerate(tl["chapters"]) if t >= s)
            s, e = tl["chapters"][ci]
            self.route(im, t, ci, s, e)
            self.chapter_card(im, ci, t - s, e - t)
            # top-left badge with bobbing mascot
            im.alpha_composite(self.badge, (44, 40))
            bob = math.sin(t * 4) * 5
            paste_center(im, self.mascot_s, 44 + 300 + 30, 88 + bob, rot=math.sin(t * 3) * 10)
        return im

    # --- intro 0..intro: title card
    def intro(self, im, t):
        d = ImageDraw.Draw(im)
        dur = self.tl["intro"]
        # cream panel rises up then (at end) slides down out
        out = ease_in_cubic((t - (dur - .5)) / .5)
        rise = ease_out_cubic(t / .45)
        panel_h = 640
        y0 = H - (H + panel_h) / 2 * rise + out * H
        top = (H - panel_h) / 2
        y0 = top + (1 - rise) * (H - top) + out * H
        pw = 1500
        panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel)
        pd.rounded_rectangle([(W - pw) / 2 + 10, y0 + 16, (W + pw) / 2 + 10, y0 + panel_h + 16], radius=70, fill=(0, 0, 0, 70))
        panel = panel.filter(ImageFilter.GaussianBlur(10))
        im.alpha_composite(panel)
        d.rounded_rectangle([(W - pw) / 2, y0, (W + pw) / 2, y0 + panel_h], radius=70, fill=CREAM, outline=INK, width=6)
        # scalloped wave strip at panel bottom
        for i in range(16):
            x = (W - pw) / 2 + 60 + i * 88
            d.ellipse([x - 30, y0 + panel_h - 70, x + 30, y0 + panel_h - 10], fill=(120, 205, 230, 255))
        cy = y0 + 70
        # small heading
        d.text((W / 2, cy + 40), "고모! 이모! 유경이랑", font=font(64), fill=(240, 120, 160, 255), anchor="mm")
        # bouncy title letters
        title = "제주도 2일차"
        f = font(190)
        total_w = f.getlength(title)
        x = W / 2 - total_w / 2
        for i, ch in enumerate(title):
            lt = t - .35 - i * .07
            sc = ease_out_back(lt / .45) if lt > 0 else 0
            cw = f.getlength(ch)
            if sc > 0 and ch.strip():
                g = Image.new("RGBA", (240, 260), (0, 0, 0, 0))
                ImageDraw.Draw(g).text((120, 130), ch, font=f, fill=ORANGE, anchor="mm", stroke_width=9, stroke_fill=INK)
                wob = math.sin(t * 5 + i) * 3
                paste_center(im, g, x + cw / 2, cy + 225 + wob, scale=sc)
            x += cw
        # subtitle pops in
        st = ease_out_back((t - 1.5) / .5)
        if st > 0:
            g = Image.new("RGBA", (1300, 110), (0, 0, 0, 0))
            ImageDraw.Draw(g).text((650, 55), "추억 가득가득, 하루 코스 따라가기", font=font(62), fill=INK, anchor="mm")
            paste_center(im, g, W / 2, cy + 410, scale=st)
        # mascots bounce in from the sides
        for side, delay in ((-1, .9), (1, 1.1)):
            p = ease_out_back((t - delay) / .5)
            if p > 0:
                mx = W / 2 + side * (pw / 2 - 40)
                my = y0 + 40 + math.sin(t * 6 + side) * 10
                paste_center(im, self.mascot, mx, my, scale=p, rot=side * -12 + math.sin(t * 4) * 8)
        # twinkly sparkles
        for i, (sx, sy) in enumerate(((330, 230), (1600, 260), (420, 860), (1520, 830), (960, 160))):
            a = .5 + .5 * math.sin(t * 6 + i * 1.7)
            r = 18 + 10 * a
            if t > .6:
                d.polygon(star_points(sx, sy + out * H, r, r * .4), fill=(255, 220, 90, int(255 * (.4 + .6 * a))))

    # --- per-chapter sticker pop-in / pop-out
    def chapter_card(self, im, ci, since, until):
        stk = self.stickers[ci]
        hold = 3.0
        if since > hold + .4:
            return
        p = ease_out_back(since / .5)
        q = 1 - ease_in_cubic((since - hold) / .35)
        sc = p * q
        cx = 70 + stk.width / 2
        cy = H - 210 - stk.height / 2 + (1 - p) * 60
        paste_center(im, stk, cx, cy, scale=sc, rot=(1 - p) * 8 + math.sin(since * 3) * 1.5)
        # bouncing location pin above sticker
        if 0.3 < since < hold:
            d = ImageDraw.Draw(im)
            px = 70 + stk.width - 40
            py = cy - stk.height / 2 - 30 - abs(math.sin(since * 6)) * 26
            col = CHAPTERS[ci][2]
            d.ellipse([px - 24, py - 24, px + 24, py + 24], fill=col, outline=INK, width=4)
            d.polygon([(px - 18, py + 12), (px + 18, py + 12), (px, py + 46)], fill=col, outline=INK)
            d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=WHITE)
        # confetti burst
        if since < 1.2:
            d = ImageDraw.Draw(im)
            for j in range(14):
                a = j / 14 * 2 * math.pi
                dist = ease_out_cubic(since / 1.0) * 260
                fx = cx + math.cos(a) * dist * 1.6
                fy = cy + math.sin(a) * dist * .8 + since * since * 120
                al = int(255 * clamp(1 - since / 1.2))
                col = CHAPTERS[(ci + j) % len(CHAPTERS)][2][:3] + (al,)
                if j % 2:
                    d.polygon(star_points(fx, fy, 14, 6, rot=since * 4 + j), fill=col)
                else:
                    d.ellipse([fx - 8, fy - 8, fx + 8, fy + 8], fill=col)

    # --- bottom route bar with mascot travelling between stops
    def route(self, im, t, ci, s, e):
        d = ImageDraw.Draw(im)
        n = len(CHAPTERS)
        x0, x1, y = 560, W - 140, H - 70
        xs = [x0 + (x1 - x0) * i / (n - 1) for i in range(n)]
        # translucent pill behind
        d.rounded_rectangle([x0 - 60, y - 34, x1 + 60, y + 34], radius=34, fill=(255, 249, 236, 170))
        for i in range(n - 1):
            for k in range(10):
                xx = xs[i] + (xs[i + 1] - xs[i]) * (k + .5) / 10
                filled = i < ci
                d.ellipse([xx - 3, y - 3, xx + 3, y + 3], fill=INK if filled else (74, 52, 40, 110))
        for i, xx in enumerate(xs):
            col = CHAPTERS[i][2] if i <= ci else (220, 210, 195, 255)
            r = 18 if i != ci else 22
            d.ellipse([xx - r, y - r, xx + r, y + r], fill=col, outline=INK, width=3)
            draw_icon(d, CHAPTERS[i][3], xx, y, r * .6)
        # mascot hops from previous stop to current one in the first 0.8s of a chapter
        hop = ease_out_cubic((t - s) / .8)
        prev = xs[ci - 1] if ci > 0 else xs[0]
        mx = prev + (xs[ci] - prev) * hop
        my = y - 52 - math.sin(clamp((t - s) / .8) * math.pi) * 40 - abs(math.sin(t * 3)) * 6
        paste_center(im, self.mascot_s, mx, my)

    # --- outro: night sky with twinkling stars
    def outro(self, im, t):
        dur = self.tl["outro"]
        d = ImageDraw.Draw(im)
        fade = ease_out_cubic(t / .6)
        d.rectangle([0, 0, W, H], fill=(20, 22, 60, int(150 * fade)))
        for i in range(40):
            sx = (i * 397) % W
            sy = (i * 211) % (H - 200)
            a = .5 + .5 * math.sin(t * 5 + i)
            r = 6 + (i % 4) * 4 + 4 * a
            d.polygon(star_points(sx, sy, r, r * .4), fill=(255, 235, 140, int(230 * a * fade)))
        # shooting star
        st = clamp((t - .3) / 1.0)
        if 0 < st < 1:
            hx, hy = 300 + st * 1300, 120 + st * 300
            d.line([hx - 220, hy - 50, hx, hy], fill=(255, 255, 255, int(255 * (1 - st))), width=6)
            d.polygon(star_points(hx, hy, 22, 9), fill=(255, 245, 180, 255))
        p = ease_out_back((t - .4) / .6)
        if p > 0:
            g = Image.new("RGBA", (1700, 420), (0, 0, 0, 0))
            gd = ImageDraw.Draw(g)
            gd.text((850, 120), "추억 가득 제주 2일차, 끝!", font=font(130), fill=WHITE, anchor="mm",
                    stroke_width=8, stroke_fill=INK)
            gd.text((850, 290), "고모 & 이모 & 유경, 다음에 또 오자!", font=font(70), fill=(255, 220, 120, 255), anchor="mm",
                    stroke_width=5, stroke_fill=INK)
            paste_center(im, g, W / 2, H / 2 - 40, scale=p)
        q = ease_out_back((t - 1.0) / .5)
        if q > 0:
            for side in (-1, 1):
                paste_center(im, self.mascot, W / 2 + side * 760, H / 2 + 230 + math.sin(t * 6 + side) * 12,
                             scale=q, rot=side * 10)


def render(timeline, outdir, frames=None):
    os.makedirs(outdir, exist_ok=True)
    ov = Overlay(timeline)
    total = int(round(timeline["total"] * FPS))
    rng = frames if frames is not None else range(total)
    for n in rng:
        ov.frame(n).save(os.path.join(outdir, f"ov_{n:05d}.png"), compress_level=1)


if __name__ == "__main__":
    import json
    tl = json.load(open(sys.argv[1]))
    render(tl, sys.argv[2])
