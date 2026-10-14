/* One explicit, modest live query in an isolated QA database; no historical matrices. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.CLIENTSCOUT_QA_FRONTEND || 'http://127.0.0.1:5175';
if (process.env.CLIENTSCOUT_QA_LIVE_DISCOVERY !== 'true') throw new Error('Explicit live opt-in and isolated migrated QA database required.');
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base+'/find-leads');
    await page.getByText('Backend connected',{exact:true}).waitFor();
    await page.getByPlaceholder('London, UK or latitude, longitude').fill('51.5074, -0.1278');
    await page.getByLabel('Business category or keyword').fill('restaurants');
    await page.getByLabel('Result limit').fill('2');
    await page.getByLabel('Search scope').selectOption('nearby');
    await page.getByLabel('Nearby radius').selectOption('500');
    await page.getByRole('button',{name:'Start search',exact:true}).click();
    await page.getByRole('button',{name:'Retry search',exact:true}).waitFor({timeout:110000});
    const id=new URL(page.url()).searchParams.get('discovery');
    const run=await (await page.request.get(base+'/api/discovery/searches/'+id)).json();
    fs.writeFileSync('/private/tmp/clientscout-qa/discovery-diagnostics-live.json',JSON.stringify(run,null,2));
    console.log('Actual modest live search:',JSON.stringify({id,status:run.status,count:run.result?.items.length,error:run.error,requests:run.diagnostics.map(d=>({stage:d.stage,http_status:d.http_status,code:d.code,bytes:d.response_bytes,elapsed_ms:d.elapsed_ms,remark:d.provider_remark}))}));
    assert(run.diagnostics.length>=1 && run.diagnostics.length<=2); // An explicit short HTTP backoff may permit one retry only.
    assert(run.diagnostics.every(d=>d.stage==='business_search' && d.query.includes('(around:500,') && d.query.includes('["amenity"="restaurant"]') && !d.query.includes('(area.target)')));
    await page.getByText('Request diagnostics',{exact:true}).click();
    if (run.status==='complete') {
      assert.equal(run.result.radius_metres,500); assert.equal(run.result.search_scope,'nearby');
      assert(run.result.items.length<=2 && run.result.items.every(item=>item.category==='restaurant' && item.unverified));
      await page.getByText(/500 m nearby sample/).first().waitFor();
    } else {
      assert.equal(run.status,'error'); assert.equal(run.result,null);
      await page.getByRole('alert').filter({hasText:run.error}).waitFor();
    }
    await page.screenshot({path:'/private/tmp/clientscout-qa/discovery-diagnostics-desktop.png',fullPage:true});
    await page.setViewportSize({width:320,height:740});
    await page.goto(base+'/settings');
    await page.getByRole('button',{name:'Dark',exact:true}).click();
    await page.goto(base+'/find-leads?discovery='+id);
    await page.getByRole('button',{name:'Retry search',exact:true}).waitFor();
    await page.getByText('Request diagnostics',{exact:true}).click();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile diagnostic overflow');
    await page.screenshot({path:'/private/tmp/clientscout-qa/discovery-diagnostics-mobile.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('Chrome actual connection, persisted scope/evidence, desktop light/mobile dark and diagnostic wrapping PASS; no second search');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
