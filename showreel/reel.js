// WITCONLAB showreel — 12s, 1920x1080, 30fps.
// One coral dot travels through six techniques (2s each) and lands as the O of the logo.
// Deterministic: renderFrame(f, samples) draws frame f with `samples`-tap motion blur.

const W = 1920, H = 1080, FPS = 30, TAU = Math.PI * 2;
const CREAM = '#F2EBDA', CORAL = '#E84B2C', INK = '#0E0C0A';
const RGB = { cream: [0xF2, 0xEB, 0xDA], coral: [0xE8, 0x4B, 0x2C], ink: [0x0E, 0x0C, 0x0A] };

const out = document.getElementById('out');
const octx = out.getContext('2d', { willReadFrequently: true });
const buf = document.createElement('canvas');
buf.width = W; buf.height = H;
const ctx = buf.getContext('2d');

// ---------------------------------------------------------------- math
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const seg = (t, a, b) => clamp((t - a) / (b - a));
const E = {
  inQuad: x => x * x,
  inCubic: x => x * x * x,
  outCubic: x => 1 - Math.pow(1 - x, 3),
  inOutCubic: x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2,
  outQuint: x => 1 - Math.pow(1 - x, 5),
  outExpo: x => x >= 1 ? 1 : 1 - Math.pow(2, -10 * x),
  inExpo: x => x <= 0 ? 0 : Math.pow(2, 10 * x - 10),
  inOutExpo: x => x <= 0 ? 0 : x >= 1 ? 1 : x < .5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2,
  outBack: (x, s = 1.70158) => 1 + (s + 1) * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2),
};

// Improved Perlin noise (seeded permutation).
const P = new Uint8Array(512);
(() => {
  const p = [...Array(256).keys()];
  let s = 1337;
  const r = () => (s = (s * 16807) % 2147483647) / 2147483647;
  for (let i = 255; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [p[i], p[j]] = [p[j], p[i]]; }
  for (let i = 0; i < 512; i++) P[i] = p[i & 255];
})();
const fade = t => t * t * t * (t * (t * 6 - 15) + 10);
function grad(h, x, y, z) {
  const u = h < 8 ? x : y, v = h < 4 ? y : (h === 12 || h === 14 ? x : z);
  return ((h & 1) ? -u : u) + ((h & 2) ? -v : v);
}
function noise(x, y, z) {
  const fx = Math.floor(x), fy = Math.floor(y), fz = Math.floor(z);
  const X = fx & 255, Y = fy & 255, Z = fz & 255;
  x -= fx; y -= fy; z -= fz;
  const u = fade(x), v = fade(y), w = fade(z);
  const A = P[X] + Y, AA = P[A] + Z, AB = P[A + 1] + Z, B = P[X + 1] + Y, BA = P[B] + Z, BB = P[B + 1] + Z;
  return lerp(
    lerp(lerp(grad(P[AA] & 15, x, y, z), grad(P[BA] & 15, x - 1, y, z), u),
         lerp(grad(P[AB] & 15, x, y - 1, z), grad(P[BB] & 15, x - 1, y - 1, z), u), v),
    lerp(lerp(grad(P[AA + 1] & 15, x, y, z - 1), grad(P[BA + 1] & 15, x - 1, y, z - 1), u),
         lerp(grad(P[AB + 1] & 15, x, y - 1, z - 1), grad(P[BB + 1] & 15, x - 1, y - 1, z - 1), u), v), w);
}

// Shared grid: S3's rows flatten onto S4's dot lattice (30px pitch, 65 x 36).
const PITCH = 30, ROWS = 36, COLS = 65;
const rowY = j => 540 + (j - 17.5) * PITCH;
const colX = i => 960 + (i - 32) * PITCH;

