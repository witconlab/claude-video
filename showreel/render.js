// Render reel.html frame-by-frame with headless Chromium.
//   node showreel/render.js <outdir> [--samples 8] [--frames 0,30,61] [--workers 4]
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
const outDir = args[0];
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const samples = +opt('--samples', 8);
const workers = +opt('--workers', 4);
const frames = opt('--frames', null)?.split(',').map(Number) ?? [...Array(360).keys()];

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ args: ['--allow-file-access-from-files'] });
  const url = 'file://' + path.resolve(__dirname, 'reel.html');
  let next = 0, done = 0;
  const t0 = Date.now();
  await Promise.all([...Array(Math.min(workers, frames.length))].map(async () => {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    page.on('pageerror', e => { console.error(e); process.exit(1); });
    await page.goto(url);
    await page.waitForFunction('window.READY === true');
    while (next < frames.length) {
      const f = frames[next++];
      const data = await page.evaluate(([f, n]) => {
        renderFrame(f, n);
        return document.getElementById('out').toDataURL('image/png');
      }, [f, samples]);
      fs.writeFileSync(path.join(outDir, `f_${String(f).padStart(4, '0')}.png`), Buffer.from(data.split(',')[1], 'base64'));
      if (++done % 30 === 0) console.log(`${done}/${frames.length}  ${((Date.now() - t0) / 1000).toFixed(1)}s`);
    }
    await page.close();
  }));
  await browser.close();
  console.log(`done ${frames.length} frames in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
})();
