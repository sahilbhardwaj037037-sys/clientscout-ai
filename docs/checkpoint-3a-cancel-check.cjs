const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = 'http://127.0.0.1:5175';
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(base + '/website-audit');
    await page.getByLabel('Public website URL').fill('https://example.org/');
    await page.getByLabel(/I have permission/).check();
    await page.getByRole('button', { name: 'Start audit', exact: true }).click();
    await page.getByRole('button', { name: 'Cancel audit' }).click();
    await page.getByText('Cancelled', { exact: true }).waitFor();
    const id = new URL(page.url()).searchParams.get('audit');
    const cancelled = await (await page.request.get(base + '/api/audits/' + id)).json();
    assert.equal(cancelled.status, 'cancelled');
    await page.reload();
    await page.getByText('Cancelled', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Cancel audit' }).count(), 0);
    const reports = await (await page.request.get(base + '/api/audits?limit=100')).json();
    fs.writeFileSync('/private/tmp/clientscout-qa/checkpoint-3a-restart-snapshot.json', JSON.stringify(reports));
    assert.deepEqual(errors, []);
    console.log('Chrome actual local cancellation, persisted state after reload, no stale cancel control, zero runtime errors PASS');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