// ================================================================ 01 SQUASH & STRETCH
const F1 = 760, R1 = 62;
const BOUNCES = [ // t0, t1, x0, x1, apex height
  [0.30, 0.80, 560, 820, 360],
  [0.80, 1.12, 820, 935, 150],
  [1.12, 1.28, 935, 960, 42],
];
const IMPACTS = [0.30, 0.80, 1.12, 1.28];
const IMPACT_GAIN = [0.62, 0.48, 0.32, 0.16];

function ballPath(t) { // contact point (x, bottom y)
  if (t < 0.30) { const u = Math.max(0, t) / 0.30; return { x: lerp(400, 560, u), y: F1 - (F1 + 260) * (1 - u * u) }; }
  for (const [a, b, x0, x1, h] of BOUNCES) {
    if (t < b) { const u = (t - a) / (b - a); return { x: lerp(x0, x1, u), y: F1 - 4 * h * u * (1 - u) }; }
  }
  return { x: 960, y: F1 };
}

function S1(g, t) {
  g.fillStyle = INK; g.fillRect(0, 0, W, H);

  // floor
  const L = 780 * E.outExpo(seg(t, 0.0, 0.6));
  g.fillStyle = CREAM; g.fillRect(960 - L, F1 - 1, 2 * L, 2);

  // impact ticks + floor ripples
  IMPACTS.forEach((ti, idx) => {
    if (t < ti) return;
    const p = ballPath(ti), d = t - ti;
    g.fillStyle = CREAM;
    g.fillRect(p.x - 1, F1 + 14, 2, 18 * E.outExpo(seg(d, 0, 0.25)));
    const u = d / 0.55;
    if (u < 1) {
      const rx = R1 * 0.9 + (240 - idx * 45) * E.outExpo(u);
      g.lineWidth = 3.5 * (1 - u); g.strokeStyle = CREAM;
      g.beginPath(); g.ellipse(p.x, F1, rx, rx * 0.16, 0, 0, TAU); g.stroke();
    }
  });

  // spacing chart: one dot per frame, shrinking with age
  if (t < 1.66) {
    g.fillStyle = CREAM;
    const f0 = Math.floor(t * FPS);
    for (let k = f0; k >= 0 && k > f0 - 26; k--) {
      const tt = k / FPS, r = 5 * (1 - (t - tt) / 0.85);
      if (r <= 0) continue;
      const p = ballPath(tt);
      g.beginPath(); g.arc(p.x, p.y - R1, r, 0, TAU); g.fill();
    }
  }

  // ball: impact squash (spring), velocity stretch, anticipation, leap
  const p = ballPath(t);
  let sx = 1, sy = 1, env = 0;
  IMPACTS.forEach((ti, i) => {
    const d = t - ti;
    if (d >= 0 && d < 0.4) {
      const a = IMPACT_GAIN[i] * Math.exp(-d * 16) * Math.cos(d * 38);
      sx *= 1 + a; sy /= 1 + a;
      env = Math.max(env, Math.exp(-d * 14));
    }
  });
  const ant = 0.45 * E.inOutCubic(seg(t, 1.40, 1.66));
  if (t < 1.66) { sx *= 1 + ant; sy /= 1 + ant; }
  else {
    let q = lerp(1 / 1.45, 1.38, E.outCubic(seg(t, 1.66, 1.73)));
    q = lerp(q, 1, E.inOutCubic(seg(t, 1.73, 1.88)));
    sx /= q; sy *= q;
  }
  const h = 1 / 240, pa = ballPath(t - h), pb = ballPath(t + h);
  const vx = (pb.x - pa.x) / (2 * h), vy = (pb.y - pa.y) / (2 * h);
  const st = 1 + clamp(Math.hypot(vx, vy) / 2800, 0, 0.45) * (1 - env);
  const ang = Math.atan2(vy, vx);

  let R = R1, cx = p.x, cy = Math.min(p.y, F1) - R1 * sy;
  if (t >= 1.66) {
    const u = seg(t, 1.66, 1.96);
    R = R1 * Math.pow(28, E.inCubic(u));
    cx = 960; cy = lerp(F1 - R1 * sy, 560, E.inOutCubic(u));
  }
  g.save();
  g.translate(cx, cy); g.scale(sx, sy); g.rotate(ang); g.scale(st, 1 / st);
  g.fillStyle = CORAL; g.beginPath(); g.arc(0, 0, R, 0, TAU); g.fill();
  g.restore();
  if (t >= 1.95) { g.fillStyle = CORAL; g.fillRect(0, 0, W, H); }
}

