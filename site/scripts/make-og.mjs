// Renders scripts/og-source.html to public/og.png (1200x630) using
// system Chrome headless. Run from site/: node scripts/make-og.mjs
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { mkdtempSync, rmSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';

const chrome =
  process.env.CHROME_BIN ??
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, 'og-source.html');
const out = join(here, '..', 'public', 'og.png');
const profile = mkdtempSync(join(tmpdir(), 'og-chrome-'));
const shot = join(profile, 'shot.png');

try {
  execFileSync(chrome, [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    `--user-data-dir=${profile}`,
    '--window-size=1200,630',
    '--force-device-scale-factor=1',
    `--screenshot=${shot}`,
    '--virtual-time-budget=3000',
    `file://${src}`,
  ]);
  copyFileSync(shot, out);
  console.log('wrote', out);
} finally {
  rmSync(profile, { recursive: true, force: true });
}
