const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const health = await page.request.get('http://127.0.0.1:8000/api/health');
  assert.equal(health.status(), 200);
  console.log('Direct API health:', await health.json());
  for (const viewport of [{ width: 1440, height: 900 }, { width: 820, height: 1180 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
    await page.setViewportSize(viewport);
    for (const theme of ['light', 'dark']) {
      await page.goto('http://127.0.0.1:5173/settings');
      await page.getByRole('button', { name: theme === 'light' ? 'Light' : 'Dark', exact: true }).click();
      for (const path of ['/', '/find-leads', '/website-audit', '/proposal-studio', '/saved-leads', '/settings']) {
        await page.goto('http://127.0.0.1:5173' + path);
        await page.getByText('Backend connected', { exact: true }).waitFor();
        assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), theme);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Overflow at ${viewport.width} ${theme} ${path}`);
      }
      await page.goto('http://127.0.0.1:5173/');
      await page.getByText('Backend connected', { exact: true }).waitFor();
      await page.screenshot({ path: `/private/tmp/clientscout-qa/${viewport.width}-${theme}.png`, fullPage: true });
      console.log(`${viewport.width}x${viewport.height} ${theme}: six routes, persisted theme, live connection, no horizontal overflow PASS`);
    }
  }
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('dialog').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Close navigation' }).evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.getByRole('link', { name: 'Settings', exact: true }).evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Tab');
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('button', { name: 'Open navigation' }).evaluate(el => el === document.activeElement), true);
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('link', { name: 'Saved Leads', exact: true }).click();
  await page.getByRole('heading', { name: 'Saved Leads', exact: true }).waitFor();
  assert.equal(await page.getByRole('dialog').count(), 0);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('button', { name: 'Collapse sidebar' }).click();
  assert.equal(await page.locator('#sidebar').evaluate(el => el.getBoundingClientRect().width), 72);
  await page.getByRole('button', { name: 'Expand sidebar' }).click();
  assert.equal(await page.locator('#sidebar').evaluate(el => el.getBoundingClientRect().width), 248);
  await page.route('**/api/health', route => route.abort());
  await page.goto('http://127.0.0.1:5173/');
  await page.getByRole('alert').waitFor();
  await page.unroute('**/api/health');
  await page.getByRole('button', { name: 'Retry' }).click();
  await page.getByText('Backend connected', { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('Drawer focus trap/Escape, mobile navigation, desktop collapse, network failure/retry, zero runtime errors PASS');
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