// ================================================================ 02 KINETIC TYPE
let WORDS = null;
function prepWords() {
  const probe = document.createElement('canvas').getContext('2d');
  probe.font = '100px IDB'; probe.letterSpacing = '-2.5px';
  const wmax = Math.max(probe.measureText('MOTION').width, probe.measureText('DESIGN').width);
  const fs = Math.floor(100 * 1760 / wmax);
  const mk = txt => {
    const c = document.createElement('canvas');
    let g = c.getContext('2d');
    const setup = () => { g.font = `${fs}px IDB`; g.letterSpacing = `${-0.025 * fs}px`; };
    setup();
    const w = g.measureText(txt).width, capH = g.measureText('H').actualBoundingBoxAscent;
    const pad = Math.ceil(fs * 0.035);
    c.width = Math.ceil(w) + 4; c.height = Math.ceil(capH + 2 * pad);
    g = c.getContext('2d'); setup();
    g.fillStyle = INK; g.fillText(txt, 2, pad + capH);
    return { c, w: c.width, h: c.height };
  };
  WORDS = { MOTION: mk('MOTION'), DESIGN: mk('DESIGN') };
}

function S2(g, t) {
  g.fillStyle = CORAL; g.fillRect(0, 0, W, H);
  const cw = W * E.inOutExpo(seg(t, 1.60, 1.96));
  if (cw > 0) { g.fillStyle = CREAM; g.fillRect(960 - cw / 2, 0, cw, H); }

  const N = 9, LW = 2.5;
  g.fillStyle = INK;
  for (const [word, phase] of [['MOTION', 0], ['DESIGN', 1]]) {
    const wc = WORDS[word], x0 = 960 - wc.w / 2, y0 = 540 - wc.h / 2, sh = wc.h / N;
    for (let i = 0; i < N; i++) {
      const dir = i % 2 ? 1 : -1;
      const us = seg(t, 1.0 + i * 0.025, 1.42 + i * 0.025); // the push between words
      let off;
      if (phase === 0) {
        if (us >= 1) continue;
        off = dir * 2300 * (1 - E.outExpo(seg(t, i * 0.03, 0.55 + i * 0.03))) - dir * 2300 * E.inOutExpo(us);
        off += 16 * Math.sin(t * 8 - i * 0.7) * seg(t, 0.35, 0.6) * (1 - seg(t, 0.92, 1.02));
      } else {
        if (us <= 0) continue;
        off = dir * 2300 * (1 - E.inOutExpo(us));
      }
      let cy = y0 + (i + 0.5) * sh, dh = sh;
      if (phase === 1) { // slats crush into hairlines and spread onto the terrain rows
        const e = E.inOutExpo(seg(t, 1.52 + i * 0.018, 1.80 + i * 0.018));
        cy = lerp(cy, 540 + (4 * i - 16) * PITCH, e);
        dh = lerp(sh, LW, e);
        if (e > 0.98) {
          const ext = E.inOutExpo(seg(t, 1.66 + i * 0.012, 1.95));
          const l = lerp(x0, -10, ext), r = lerp(x0 + wc.w, W + 10, ext);
          g.fillRect(l, cy - LW / 2, x0 - l, LW);
          g.fillRect(x0 + wc.w, cy - LW / 2, r - x0 - wc.w, LW);
          if (t > 1.9) g.fillRect(x0, cy - LW / 2, wc.w, LW);
        }
      }
      g.drawImage(wc.c, 0, i * sh, wc.w, sh, x0 + off, cy - dh / 2, wc.w, dh + 0.6);
    }
  }
}

