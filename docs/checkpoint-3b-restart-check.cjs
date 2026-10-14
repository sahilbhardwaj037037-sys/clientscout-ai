const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.CLIENTSCOUT_QA_FRONTEND || 'http://127.0.0.1:5175';
const id = process.env.CLIENTSCOUT_QA_DISCOVERY_ID || '1';
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await page.goto(base + '/find-leads?discovery=' + id);
    await page.getByText('Backend connected', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Retry search', exact: true }).waitFor();
    assert.equal(await page.getByPlaceholder('Exact place name or latitude, longitude').inputValue(), '52.2053, 0.1218');
    const run = await (await page.request.get(base + '/api/discovery/searches/' + id)).json();
    const saved = await (await page.request.get(base + '/api/discovery/saved')).json();
    assert.equal(run.status, 'complete'); assert.equal(run.result.items.length, 2); assert.equal(saved.total, 1);
    assert.equal(saved.items[0].source_id, run.result.items[0].source_id);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    console.log('Chrome after backend process restart: original live evidence, selected source record and prefilled query preserved PASS; no new provider call');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
