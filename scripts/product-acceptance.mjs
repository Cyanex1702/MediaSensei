import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {join} from 'node:path';
import {mkdir,writeFile} from 'node:fs/promises';
const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
await mkdir('.audit',{recursive:true});
const api=process.env.NEXT_PUBLIC_CORE_API_URL;const web=process.env.MEDIASENSEI_SMOKE_WEB_URL;
try{
 await page.goto(web);await page.getByText('API online',{exact:true}).waitFor();
 await page.getByPlaceholder('New project name').fill('Repair acceptance');await page.getByRole('button',{name:'New project',exact:true}).click();await page.getByText('Created project',{exact:false}).waitFor();
 const project=await page.locator('main select').first().inputValue();
 await page.getByLabel('Choose CSV/TSV delimiter and preserve text identifiers before upload').check();
 await page.locator('input[type=file]').first().setInputFiles({name:'identifiers.csv',mimeType:'text/csv',buffer:Buffer.from('id;amount\n00123;10\n')});
 await page.getByRole('dialog').waitFor();await page.getByLabel('Import source').selectOption(';');await page.getByLabel('Keep all columns as text (preserve identifiers and leading zeros)').check();await page.getByRole('button',{name:'Import selected source',exact:true}).click();await page.getByText('Imported 1 file.',{exact:false}).waitFor();
 for(let i=0;i<60;i++){const {items}=await(await fetch(`${api}/projects/${project}/tabular`)).json();const ds=items.find(x=>x.name==='identifiers');if(Array.isArray(ds?.profile?.sample)){assert.equal(ds.profile.sample[0].id,'00123');break;}if(i===59)throw Error('Identifier processing timed out');await page.waitForTimeout(500);}

 await page.locator('input[type=file]').first().setInputFiles(join(process.env.MEDIASENSEI_SMOKE_FIXTURES,'two.db'));
 await page.getByRole('dialog').waitFor();await page.getByLabel('Import source').selectOption('sales');await page.getByRole('button',{name:'Import selected source',exact:true}).click();await page.getByText('Imported 1 file.',{exact:false}).waitFor();
 for(let i=0;i<60;i++){const {items}=await(await fetch(`${api}/projects/${project}/tabular`)).json();if(Array.isArray(items[0]?.profile?.sample)){assert.deepEqual(items[0].profile.sample,[{amount:999}]);break;}if(i===59)throw Error('Source processing timed out');await page.waitForTimeout(500);}
 await page.locator('.sensei-nav').getByRole('button',{name:'Library',exact:true}).click();await page.getByLabel('Library modality').selectOption('tabular');await page.getByLabel('Collection name').fill('Working tables');await page.getByRole('button',{name:'Save current filters',exact:true}).click();await page.getByRole('button',{name:'Working tables',exact:true}).waitFor();
 await page.reload();await page.locator('.sensei-nav').getByRole('button',{name:'Library',exact:true}).click();await page.getByRole('button',{name:'Working tables',exact:true}).click();assert.equal(await page.getByLabel('Library modality').inputValue(),'tabular');
 await page.locator('.sensei-nav').getByRole('button',{name:'Data Lab',exact:true}).click();await page.getByRole('button',{name:'Refresh imports',exact:true}).click();await page.getByLabel('Create from imported table').selectOption({label:'two'});
 await page.locator('.data-lab table th').filter({hasText:'amount'}).first().waitFor();
 await page.locator('.sensei-nav').getByRole('button',{name:'Quality',exact:true}).click();await page.getByRole('button',{name:'Add quality rule',exact:true}).waitFor();await page.getByRole('button',{name:'Add quality rule',exact:true}).click();await page.getByLabel('Rule check 1').selectOption('maximum');await page.getByLabel('Rule value 1').fill('100');await page.getByRole('button',{name:'Save and run checks',exact:true}).click();await page.getByText('Needs attention: 1 of 1 rows fail checks. Revision 0.',{exact:true}).waitFor();
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Download quality report',exact:true}).click();await(await downloadPromise).saveAs('.audit/quality-report.json');
 await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'.audit/quality-contract.png',fullPage:true});
 let releaseLoad;const loadGate=new Promise(resolve=>{releaseLoad=resolve});await page.route('**/api/v1/contracts/*',async route=>{if(route.request().method()==='GET')await loadGate;await route.continue()});
 await page.reload();await page.locator('.sensei-nav').getByRole('button',{name:'Quality',exact:true}).click();await page.getByRole('button',{name:'Save and run checks',exact:true}).waitFor();assert(await page.getByRole('button',{name:'Save and run checks',exact:true}).isDisabled());const loadedContract=page.waitForResponse(r=>r.url().includes('/api/v1/contracts/')&&r.request().method()==='GET');releaseLoad();await loadedContract;await page.unroute('**/api/v1/contracts/*');assert.equal(await page.getByLabel('Rule value 1').inputValue(),'100');
 await page.locator('.sensei-nav').getByRole('button',{name:'Sources',exact:true}).click();await page.getByLabel('Acquisition request').fill('Find 10 CSV datasets about houses');await page.getByRole('button',{name:'Preview acquisition plan',exact:true}).click();await page.getByRole('alert').filter({hasText:'images only'}).waitFor();
 await page.getByLabel('Acquisition request').fill('Find 10 images of red foxes, CC0 only');await page.getByRole('button',{name:'Preview acquisition plan',exact:true}).click();await page.getByText('Plan ready. No downloads have started.',{exact:true}).waitFor();assert.equal(await page.getByLabel(/Allowed license labels/).inputValue(),'cc0');
 await page.screenshot({path:'.audit/acquisition-plan.png',fullPage:true});assert.deepEqual(errors,[]);
 const report={ok:true,checks:['CSV delimiter and leading-zero preservation','saved Library collection and reload','choose SQLite sales table','verify imported rows','adopt working dataset','save quality contract','identify failing row','download report','reload contract persistence','unsupported acquisition request','CC0 constraint'],pageErrors:errors};await writeFile('.audit/product-acceptance.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}catch(e){await page.screenshot({path:'.audit/product-failure.png',fullPage:true});console.log(await page.locator('body').innerText());throw e}finally{await browser.close()}
