/* Explicit live opt-in. Isolated QA database required; no historical matrices. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.CLIENTSCOUT_QA_FRONTEND || 'http://127.0.0.1:5175';
if (process.env.CLIENTSCOUT_QA_LIVE_DISCOVERY !== 'true') throw new Error('Set CLIENTSCOUT_QA_LIVE_DISCOVERY=true explicitly; this submits one small provider search.');
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto(base + '/find-leads');
    await page.getByText('Backend connected', { exact: true }).waitFor();
    await page.getByPlaceholder('London, UK or latitude, longitude').fill('52.2053, 0.1218');
    await page.getByLabel('Business category or keyword').fill('cafe');
    await page.getByLabel('Result limit').fill('2');
    await page.getByRole('button', { name: 'Start search', exact: true }).click();
    await page.getByRole('button', { name: 'Retry search', exact: true }).waitFor({ timeout: 110000 });
    const id = new URL(page.url()).searchParams.get('discovery');
    const run = await (await page.request.get(base + '/api/discovery/searches/' + id)).json();
    fs.writeFileSync('/private/tmp/clientscout-qa/checkpoint-3b-live.json', JSON.stringify(run, null, 2));
    console.log('Live provider actual result:', JSON.stringify({ id, status: run.status, count: run.result?.items.length, error: run.error, cache_hit: run.result?.cache_hit }));
    if (run.status === 'complete') {
      assert.equal(run.result.cache_hit, false); assert(run.result.items.length <= 2);
      assert(run.result.items.every(i => i.provider === 'osm_overpass' && i.unverified && i.source_url.startsWith('https://www.openstreetmap.org/')));
      if (run.result.items.length) {
        await page.getByRole('checkbox', { name: /^Select / }).first().check();
        assert.equal(await page.getByRole('button', { name: 'Save selected · 1' }).isDisabled(), true);
        await page.getByRole('checkbox', { name: /I understand these source records/ }).check();
        await page.getByRole('button', { name: 'Save selected · 1' }).click();
        await page.getByText(/1 saved, 0 already saved/).waitFor();
        const saved = await (await page.request.get(base + '/api/discovery/saved')).json();
        assert.equal(saved.total, 1); assert.equal(saved.items[0].source_id, run.result.items[0].source_id);
        console.log('Chrome live review, licence gating and SQLite selected-save PASS');
      }
    } else {
      assert.equal(run.status, 'error'); assert.equal(run.result, null);
      await page.getByRole('alert').filter({ hasText: run.error }).waitFor();
      console.log('Chrome provider failure is visible with no substituted records PASS; live results NOT verified');
    }
    await page.reload();
    await page.getByRole('button', { name: 'Retry search', exact: true }).waitFor();
    for (const sample of [{ width: 1440, height: 1000, theme: 'light' }, { width: 320, height: 740, theme: 'dark' }]) {
      await page.setViewportSize(sample);
      await page.goto(base + '/settings');
      await page.getByRole('button', { name: sample.theme === 'light' ? 'Light' : 'Dark', exact: true }).click();
      await page.goto(base + '/find-leads?discovery=' + id);
      await page.getByRole('button', { name: 'Retry search', exact: true }).waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), sample.theme);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Horizontal overflow in discovery');
      await page.screenshot({ path: `/private/tmp/clientscout-qa/checkpoint-3b-${sample.width}-${sample.theme}.png`, fullPage: true });
      console.log(`Chrome discovery ${sample.width} ${sample.theme}: persisted source state, theme and no overflow PASS`);
    }
    await page.goto(base + '/saved-leads');
    await page.getByRole('heading', { name: /Saved discovered businesses/ }).waitFor();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.goto(base + '/');
    const metrics = await (await page.request.get(base + '/api/dashboard')).json();
    await page.getByText('Saved discoveries · ' + metrics.discovered_businesses, { exact: true }).waitFor();
    assert.equal(metrics.leads_found, 0);
    console.log('Chrome saved collection and real dashboard discovery count PASS');
    assert.deepEqual(errors, []); console.log('Chrome page errors: 0');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
