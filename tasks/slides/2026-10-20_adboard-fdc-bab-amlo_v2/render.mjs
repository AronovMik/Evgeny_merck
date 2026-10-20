// Рендер макетов slides.html в PNG 1600×900.
// Запуск из корня репо: node tasks/slides/2026-10-20_adboard-fdc-bab-amlo_v2/render.mjs
// Нужен Playwright (в облачной среде: глобальный пакет, Chromium в /opt/pw-browsers).
import { execSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const dir = dirname(fileURLToPath(import.meta.url));
const globalRoot = execSync('npm root -g').toString().trim();
const { chromium } = await import(pathToFileURL(join(globalRoot, 'playwright', 'index.mjs')).href);

const names = {
  s1: 'slide-01', s2: 'slide-02', s3: 'slide-03', s4: 'slide-04', s5: 'slide-05',
  s6: 'slide-06', s7: 'slide-07', b1: 'backup-1', b2: 'backup-2',
};

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
  .catch(() => chromium.launch());
const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } });
await page.goto(pathToFileURL(join(dir, 'slides.html')).href);
await page.waitForTimeout(500);
for (const [id, name] of Object.entries(names)) {
  await (await page.$('#' + id)).screenshot({ path: join(dir, name + '.png') });
}
await browser.close();
console.log('rendered', Object.keys(names).length, 'slides');
