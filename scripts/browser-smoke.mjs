import { chromium } from '../ui/node_modules/playwright/index.mjs';
import assert from 'node:assert/strict';

const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  const origin = process.env.HERETIC_TEST_URL;
  assert.match(origin ?? '', /^http:\/\/127\.0\.0\.1:\d+$/);
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Memory', exact: true }).click();
  await page.getByRole('heading', { name: 'Memory and knowledge' }).waitFor();
  await page.getByLabel('Record kind').selectOption('preference');
  await page.getByLabel('Explicit memory record').fill('The smoke test code is amber-signal.');
  await page.getByRole('button', { name: 'Save memory record', exact: true }).click();
  const record = page.getByLabel(/^Record [0-9a-f]/);
  await record.waitFor();
  assert.equal(await record.inputValue(), 'The smoke test code is amber-signal.');
  await record.fill('The smoke test code is violet-signal.');
  await page.getByRole('button', { name: 'Save correction' }).click();
  await page.getByRole('button', { name: 'Refresh memory' }).click();
  assert.equal(await record.inputValue(), 'The smoke test code is violet-signal.');
  await page.getByLabel('Upload document').setInputFiles({ name: 'smoke.txt', mimeType: 'text/plain',
    buffer: Buffer.from('إبداع المعرفة المحلية. Knowledge smoke test document.') });
  await page.getByText('smoke.txt', { exact: false }).waitFor();
  await page.getByRole('button', { name: 'Read', exact: true }).click();
  await page.getByText(/Knowledge smoke test document/).waitFor();
  await page.getByRole('button', { name: 'Export memory' }).click();
  await page.getByText(/Exported to/).waitFor();
  await page.getByRole('button', { name: 'Close memory' }).click();
  const input = page.getByPlaceholder('Type a message...');
  await input.fill('What is the smoke test code? Answer with only the code.');
  await input.press('Enter');
  await page.getByText('violet-signal', { exact: true }).first().waitFor({ timeout: 90000 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByText('violet-signal', { exact: true }).first().waitFor();
  await page.getByPlaceholder('Type a message...').fill('Use exa_web_search_exa now to search for the official llama.cpp GitHub repository. The search query must be only llama.cpp GitHub. If tool permission is denied, stop without using any other tool.');
  await page.getByPlaceholder('Type a message...').press('Enter');
  await page.getByRole('button', { name: 'Allow once', exact: true }).waitFor({ timeout: 90000 });
  await page.getByRole('button', { name: 'Allow once', exact: true }).click();
  await page.getByRole('heading', { name: 'Approve exact tool action' }).waitFor({ timeout: 15000 });
  assert.match(await page.locator('dialog[open]').innerText(), /exa_web_search_exa/);
  await page.locator('dialog[open]').getByRole('button', { name: 'Deny', exact: true }).click();
  await page.locator('dialog[open]').waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: 'Stop', exact: true }).waitFor({ state: 'hidden', timeout: 90000 });
  await page.getByRole('button', { name: 'Memory', exact: true }).click();
  await page.getByRole('button', { name: 'Delete record' }).click();
  await page.getByRole('button', { name: 'Delete document' }).click();
  await page.getByRole('button', { name: 'Delete document' }).waitFor({ state: 'hidden' });
  assert.equal(await page.getByRole('button', { name: 'Delete record' }).count(), 0);
  assert.deepEqual(errors, []);
  console.log('PASS: UI save/correct/import/read/export/live recall/reload history/exact external approval/deny/forget; no page errors.');
} finally {
  await browser.close();
}