// ================================================================ 03 PROCEDURAL TERRAIN
const NX = 200, XS = 1110, ZS = 525;
function hgt(x, z, t) {
  const w = Math.exp(-Math.pow(x / 560, 4));
  const n = noise(x * 0.0034, z * 0.0034 + t * 0.9, 1.7);
  const n2 = noise(x * 0.011, z * 0.011 + t * 1.6, 9.1);
  return w * (340 * Math.pow(clamp(0.5 + 0.95 * n), 2.4) + 26 * n2) + 10 * n2;
}

function S3(g, t) {
  g.fillStyle = CREAM; g.fillRect(0, 0, W, H);
  const AMAX = 66 * Math.PI / 180;
  const a = AMAX * E.inOutCubic(seg(t, 0.06, 0.72)) * (1 - E.inOutExpo(seg(t, 1.3, 1.8)));
  const amp = E.outCubic(seg(t, 0.1, 0.8)) * (1 - E.inOutCubic(seg(t, 1.25, 1.72)));
  const D = 1500, ca = Math.cos(a), sa = Math.sin(a);
  const lift = -60 * (a / AMAX);
  const spread = E.outExpo(seg(t, 0.0, 0.45));
  const k = E.inOutCubic(seg(t, 1.55, 1.9));
  const lw = lerp(2.5, 9, k);
  const hl = (t > 0.25 && t < 1.3) ? Math.round(lerp(ROWS - 1, 0, seg(t, 0.25, 1.3))) : -1;
  g.lineJoin = 'round'; g.lineCap = 'round';
  const pts = new Float32Array((NX + 1) * 2);
  for (let j = 0; j < ROWS; j++) { // far -> near, fills give hidden-line removal
    const z = lerp(ZS, -ZS, j / (ROWS - 1));
    const gy = 540 + (4 * Math.floor(j / 4) - 16) * PITCH;
    for (let n = 0; n <= NX; n++) {
      const x = lerp(-XS, XS, n / NX), hh = amp * hgt(x, z, t);
      const v = z * ca + hh * sa, d = D - hh * ca + z * sa, s = D / d;
      pts[2 * n] = 960 + x * s;
      pts[2 * n + 1] = lerp(gy, 540 + lift - v * s, spread);
    }
    g.beginPath(); g.moveTo(pts[0], pts[1]);
    for (let n = 1; n <= NX; n++) g.lineTo(pts[2 * n], pts[2 * n + 1]);
    g.lineTo(pts[2 * NX], H + 60); g.lineTo(pts[0], H + 60); g.closePath();
    g.fillStyle = CREAM; g.fill();

    g.beginPath(); g.moveTo(pts[0], pts[1]);
    for (let n = 1; n <= NX; n++) g.lineTo(pts[2 * n], pts[2 * n + 1]);
    if (k > 0) g.setLineDash([Math.max(0.001, PITCH * (1 - k)), PITCH * k]); else g.setLineDash([]);
    g.strokeStyle = j === hl ? CORAL : INK;
    g.lineWidth = j === hl ? 6 : lw;
    g.stroke();
  }
  g.setLineDash([]);
}

