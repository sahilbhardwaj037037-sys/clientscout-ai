/* Run only after restarting the backend used by checkpoint-2-browser-check.cjs.
   This script deletes QA fixtures from an isolated database. Never use a real lead database. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.CLIENTSCOUT_QA_FRONTEND || 'http://127.0.0.1:5175';
const saved = JSON.parse(fs.readFileSync('/private/tmp/clientscout-qa/checkpoint-2-persisted.json'));
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    const reopened = (await (await page.request.get(base + '/api/leads')).json()).items;
    assert.deepEqual(reopened, saved);
    assert(reopened.every(lead => lead.business_name.startsWith('QA fixture')));
    console.log('Actual backend process restart preserves every stored lead field and timestamp PASS');
    const csv = reopened.find(lead => lead.source === 'csv');
    const manual = reopened.find(lead => lead.source === 'manual');
    assert.equal(manual.notes, 'QA notes changed and persisted');
    await page.goto(base + '/saved-leads');
    await page.getByRole('heading', { name: 'Your collection · 2' }).waitFor();
    await page.screenshot({ path: '/private/tmp/clientscout-qa/checkpoint-2-mobile-saved.png', fullPage: true });
    await page.goto(base + '/saved-leads/' + manual.id);
    await page.getByRole('heading', { name: 'Edit lead' }).waitFor();
    await page.screenshot({ path: '/private/tmp/clientscout-qa/checkpoint-2-mobile-detail.png', fullPage: true });
    await page.goto(base + '/saved-leads/' + csv.id);
    await page.getByRole('button', { name: 'Delete lead', exact: true }).click();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.equal((await page.request.get(base + '/api/leads/' + csv.id)).status(), 200);
    await page.getByRole('button', { name: 'Delete lead', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm deletion' }).click();
    await page.getByRole('heading', { name: 'Your collection · 1' }).waitFor();
    assert.equal((await page.request.get(base + '/api/leads/' + csv.id)).status(), 404);
    console.log('Chrome delete cancellation and confirmed persisted deletion PASS');
    for (let index = 0; index < 20; index++) {
      const response = await page.request.post(base + '/api/leads', { data: { website_url: `https://qa-pagination-${index}.example.org`, business_name: `QA fixture page ${index}` } });
      assert.equal(response.status(), 201);
    }
    await page.goto(base + '/saved-leads');
    await page.getByRole('heading', { name: 'Your collection · 21' }).waitFor();
    assert.equal(await page.locator('.lead-row').count(), 20);
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await page.getByText('21–21 of 21').waitFor();
    assert.equal(await page.locator('.lead-row').count(), 1);
    assert.equal(await page.getByRole('button', { name: 'Next', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: 'Previous', exact: true }).click();
    await page.getByText('1–20 of 21').waitFor();
    await page.goto(base + '/saved-leads/999999');
    await page.getByRole('alert').filter({ hasText: 'Lead not found.' }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Save changes' }).count(), 0);
    assert.deepEqual(errors, []);
    console.log('Chrome real pagination, missing detail recovery and zero runtime errors PASS');
    const fixtures = (await (await page.request.get(base + '/api/leads?limit=100')).json()).items;
    for (const lead of fixtures) {
      assert(lead.business_name.startsWith('QA fixture'));
      assert.equal((await page.request.delete(base + '/api/leads/' + lead.id)).status(), 204);
    }
    assert.equal((await (await page.request.get(base + '/api/dashboard')).json()).leads_found, 0);
    console.log('Isolated QA fixtures cleaned up; workspace database untouched PASS');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
