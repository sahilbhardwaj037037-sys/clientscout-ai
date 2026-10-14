/* Real public requests against example.com, in an isolated QA database. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.CLIENTSCOUT_QA_FRONTEND || 'http://127.0.0.1:5175';
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(base + '/website-audit');
    await page.getByText('Backend connected', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Start audit', exact: true }).isDisabled(), true);
    await page.getByLabel('Public website URL').fill('https://example.com/');
    await page.getByLabel(/I have permission/).check();
    if (process.env.CLIENTSCOUT_QA_PAGESPEED) await page.getByLabel(/Include Google PageSpeed/).check();
    await page.getByRole('button', { name: 'Start audit', exact: true }).click();
    await page.getByRole('button', { name: 'Cancel audit' }).waitFor();
    console.log('Chrome real audit start, visible progress and cancellation control PASS');
    const id = new URL(page.url()).searchParams.get('audit');
    let run;
    const deadline = Date.now() + 115000;
    while (Date.now() < deadline) {
      const response = await page.request.get(base + '/api/audits/' + id);
      if (response.ok()) {
        run = await response.json();
        if (['complete', 'partial', 'error', 'blocked', 'cancelled', 'interrupted'].includes(run.status)) break;
      }
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
    console.log('Actual public audit result:', JSON.stringify({ id: run.id, status: run.status, error: run.error, http: run.report?.http_status, titles: run.report?.html?.titles, pagespeed: run.report?.pagespeed }));
    fs.writeFileSync('/private/tmp/clientscout-qa/checkpoint-3a-real-audit.json', JSON.stringify(run, null, 2));
    assert(['complete', 'partial'].includes(run.status), 'Real public audit must produce observations, not fixture findings');
    assert.equal(run.report.http_status, 200);
    assert.equal(run.report.tls_verified, true);
    assert(run.report.html.titles[0].includes('Example Domain'));
    assert(run.report.requests.every(entry => entry.connections.every(connection => connection.connected_ip)));
    await page.getByText('Example Domain', { exact: true }).first().waitFor();
    await page.reload();
    await page.getByRole('heading', { name: 'Audit report #' + id, exact: true }).waitFor();
    for (const viewport of [{ width: 1440, height: 900 }, { width: 820, height: 1180 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
      await page.setViewportSize(viewport);
      for (const theme of ['light', 'dark']) {
        await page.goto(base + '/settings');
        await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click();
        await page.goto(base + '/website-audit?audit=' + id);
        await page.getByRole('heading', { name: 'Audit report #' + id, exact: true }).waitFor();
        assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), theme);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Report overflow at ' + viewport.width);
        await page.screenshot({ path: `/private/tmp/clientscout-qa/checkpoint-3a-${viewport.width}-${theme}.png`, fullPage: true });
        console.log(`Chrome real persisted report ${viewport.width} ${theme}: theme, source evidence, no horizontal overflow PASS`);
      }
    }
    // Rejected requests produce no fictional report. Retry path respects cooldown if still active.
    await page.getByRole('button', { name: 'Retry audit' }).click();
    await page.waitForFunction((originalId) => document.querySelector('[role="alert"]') || new URLSearchParams(location.search).get('audit') !== originalId, id, { timeout: 10000 }).catch(() => {});
    const currentId = new URL(page.url()).searchParams.get('audit');
    if (currentId !== id) {
      await page.getByRole('button', { name: 'Cancel audit' }).click();
      await page.getByText('Cancelled', { exact: true }).waitFor();
      const cancelled = await (await page.request.get(base + '/api/audits/' + currentId)).json();
      assert.equal(cancelled.status, 'cancelled');
      console.log('Chrome manual retry created a separate run; cancellation confirmed in SQLite PASS');
    } else {
      await page.getByRole('alert').filter({ hasText: /cooldown|rate limit/ }).waitFor();
      console.log('Chrome retry respected persisted hostname cooldown PASS');
    }
    await page.getByLabel('Public website URL').fill('http://127.0.0.1');
    await page.getByLabel(/I have permission/).check();
    await page.getByRole('button', { name: 'Start audit', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: /local addresses|Private|public/ }).waitFor();
    assert.deepEqual(errors, []);
    console.log('Chrome blocked unsafe input without outbound request or invented success; zero runtime errors PASS');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