// ================================================================ 04 RIPPLE FIELD
const RIP = [ // x, y, t0, strength
  [960, 540, 0.00, 1.0], [430, 290, 0.30, 0.85], [1490, 800, 0.52, 0.9],
  [1300, 240, 0.78, 0.75], [640, 840, 0.98, 0.8],
];
function S4(g, t) {
  g.fillStyle = INK; g.fillRect(0, 0, W, H);
  const cx = 960, cy = 540;
  const cream = new Path2D(), coral = new Path2D();
  let sumE = 0;
  for (let j = 0; j < ROWS; j++) for (let i = 0; i < COLS; i++) {
    let x = colX(i), y = rowY(j), tot = 0, dx = 0, dy = 0;
    for (const [rx, ry, t0, st] of RIP) {
      if (t < t0) continue;
      const age = t - t0, rho = 1350 * age;
      const ddx = x - rx, ddy = y - ry, dist = Math.sqrt(ddx * ddx + ddy * ddy) + 1e-6;
      const dd = dist - rho;
      const wv = (Math.exp(-((dd / 55) ** 2)) - 0.5 * Math.exp(-(((dd + 120) / 55) ** 2))) * st * Math.exp(-age * 1.1);
      tot += wv; dx += ddx / dist * wv * 24; dy += ddy / dist * wv * 24;
    }
    let r = 4.5 + 11 * Math.max(0, tot), hot = tot > 0.42;
    x += dx; y += dy;
    const D0 = Math.hypot(x - cx, y - cy), del = 0.26 * (D0 / 1100);
    const u = seg(t, 1.34 + del, 1.68 + del);
    if (u > 0) { // implosion: spiral into the core
      const e = E.inExpo(u), ang = 1.6 * e, c = Math.cos(ang), s = Math.sin(ang);
      const px = x - cx, py = y - cy;
      x = cx + (px * c - py * s) * (1 - e); y = cy + (px * s + py * c) * (1 - e);
      r *= 1 - 0.6 * e; hot = true; sumE += e;
    }
    const path = hot ? coral : cream;
    path.moveTo(x + r, y); path.arc(x, y, r, 0, TAU);
  }
  g.fillStyle = CREAM; g.fill(cream);
  g.fillStyle = CORAL; g.fill(coral);

  const iris = 1150 * E.inCubic(seg(t, 1.76, 1.95));
  if (iris > 0) { g.fillStyle = CREAM; g.beginPath(); g.arc(cx, cy, iris, 0, TAU); g.fill(); }
  if (t >= 1.95) { g.fillStyle = CREAM; g.fillRect(0, 0, W, H); }
  const rc = 125 * Math.sqrt(sumE / (ROWS * COLS));
  if (rc > 0.5) { g.fillStyle = CORAL; g.beginPath(); g.arc(cx, cy, rc, 0, TAU); g.fill(); }
}

// ================================================================ 05 LIQUID SDF
let IMG = null;
const pack = (r, g, b) => (255 << 24) | (b << 16) | (g << 8) | r;

