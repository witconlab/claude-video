// Render index.html frame-by-frame with Playwright and pipe to ffmpeg.
//   node render.mjs                 → out/maesaengi-vlog.mp4 (60s, 1080x1920, 30fps)
//   node render.mjs --stills 3,15   → out/still-3.png, out/still-15.png
//   node render.mjs --voice M1      → out/maesaengi-vlog-narration.mp4 (male announcer TTS, BGM ducked)
//   node render.mjs --voice M1 --mix-only   reuse out/maesaengi-vlog.mp4 frames, only redo audio
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

const voiceIdx = args.indexOf('--voice');
const voice = voiceIdx >= 0 ? args[voiceIdx + 1] : null;
const plain = path.join(outDir, 'maesaengi-vlog.mp4');
const out = voice ? path.join(outDir, 'maesaengi-vlog-narration.mp4') : plain;
const audio = path.join(outDir, 'bgm.wav');
execFileSync('python3', [path.join(here, 'bgm.py'), audio], { stdio: 'inherit' });

// Audio inputs + filter: plain BGM, or narration over BGM ducked by a sidechain compressor.
let audioArgs = ['-i', audio];
let mapArgs = ['-map', '0:v', '-map', '1:a'];
if (voice) {
  const narr = path.join(outDir, 'narration.wav');
  execFileSync('python3', [path.join(here, 'narration.py'), narr, '--voice', voice], { stdio: 'inherit' });
  audioArgs = ['-i', audio, '-i', narr];
  mapArgs = ['-filter_complex',
    '[2:a]aresample=44100,highpass=f=80,acompressor=threshold=0.1:ratio=3:attack=5:release=120:makeup=1.5,asplit=2[v1][v2];' +
    '[1:a]volume=0.6[m];[m][v1]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck];' +
    '[duck][v2]amix=inputs=2:normalize=0,alimiter=limit=0.95[a]',
    '-map', '0:v', '-map', '[a]'];
}

if (args.includes('--mix-only')) {
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', plain, ...audioArgs, ...mapArgs,
    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out], { stdio: 'inherit' });
  await browser.close();
  console.log('wrote', out);
  process.exit(0);
}

const ff = spawn('ffmpeg', [
  '-y', '-loglevel', 'error',
  '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
  ...audioArgs, ...mapArgs,
  '-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-pix_fmt', 'yuv420p',
  '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out,
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
