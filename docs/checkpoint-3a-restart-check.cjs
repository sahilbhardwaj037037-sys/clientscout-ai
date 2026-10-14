const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const page = await browser.newPage();
  const base = 'http://127.0.0.1:5175';
  try {
    const before = JSON.parse(fs.readFileSync('/private/tmp/clientscout-qa/checkpoint-3a-restart-snapshot.json'));
    const after = await (await page.request.get(base + '/api/audits?limit=100')).json();
    assert.deepEqual(after, before);
    const measured = after.items.find(run => run.report?.http_status === 200);
    assert(measured);
    assert.equal(measured.report.html.titles[0], 'Example Domain');
    assert.equal(measured.report.pagespeed.status, 'unavailable');
    assert(measured.report.pagespeed.cooldown_until);
    await page.goto(base + '/website-audit?audit=' + measured.id);
    await page.getByRole('heading', { name: 'Audit report #' + measured.id, exact: true }).waitFor();
    await page.getByText('Example Domain', { exact: true }).first().waitFor();
    await page.getByText('PageSpeed returned HTTP 429. No mobile metrics were substituted.').waitFor();
    console.log('Chrome real process restart: all audit states, evidence, timestamps and provider cooldown preserved exactly PASS');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
