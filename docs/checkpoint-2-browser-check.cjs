/* Run against an isolated QA database, never the user's lead database. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.CLIENTSCOUT_QA_FRONTEND || 'http://127.0.0.1:5173';
const api = process.env.CLIENTSCOUT_QA_API || 'http://127.0.0.1:8000';
const screenshots = process.env.CLIENTSCOUT_QA_SCREENSHOTS || '/private/tmp/clientscout-qa';
const { mkdirSync } = require('node:fs');

(async () => {
  mkdirSync(screenshots, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    const direct = await page.request.get(api + '/api/health');
    const proxied = await page.request.get(base + '/api/health');
    assert.equal(direct.status(), 200); assert.equal(proxied.status(), 200);
    assert.deepEqual(await proxied.json(), await direct.json());
    assert.equal((await direct.json()).database, 'ready');
    await page.goto(base + '/settings');
    await page.getByText('Backend connected', { exact: true }).waitFor();
    await page.getByText(api, { exact: true }).waitFor();
    console.log('Actual Chrome direct/proxied health and configured backend target PASS:', api);
    if (process.env.CLIENTSCOUT_QA_CONNECTION_ONLY) return;
    assert.equal((await (await page.request.get(base + '/api/dashboard')).json()).leads_found, 0, 'Use an empty isolated QA database');
    for (const viewport of [{ width: 1440, height: 900 }, { width: 820, height: 1180 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
      await page.setViewportSize(viewport);
      for (const theme of ['light', 'dark']) {
        await page.goto(base + '/settings');
        await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click();
        for (const path of ['/', '/find-leads', '/website-audit', '/proposal-studio', '/saved-leads', '/settings']) {
          await page.goto(base + path);
          await page.getByText('Backend connected', { exact: true }).waitFor();
          assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), theme);
          assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Overflow ${viewport.width} ${theme} ${path}`);
        }
        await page.goto(base + '/');
        await page.getByText('Saved in your local database').waitFor();
        await page.screenshot({ path: `${screenshots}/checkpoint-2-${viewport.width}-${theme}.png`, fullPage: true });
        console.log(`${viewport.width}x${viewport.height} ${theme}: six routes + theme + live connection + no overflow PASS`);
      }
    }
    await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('dialog').waitFor();
    await page.keyboard.press('Shift+Tab');
    assert(await page.getByRole('link', { name: 'Settings', exact: true }).evaluate(el => el === document.activeElement));
    await page.keyboard.press('Escape');
    assert(await page.getByRole('button', { name: 'Open navigation' }).evaluate(el => el === document.activeElement));
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole('button', { name: 'Collapse sidebar' }).click();
    assert.equal(await page.locator('#sidebar').evaluate(el => el.getBoundingClientRect().width), 72);
    await page.getByRole('button', { name: 'Expand sidebar' }).click();
    assert.equal(await page.locator('#sidebar').evaluate(el => el.getBoundingClientRect().width), 248);
    await page.goto(base + '/find-leads');
    await page.getByLabel('Website URL').fill('https://checkpoint2-manual.example.org');
    await page.getByLabel('Business name (optional)', { exact: true }).fill('QA fixture — manual lead');
    await page.getByLabel('Notes', { exact: true }).fill('User-supplied QA notes');
    await page.getByRole('button', { name: 'Save lead', exact: true }).click();
    await page.getByText('Lead saved to your local database.', { exact: false }).waitFor();
    await page.getByRole('link', { name: 'View QA fixture — manual lead' }).click();
    await page.getByRole('heading', { name: 'Lead details', exact: true }).waitFor();
    const detailPath = new URL(page.url()).pathname;
    await page.getByLabel('Status', { exact: true }).selectOption('shortlisted');
    await page.getByLabel('Notes', { exact: true }).fill('QA notes changed and persisted');
    await page.getByRole('button', { name: 'Save changes' }).click();
    await page.getByText('Changes saved to your local database.').waitFor();
    await page.reload();
    await page.getByLabel('Notes', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('Notes', { exact: true }).inputValue(), 'QA notes changed and persisted');
    assert.equal(await page.getByLabel('Status', { exact: true }).inputValue(), 'shortlisted');
    await page.goto(base + '/find-leads');
    await page.getByLabel('Website URL').fill('http://www.checkpoint2-manual.example.org/contact');
    await page.getByRole('button', { name: 'Save lead', exact: true }).click();
    await page.getByRole('link', { name: 'Open existing lead' }).waitFor();
    await page.getByLabel('Website URL').fill('http://localhost');
    await page.getByRole('button', { name: 'Save lead', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'local addresses' }).waitFor();
    await page.getByLabel('CSV file').setInputFiles({ name: 'qa-fixtures.csv', mimeType: 'text/csv', buffer: Buffer.from('website_url,business_name,status,notes\nhttps://checkpoint2-csv.example.org,QA fixture — CSV lead,contacted,"Comma, retained"\nhttps://checkpoint2-manual.example.org,Duplicate,new,Ignored\nhttp://127.0.0.1,Invalid,new,Skipped\n') });
    await page.getByRole('button', { name: 'Import CSV', exact: true }).click();
    await page.getByText('Import finished: 1 saved, 1 duplicates skipped, 1 invalid rows.').waitFor();
    await page.goto(base + '/');
    await page.getByText('Saved in your local database').waitFor();
    assert.equal(await page.locator('.metric').first().locator('strong').innerText(), '2');
    await page.getByText('Shortlisted · 1', { exact: true }).waitFor();
    await page.getByText('Contacted · 1', { exact: true }).waitFor();
    await page.getByRole('link', { name: /QA fixture — CSV lead/ }).waitFor();
    await page.goto(base + '/saved-leads');
    await page.getByLabel('Filter by status').selectOption('shortlisted');
    await page.getByRole('button', { name: 'Apply filters' }).click();
    await page.getByRole('heading', { name: 'Your collection · 1' }).waitFor();
    assert.equal(await page.getByRole('link', { name: /QA fixture — CSV lead/ }).count(), 0);
    await page.getByRole('button', { name: 'Reset', exact: true }).click();
    await page.getByRole('heading', { name: 'Your collection · 2' }).waitFor();
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
      await page.setViewportSize(viewport);
      for (const path of ['/saved-leads', detailPath]) {
        await page.goto(base + path); await page.getByText('Backend connected', { exact: true }).waitFor();
        await page.getByRole('heading', { name: path === detailPath ? 'Edit lead' : 'Your collection · 2', exact: true }).waitFor();
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
      }
    }
    const snapshot = (await (await page.request.get(base + '/api/leads')).json()).items;
    require('node:fs').writeFileSync(`${screenshots}/checkpoint-2-persisted.json`, JSON.stringify(snapshot));
    assert.equal(errors.length, 0, JSON.stringify(errors));
    console.log('Actual Chrome manual create, duplicate/invalid errors, notes/status edits, reload persistence, CSV partial import, database metrics/statuses, filters, populated responsive views, drawer and collapse PASS');
    await page.route('**/api/health', route => route.abort());
    await page.goto(base + '/settings');
    await page.getByRole('alert').waitFor();
    assert.equal(await page.getByText(/Start FastAPI on/).count(), 0);
    await page.unroute('**/api/health');
    await page.getByRole('button', { name: 'Retry', exact: true }).click();
    await page.getByText('Backend connected', { exact: true }).waitFor();
    console.log('Port-independent error and real retry PASS');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
