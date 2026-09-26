// Render index.html frame-by-frame with Playwright and pipe to ffmpeg.
//   node render.mjs                 → out/maesaengi-vlog.mp4 (60s, 1080x1920, 30fps)
//   node render.mjs --stills 3,15   → out/still-3.png, out/still-15.png
import { spawn, execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require('playwright')); }
catch { ({ chromium } = require(path.join(execFileSync('npm', ['root', '-g']).toString().trim(), 'playwright'))); }

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(here, 'out');
mkdirSync(outDir, { recursive: true });
const FPS = 30;
const args = process.argv.slice(2);
const stillsIdx = args.indexOf('--stills');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
await page.goto(pathToFileURL(path.join(here, 'index.html')).href + '?render=1');
await page.evaluate(() => document.fonts.ready);
// Warm up every font face before capturing.
await page.evaluate(() => Promise.all([...document.fonts].map(f => f.load().catch(() => null))));
const duration = await page.evaluate(() => window.DURATION);
const root = page.locator('#root');

if (stillsIdx >= 0) {
  for (const t of args[stillsIdx + 1].split(',').map(Number)) {
    await page.evaluate(t => window.renderAt(t), t);
    await root.screenshot({ path: path.join(outDir, `still-${t}.png`) });
    console.log('still', t);
  }
  await browser.close();
  process.exit(0);
}

const out = path.join(outDir, 'maesaengi-vlog.mp4');
const audio = path.join(outDir, 'bgm.wav');
execFileSync('python3', [path.join(here, 'bgm.py'), audio], { stdio: 'inherit' });

const ff = spawn('ffmpeg', [
  '-y', '-loglevel', 'error',
  '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
  '-i', audio,
  '-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-pix_fmt', 'yuv420p',
  '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', out,
], { stdio: ['pipe', 'inherit', 'inherit'] });

const total = Math.round(duration * FPS);
for (let i = 0; i < total; i++) {
  await page.evaluate(t => window.renderAt(t), i / FPS);
  const buf = await root.screenshot({ type: 'jpeg', quality: 92 });
  if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
  if (i % 150 === 0) console.log(`frame ${i}/${total}`);
}
ff.stdin.end();
await new Promise((res, rej) => ff.on('close', c => (c === 0 ? res() : rej(new Error('ffmpeg exit ' + c)))));
await browser.close();
console.log('wrote', out);