function S5(g, t) {
  const L = LOGO;
  const mv = E.inOutCubic(seg(t, 1.2, 1.75));
  const mx = lerp(960, L.ox, mv), my = lerp(540, L.oy, mv);
  let mr = lerp(125, 92, E.outCubic(seg(t, 0.08, 0.5)));
  mr = lerp(mr, L.R, E.inOutCubic(seg(t, 1.3, 1.75)));
  const dw = t - 1.75;
  if (dw > 0) mr *= 1 + 0.07 * Math.exp(-dw * 12) * Math.sin(dw * 34);

  const blobs = [[mx, my, mr]];
  const spread = E.outBack(seg(t, 0.1, 0.7), 1.4), back = E.inOutExpo(seg(t, 1.2, 1.68));
  const RO = [330, 250, 370, 280, 345, 240], RR = [72, 50, 62, 44, 58, 40];
  for (let k = 0; k < 6; k++) {
    const th = k * TAU / 6 + t * 2.4 + 0.3 * Math.sin(t * 3 + k);
    const rho = (RO[k] + 45 * Math.sin(t * 6 + k * 1.9) * seg(t, 0.5, 0.8)) * spread * (1 - back);
    const r = RR[k] * lerp(0.6, 1, seg(t, 0.1, 0.4)) * (1 - seg(t, 1.55, 1.8));
    blobs.push([mx + Math.cos(th) * rho, my + Math.sin(th) * rho, r]);
  }
  const K = 110 * seg(t, 0, 0.2) * (1 - seg(t, 1.6, 1.85)) + 1;
  const cs = seg(t, 0.15, 0.55) * (1 - seg(t, 1.3, 1.7)); // topo contour spread
  const RINGS = 4, GAP = 30 * cs, hw = 1.4 * cs;

  if (!IMG) IMG = g.createImageData(W, H);
  const d32 = new Uint32Array(IMG.data.buffer);
  const [cr, cg, cb] = RGB.cream, [kr, kg, kb] = RGB.ink, [or, og, ob] = RGB.coral;
  d32.fill(pack(cr, cg, cb));
  const reach = RINGS * GAP + K + 6;
  let x0 = W, y0 = H, x1 = 0, y1 = 0;
  for (const [bx, by, br] of blobs) {
    x0 = Math.min(x0, bx - br - reach); x1 = Math.max(x1, bx + br + reach);
    y0 = Math.min(y0, by - br - reach); y1 = Math.max(y1, by + br + reach);
  }
  x0 = Math.max(0, Math.floor(x0)); y0 = Math.max(0, Math.floor(y0));
  x1 = Math.min(W, Math.ceil(x1)); y1 = Math.min(H, Math.ceil(y1));
  const nb = blobs.length;
  for (let y = y0; y < y1; y++) {
    const py = y + 0.5;
    for (let x = x0; x < x1; x++) {
      const px = x + 0.5;
      let d = 1e9;
      for (let b = 0; b < nb; b++) {
        const bl = blobs[b], ddx = px - bl[0], ddy = py - bl[1];
        const s = Math.sqrt(ddx * ddx + ddy * ddy) - bl[2];
        if (b === 0) { d = s; continue; }
        const hk = Math.max(K - Math.abs(d - s), 0) / K;
        d = Math.min(d, s) - hk * hk * K * 0.25;
      }
      if (d > reach) continue;
      let lc = 0;
      if (hw > 0.05 && d > 0) {
        const m = Math.max(1, Math.min(RINGS, Math.round(d / GAP)));
        lc = clamp(hw + 0.5 - Math.abs(d - m * GAP));
      }
      const fc = clamp(0.5 - d);
      let r = cr + (kr - cr) * lc, gg = cg + (kg - cg) * lc, bb = cb + (kb - cb) * lc;
      r += (or - r) * fc; gg += (og - gg) * fc; bb += (ob - bb) * fc;
      d32[y * W + x] = pack(r | 0, gg | 0, bb | 0);
    }
  }
  g.putImageData(IMG, 0, 0);
}

// ================================================================ 06 LOGO REVEAL
let LOGO = null;
function prepLogo() {
  const g = document.createElement('canvas').getContext('2d');
  const fs = 214;
  g.font = `${fs}px IDB`;
  const capH = g.measureText('H').actualBoundingBoxAscent;
  const R = capH / 2, gap = 0.055 * fs, track = -0.012 * fs;
  const KERN = { LA: -0.075 * fs, AB: -0.01 * fs, WI: -0.005 * fs, TC: -0.02 * fs };
  const adv = (s) => {
    let w = 0;
    for (let i = 0; i < s.length; i++) {
      w += g.measureText(s[i]).width + (i < s.length - 1 ? track + (KERN[s[i] + s[i + 1]] || 0) : 0);
    }
    return w;
  };
  const left = 'WITC', right = 'NLAB';
  const total = adv(left) + gap + 2 * R + gap + adv(right);
  const x0 = 960 - total / 2, baseline = 505 + capH / 2;
  const ox = x0 + adv(left) + gap + R, oy = baseline - capH / 2;
  const letters = [];
  let x = x0;
  for (let i = 0; i < left.length; i++) {
    letters.push({ ch: left[i], x, w: g.measureText(left[i]).width, side: -1, rank: left.length - 1 - i });
    x += g.measureText(left[i]).width + track + (KERN[left[i] + left[i + 1]] || 0);
  }
  x = ox + R + gap;
  for (let i = 0; i < right.length; i++) {
    letters.push({ ch: right[i], x, w: g.measureText(right[i]).width, side: 1, rank: i });
    x += g.measureText(right[i]).width + track + (KERN[right[i] + right[i + 1]] || 0);
  }
  LOGO = { fs, capH, R, ox, oy, baseline, letters, left: x0, right: x0 + total };
}

