// Run after npm install --prefix .cache/browser playwright. Uses installed Edge.
const { chromium } = require('../../.cache/browser/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ timezoneId: 'America/Los_Angeles' });
  const page = await context.newPage();
  const base = process.env.QA_WEB_URL || 'http://localhost:3001';
  const results = {};
  try {
    await page.goto(base, { waitUntil: 'networkidle' });
    const times = await page.locator('.fixture-card time').evaluateAll(nodes => nodes.map(n => ({iso:n.dateTime, text:n.textContent})));
    assert(times.length > 0);
    for (const t of times) {
      const expected = new Intl.DateTimeFormat('ko-KR', {timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit'}).format(new Date(t.iso));
      assert.equal(t.text, expected);
    }
    results.QA04 = {status:'PASS', timezone:'America/Los_Angeles', cards:times.length};
    await page.setViewportSize({width:390,height:844});
    const mobile = await page.locator('.pick-prob-value').first().evaluate(n=>parseFloat(getComputedStyle(n).fontSize));
    const outcome = await page.locator('.pick-outcome').first().evaluate(n=>parseFloat(getComputedStyle(n).fontSize));
    assert.equal(mobile, 25.6);
    assert.equal(outcome, 18.4);
    results.QA08 = {status:'PASS', width:390, probabilityPx:mobile, outcomePx:outcome};
    await page.goto(base+'/combinations', {waitUntil:'networkidle'});
    const buttons=page.locator('.pick-buttons button');
    await buttons.nth(0).click();
    const rows=page.locator('.pick-buttons');
    for(let i=1;i<await rows.count();i++) {
      const b=rows.nth(i).locator('button').first();
      if(await b.isEnabled()) {await b.click();break;}
    }
    let release, started;
    const arrival=new Promise(r=>started=r);
    await page.route('**/api/combinations',async route=>{
      started();
      await new Promise(r=>release=r);
      await route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({detail:'STALE_SENTINEL'})}).catch(()=>{});
    });
    await page.getByRole('button',{name:'조합 분석',exact:true}).click();
    await arrival;
    await page.getByRole('button',{name:'초기화',exact:true}).click();
    release();
    await page.waitForTimeout(250);
    assert.equal(await page.getByText('STALE_SENTINEL',{exact:true}).count(),0);
    assert.equal(await page.getByText('계산 중…',{exact:true}).count(),0);
    results.QA01={status:'PASS',scenario:'reset during delayed HTTP error'};
    fs.writeFileSync('.cache/browser-regression.json',JSON.stringify(results,null,2));
    console.log(JSON.stringify(results));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
