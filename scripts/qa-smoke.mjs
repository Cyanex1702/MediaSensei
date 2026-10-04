import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';

const api = process.env.NEXT_PUBLIC_CORE_API_URL || 'http://127.0.0.1:8810/api/v1';
const web = process.env.MEDIASENSEI_SMOKE_WEB_URL || 'http://127.0.0.1:3810';
async function json(path, init) {
  const response = await fetch(api + path, init);
  assert(response.ok, `${path}: ${response.status} ${await response.clone().text()}`);
  return response.json();
}
const post = (path, body) => json(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
const project = (await post('/projects', {name:'QA regression workspace'})).id;
const body = new FormData();
body.append('file', new File(['name,value\n' + Array.from({length:120}, (_, i) => `row-${i},${i}`).join('\n')], 'pagination.csv'));
await json(`/projects/${project}/assets`, {method:'POST', body});
for (let i=0; i<120; i++) {
  const {items} = await json(`/jobs?project_id=${project}`);
  if (items.every(job => job.state === 'completed')) break;
  assert(!items.some(job => ['failed','completed_with_errors','paused'].includes(job.state)), JSON.stringify(items));
  assert(i < 119, 'worker did not complete');
  await new Promise(resolve => setTimeout(resolve, 500));
}
const source = (await json(`/projects/${project}/tabular`)).items[0];
await post('/lab/datasets/from-table/' + source.id, {});
const browser = await chromium.launch({headless:true, ...(process.env.MEDIASENSEI_BROWSER_PATH ? {executablePath:process.env.MEDIASENSEI_BROWSER_PATH} : process.platform === 'win32' ? {channel:'msedge'} : {})});
await mkdir('.audit', {recursive:true});
const page = await browser.newPage({viewport:{width:1440,height:960}});
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.addInitScript(project => {
    localStorage.setItem('mediasensei.activeProject', project);
    localStorage.setItem('sensei-favorites', 'null');
    localStorage.setItem('sensei.recent', '{bad json');
    localStorage.setItem('sensei.selection.' + project, '{}');
  }, project);
  await page.goto(web);
  await page.getByText('API online', {exact:true}).waitFor();
  const nav = name => page.locator('.sensei-nav').getByRole('button', {name,exact:true}).click();
  for (const name of ['Overview','Sources','Library','Data Lab','Image Lab','Video Lab','Audio Lab','Knowledge Lab','Quality','Workflows','Versions','Exports','Jobs','Model Hub','Connections','Playground','Voices','Documentation','System']) {
    await nav(name);
    await page.waitForTimeout(150);
  }
  const catalogPattern = `**/api/v1/projects/${project}/assets`;
  await page.route(catalogPattern, route => route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({items:Array.from({length:205}, (_, i) => ({id:`qa-${i}`,project_id:project,sha256:'a'.repeat(64),original_filename:`qa-${i}.txt`,media_type:'document',byte_size:100,state:'active',created_at:'2026-09-30'}))})}));
  await nav('Library');
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await page.getByText('205 matching assets · Page 1 of 3', {exact:true}).waitFor();
  await page.getByRole('button',{name:'Next assets',exact:true}).click();
  await page.getByText('qa-100.txt',{exact:true}).waitFor();
  assert.equal(await page.getByText('qa-0.txt',{exact:true}).count(), 0);
  await page.getByLabel('Library modality').selectOption('image');
  await page.getByText('No assets match. Import files from Overview.',{exact:true}).waitFor();
  await page.getByLabel('Library modality').selectOption('all');
  await page.unroute(catalogPattern);
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await nav('Data Lab');
  await page.getByRole('tab', {name:'Explore',exact:true}).waitFor();
  assert.equal(await page.getByRole('tab', {name:'Explore',exact:true}).getAttribute('aria-selected'), 'true');
  await page.locator('.lab-grid tbody tr').first().waitFor();
  await page.getByRole('button', {name:'Next rows',exact:true}).click();
  await page.locator('.lab-grid').getByText('row-50', {exact:true}).waitFor();
  await page.getByPlaceholder('Search this table…').fill('row-119');
  await page.locator('.lab-grid').getByText('row-119', {exact:true}).waitFor();
  assert.equal(await page.locator('.lab-grid tbody tr').count(), 1);
  await page.getByPlaceholder('Search this table…').fill('');
  await page.locator('.lab-grid').getByText('row-0', {exact:true}).waitFor();
  await page.getByRole('button', {name:'Preview',exact:true}).click();
  await page.getByRole('heading', {name:'Preview · first 100 rows'}).waitFor();
  await page.getByRole('button', {name:'Run',exact:true}).click();
  await page.getByText('Operation queued. Follow its progress in the job drawer.', {exact:true}).waitFor();
  await nav('Overview');
  await page.screenshot({path:'.audit/qa-overview.png', fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2), false);
  await page.screenshot({path:'.audit/qa-mobile.png', fullPage:true});
  assert.deepEqual(errors, []);
  // Browser privacy settings must not prevent startup.
  const blocked = await browser.newPage();
  blocked.on('pageerror', error => errors.push(error.message));
  await blocked.addInitScript(() => Object.defineProperty(window, 'localStorage', {get() {throw new DOMException('Blocked', 'SecurityError');}}));
  await blocked.goto(web);
  await blocked.getByText('API online', {exact:true}).waitFor();
  await blocked.locator('.sensei-nav').getByRole('button', {name:'Data Lab',exact:true}).click();
  await blocked.waitForTimeout(500);
  assert.deepEqual(errors, []);
  const report = {ok:true, project, checks:['all 19 navigation pages','invalid saved preference recovery','blocked browser storage','Library pagination and modality empty states','Data Lab navigation selects Explore','search resets pagination','preview and enqueue with corrupt recents','mobile overview has no overflow'], errors};
  await writeFile('.audit/qa-browser.json', JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} catch (error) {
  await page.screenshot({path:'.audit/qa-failure.png',fullPage:true});
  throw error;
} finally { await browser.close(); }