function S6(g, t) {
  const L = LOGO;
  g.fillStyle = CREAM; g.fillRect(0, 0, W, H);
  g.font = `${L.fs}px IDB`; g.letterSpacing = '0px'; g.fillStyle = INK; g.textBaseline = 'alphabetic';
  for (const side of [-1, 1]) {
    g.save(); g.beginPath();
    if (side < 0) g.rect(0, 0, L.ox - L.R, H); else g.rect(L.ox + L.R, 0, W, H);
    g.clip();
    for (const l of L.letters) {
      if (l.side !== side) continue;
      const a = 0.06 + l.rank * 0.055;
      const e = E.outExpo(seg(t, a, a + 0.7));
      const xs = side < 0 ? L.ox - L.R : L.ox + L.R - l.w;
      g.fillText(l.ch, lerp(xs, l.x, e), L.baseline);
    }
    g.restore();
  }
  const d = t - 0.08, a = d > 0 ? 0.10 * Math.exp(-d * 6) * Math.sin(d * 20) : 0;
  g.fillStyle = CORAL;
  g.beginPath(); g.ellipse(L.ox, L.oy, L.R * (1 - a), L.R * (1 + a), 0, 0, TAU); g.fill();

  // rule + travelling dot
  const ry = L.baseline + 0.2 * L.fs;
  const rw = (L.right - L.left) * E.inOutExpo(seg(t, 0.55, 1.05));
  if (rw > 0) {
    g.fillStyle = INK; g.fillRect(L.left, ry, rw, 3);
    g.fillStyle = CORAL; g.beginPath(); g.arc(L.left + rw, ry + 1.5, 7 * seg(t, 0.55, 0.62), 0, TAU); g.fill();
  }
  // tagline rises out of the rule
  const ty = ry + 52 + 90 * (1 - E.outExpo(seg(t, 0.85, 1.4)));
  g.save(); g.beginPath(); g.rect(0, ry + 6, W, 80); g.clip();
  g.font = '24px ISB'; g.letterSpacing = '7px'; g.fillStyle = INK;
  g.textAlign = 'left'; g.fillText('MOTION DESIGN', L.left, ty);
  const tag = 'SHOWREEL 2026';
  g.fillText(tag, L.right - g.measureText(tag).width + 7, ty);
  g.restore();
  g.textAlign = 'left'; g.letterSpacing = '0px';
}

// ================================================================ HUD
const LABELS = ['SQUASH & STRETCH', 'KINETIC TYPE', 'PROCEDURAL TERRAIN', 'RIPPLE FIELD', 'LIQUID SDF', 'LOGO REVEAL'];
const pad2 = n => String(n).padStart(2, '0');

const PALETTE = [[CREAM, RGB.cream], [CORAL, RGB.coral], [INK, RGB.ink]];
function sampleBg(x, y) { // nearest palette colour under this corner + a legible ink for it
  const d = octx.getImageData(x, y, 8, 8).data, n = d.length / 4, m = [0, 0, 0];
  for (let i = 0; i < d.length; i += 4) { m[0] += d[i] / n; m[1] += d[i + 1] / n; m[2] += d[i + 2] / n; }
  let best = null, bd = Infinity;
  for (const [hex, c] of PALETTE) {
    const dd = (c[0] - m[0]) ** 2 + (c[1] - m[1]) ** 2 + (c[2] - m[2]) ** 2;
    if (dd < bd) { bd = dd; best = hex; }
  }
  return { bg: best, fg: best === INK ? CREAM : INK };
}

