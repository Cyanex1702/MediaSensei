import { join } from 'node:path';
import { createRequire } from 'node:module';
import { strict as assert } from 'node:assert';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const browser = await chromium.launch({ headless: true, ...(process.env.MEDIASENSEI_BROWSER_PATH ? {executablePath:process.env.MEDIASENSEI_BROWSER_PATH}: {}) });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const base = process.env.MEDIASENSEI_SMOKE_WEB_URL || 'http://127.0.0.1:3765';
try {
  await page.goto(base);
  await page.getByText('API online', {exact:true}).waitFor({timeout:60000});
  await page.getByPlaceholder('New project name').fill('Browser audit');
  await page.getByRole('button', {name:'New project',exact:true}).click();
  await page.getByText('Created project', {exact:false}).waitFor();
  const projectSelect = page.locator('main select').first();
  const projectId = await projectSelect.inputValue();
  assert.equal(await page.locator('input[type=file]').nth(1).getAttribute('webkitdirectory'), '');
  const fixture = Buffer.from('Night cameras observed foxes near the river. Foxes are active after midnight.');
  await page.locator('input[type=file]').first().setInputFiles([{name:'field notes.txt',mimeType:'text/plain',buffer:fixture}]);
  await page.getByText('Imported 1 file.', {exact:false}).waitFor({timeout:30000});
  const fixtures = process.env.MEDIASENSEI_SMOKE_FIXTURES;
  if (fixtures) {
    await page.locator('input[type=file]').first().setInputFiles(['photo.png','table.csv','nested.zip'].map(name => join(fixtures,name)));
    await page.getByText('Imported 3 files.',{exact:false}).waitFor({timeout:60000});
    const apiBase = process.env.NEXT_PUBLIC_CORE_API_URL;
    for (let attempt=0; attempt<120; attempt++) {
      const jobs = await (await fetch(`${apiBase}/jobs?project_id=${projectId}`)).json();
      if(jobs.items.every(job => job.state === 'completed')) break;
      if(attempt===119) throw new Error(`Jobs did not complete: ${JSON.stringify(jobs)}`);
      await new Promise(resolve => setTimeout(resolve,500));
    }
  }
  await page.getByRole('button',{name:'Library',exact:true}).first().click();
  await page.locator('main').getByText('field notes.txt',{exact:true}).waitFor();
  if(fixtures) { await page.getByText('photo.png',{exact:true}).waitFor(); await page.getByText('zip notes.txt',{exact:true}).waitFor(); }
  await page.getByRole('button',{name:'Knowledge Lab',exact:true}).first().click();
  await page.getByRole('button',{name:'Index documents',exact:true}).click();
  await page.locator('textarea').fill('foxes river');
  await page.waitForTimeout(2000);
  await page.getByRole('button',{name:'Search indexed content',exact:true}).click();
  await page.getByText('foxes',{exact:false}).first().waitFor({timeout:30000});
  await page.getByRole('button',{name:'Jobs',exact:true}).first().click();
  await page.locator('main').getByText('document-index',{exact:false}).first().waitFor();
  await page.getByRole('button',{name:'System',exact:true}).first().click();
  await page.getByText('Backend health',{exact:false}).waitFor();
  await page.getByRole('button',{name:'Rescan plugins',exact:true}).click();
  await page.getByText('Plugin rescan submitted successfully.',{exact:true}).waitFor();
  // Verify an API failure is not interpreted as loss of health.
  await page.route('**/api/v1/projects/*/assets', route => route.request().method()==='GET' ? route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({detail:{code:'TEST_FAILURE',message:'Simulated catalog error'}})}) : route.continue());
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await page.getByText('Simulated catalog error',{exact:false}).waitFor();
  assert(await page.getByText('API online',{exact:true}).isVisible());
  await page.unroute('**/api/v1/projects/*/assets');
  await page.getByRole('button',{name:'Overview',exact:true}).first().click();
  await page.locator('input[type=file]').first().setInputFiles({name:'invalid.exe',mimeType:'application/octet-stream',buffer:Buffer.from('invalid')});
  await page.getByText('UNSUPPORTED_ASSET',{exact:false}).waitFor();
  assert(await page.getByText('API online',{exact:true}).isVisible());
  await page.reload();
  await page.getByText('API online',{exact:true}).waitFor();
  assert(await page.locator('main select').first().inputValue());
  await page.setViewportSize({width:390,height:844});
  assert(await page.getByRole('button',{name:'Library',exact:true}).first().isVisible());
  assert.deepEqual(errors,[]);
  if(process.env.MEDIASENSEI_SCREENSHOT) await page.screenshot({path:process.env.MEDIASENSEI_SCREENSHOT,fullPage:true});
  console.log(JSON.stringify({ok:true,projectId,checks:['browser API connection','project creation','multipart upload',...(fixtures?['multiple file upload','ZIP upload and worker processing']:[]),'library','document retrieval','jobs','system','failure health isolation','invalid upload','persistence','mobile navigation'],pageErrors:errors}));
} finally { await browser.close(); }