function hud(g, f) {
  const t = f / FPS, s = Math.min(5, Math.floor(f / 60)), lt = t - 2 * s;
  const vis = E.outExpo(seg(t, 0.05, 0.55)) * (1 - E.inOutExpo(seg(t, 11.2, 11.55)));
  if (vis <= 0.001) return;
  const M = 64, P = 14;
  g.save();
  g.font = '20px IM'; g.letterSpacing = '3px'; g.textBaseline = 'alphabetic';
  // each block: knock out a panel in the sampled background so fields behind never fight the type
  const block = (corner, x, w, draw) => {
    const c = sampleBg(...corner);
    g.save(); g.beginPath(); g.rect(x - P, M - 24 - P + (corner[1] > H / 2 ? H - 2 * M : 0), w + 2 * P, 34 + 2 * P); g.clip();
    g.fillStyle = c.bg; g.fillRect(0, 0, W, H);
    g.fillStyle = c.fg; draw();
    g.restore();
  };
  const by = H - M;

  const tl = 'SHOWREEL 2026';
  block([2, 2], M, g.measureText(tl).width * vis, () => g.fillText(tl, M, M));

  const tc = `00:00:${pad2(Math.floor(f / FPS))}:${pad2(f % FPS)}`;
  const pitch = ch => ch === ':' ? 9 : 15, tw = [...tc].reduce((a, ch) => a + pitch(ch), 0);
  block([W - 10, 2], W - M - tw * vis, tw * vis, () => {
    let x = W - M - tw;
    for (const ch of tc) { g.fillText(ch, x, M); x += pitch(ch); }
  });

  const line = k => `${pad2(k + 1)}/06   ${LABELS[k]}`;
  const roll = s > 0 ? E.outExpo(seg(lt, 0, 0.32)) : 1;
  const lw = Math.max(g.measureText(line(s)).width, roll < 1 ? g.measureText(line(s - 1)).width : 0);
  block([2, H - 10], M, lw * vis, () => {
    if (roll < 1) g.fillText(line(s - 1), M, by - 34 * roll);
    g.fillText(line(s), M, by + 34 * (1 - roll));
  });

  const sw = 44, sg = 8, total = 6 * sw + 5 * sg, x0 = W - M - total * vis;
  block([W - 10, H - 10], x0, total * vis, () => {
    for (let k = 0; k < 6; k++) {
      const x = x0 + k * (sw + sg), fill = clamp((t - 2 * k) / 2);
      g.fillRect(x, by - 1, sw, 1);
      if (fill > 0) g.fillRect(x, by - 3, sw * fill, 5);
    }
  });
  g.restore();
}

// ================================================================ frame
const SCENES = [S1, S2, S3, S4, S5, S6];

function drawScene(g, s, lt) {
  g.save();
  g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.setLineDash([]);
  SCENES[s](g, lt);
  g.restore();
}

// Box-filtered 180-degree shutter; sub-samples never cross a scene cut.
window.renderFrame = (f, samples = 8, shutter = 0.5) => {
  const s = Math.min(5, Math.floor(f / 60)), t0 = f / FPS - 2 * s;
  octx.globalAlpha = 1;
  for (let k = 0; k < samples; k++) {
    const off = samples > 1 ? ((k + 0.5) / samples - 0.5) * shutter / FPS : 0;
    drawScene(ctx, s, clamp(t0 + off, 0, 2 - 1e-4));
    octx.globalAlpha = 1 / (k + 1);
    octx.drawImage(buf, 0, 0);
  }
  octx.globalAlpha = 1;
  hud(octx, f);
};

(async () => {
  await Promise.all(['100px IDB', '20px IM', '24px ISB'].map(f => document.fonts.load(f)));
  prepWords(); prepLogo();
  window.READY = true;
})();
