import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
const browser=await chromium.launch({...(process.env.MEDIASENSEI_BROWSER_PATH?{executablePath:process.env.MEDIASENSEI_BROWSER_PATH}:process.platform==='win32'?{channel:'msedge'}:{}),headless:true});
const page=await browser.newPage({viewport:{width:1512,height:982}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const api=process.env.NEXT_PUBLIC_CORE_API_URL||'http://127.0.0.1:8010/api/v1';
const web=process.env.MEDIASENSEI_SMOKE_WEB_URL||'http://127.0.0.1:3010/';
const projectName=`Batch one acceptance ${Date.now()}`;
async function waitJobs(project){for(let i=0;i<90;i++){const r=await(await fetch(`${api}/jobs?project_id=${project}`)).json();if(r.items.length&&r.items.every(j=>['completed','failed','completed_with_errors','cancelled'].includes(j.state))){assert(r.items.every(j=>j.state==='completed'),JSON.stringify(r.items));return;}await new Promise(r=>setTimeout(r,500));}throw Error('Jobs did not complete');}
try{
 const initialProjects=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/projects'&&r.request().method()==='GET');
 await page.goto(web);await page.getByText('API online',{exact:true}).waitFor({timeout:60000});
 const initialProjectData=await (await initialProjects).json();
 if(initialProjectData.items.length===0){await page.locator('main input').first().fill(projectName);await page.getByRole('button',{name:'Create project',exact:true}).click();}
 else{await page.getByPlaceholder('New project name').waitFor();await page.getByPlaceholder('New project name').fill(projectName);await page.getByRole('button',{name:'New project',exact:true}).click();}
 await page.getByText('Created project',{exact:false}).waitFor();
 const projects=await(await fetch(`${api}/projects`)).json();const project=projects.items.find(p=>p.name===projectName).id;
 const csv='age,income,score,segment\n'+Array.from({length:150},(_,i)=>`${20+i%43},${i%7===0?'':25000+(i%21)*4200},${(i%10)/10},${i%5?'returning':'new'}`).join('\n');
 await page.locator('input[type=file]').first().setInputFiles({name:'customers.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
 await page.getByText('Imported 1 file.',{exact:false}).waitFor({timeout:30000});await waitJobs(project);
 await page.locator('.sensei-nav').getByRole('button',{name:'Data Lab',exact:true}).click();
 await page.getByRole('button',{name:'Refresh imports',exact:true}).click();
 await page.locator('select[aria-label="Create from imported table"] option').nth(1).waitFor({state:'attached'});
 const source=await page.locator('select[aria-label="Create from imported table"] option').nth(1).getAttribute('value');
 await page.getByLabel('Create from imported table').selectOption(source);
 await page.locator('.lab-stats').getByText('150',{exact:true}).waitFor();
 await page.getByLabel('Operation',{exact:true}).selectOption('fill_missing');
 await page.locator('.lab-column-options').getByLabel('income',{exact:true}).check();
 await page.getByRole('button',{name:'Preview',exact:true}).click();
 await page.getByRole('heading',{name:'Preview · first 100 rows'}).waitFor();
 assert(await page.locator('.lab-before-after').getByText('missing',{exact:true}).count()>0);
 await page.getByRole('button',{name:'Run',exact:true}).click();await waitJobs(project);
 await page.getByText('Working copy · revision 1',{exact:true}).waitFor({timeout:15000});
 await page.getByRole('tab',{name:'Versions',exact:true}).click();await page.getByLabel('Version name').fill('Clean v1');await page.getByRole('button',{name:'Create version',exact:true}).click();await page.getByText('Dataset version created.',{exact:true}).waitFor();
 assert(await page.locator('.lab-version-list').getByText('Clean v1',{exact:true}).count());
 const dl=page.waitForEvent('download');await page.locator('.lab-version-list').getByRole('link',{name:'Parquet',exact:true}).click();assert.equal((await dl).suggestedFilename(),'dataset.parquet');
 await page.getByLabel('Operation',{exact:true}).selectOption('scale');await page.locator('.lab-column-options').getByLabel('income',{exact:true}).check();await page.getByRole('button',{name:'Add to workflow',exact:true}).click();
 await page.getByRole('tab',{name:'Workflows',exact:true}).click();await page.getByLabel('Workflow / recipe name').fill('Income preparation');await page.getByRole('button',{name:'Save recipe',exact:true}).click();await page.getByText('Recipe saved.',{exact:false}).waitFor();
 await page.keyboard.press('Control+k');await page.getByLabel('Search operations and navigation').fill('make heat map');await page.locator('dialog').getByRole('button',{name:'Correlation heatmap',exact:false}).click();
 await page.getByLabel('Operation',{exact:true}).selectOption('correlation');await page.getByRole('button',{name:'Preview',exact:true}).click();await page.locator('.lab-heatmap').first().waitFor();
 await page.getByRole('tab',{name:'Visualize',exact:true}).click();await page.getByRole('button',{name:'Close preview',exact:true}).click();
 // Verify all themes render and persist, with the original forest as the starting default.
 assert.equal(await page.getByLabel('Color scheme').inputValue(),'forest');
 const backgrounds=[];
 for(const theme of ['forest','spectrum','charcoal','beige']){
   await page.getByLabel('Color scheme').selectOption(theme);
   backgrounds.push(await page.evaluate(()=>getComputedStyle(document.body).backgroundColor));
   await page.evaluate(()=>window.scrollTo(0,0));
   await page.screenshot({path:`.audit/batch-theme-${theme}.png`,fullPage:true});
 }
 assert.equal(new Set(backgrounds).size,4);
 await page.getByLabel('Color scheme').selectOption('forest');
 // Table selection, visible columns, conditions and query history use real server results.
 await page.getByRole('tab',{name:'Explore',exact:true}).click();
 await page.getByText('Filters, visible columns and query history',{exact:true}).click();
 await page.getByLabel('Filter column',{exact:true}).selectOption('age');
 await page.getByLabel('Condition',{exact:true}).selectOption('ge');
 await page.getByLabel('Value',{exact:true}).fill('40');
 await page.getByRole('button',{name:'Add condition',exact:true}).click();
 await page.waitForResponse(r=>r.url().endsWith('/query')&&r.status()===200);
 await page.getByLabel('Select page',{exact:true}).check();
 assert.match(await page.locator('.lab-data-summary').innerText(),/selected rows/);
 await page.getByRole('button',{name:'Remove condition 1',exact:true}).click();
 // Parameterized recipe import -> dry run -> durable workflow -> execution.
 await page.getByRole('tab',{name:'Workflows',exact:true}).click();
 const recipe={name:'Parameterized age feature',steps:[{operation:'derive',parameters:{name:'{{feature}}',expression:'age * 2'}}]};
 await page.getByLabel('Import recipe',{exact:true}).setInputFiles({name:'recipe.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(recipe))});
 await page.getByText('Recipe imported and validated.',{exact:true}).waitFor();
 await page.getByLabel('Recipe parameter: feature',{exact:true}).fill('double_age');
 await page.getByRole('button',{name:'Dry run · 100 rows',exact:true}).click();
 await page.getByText('Create arithmetic feature: 100 rows',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Save workflow',exact:true}).click();await page.getByText('Workflow saved.',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Show equivalent Python',exact:true}).click();await page.locator('.lab-code').getByText('double_age',{exact:false}).waitFor();
 const notebook=page.waitForEvent('download');await page.getByRole('button',{name:'Export notebook',exact:true}).click();assert.equal((await notebook).suggestedFilename(),'workflow.ipynb');
 await page.getByRole('button',{name:'Run workflow',exact:true}).click();await waitJobs(project);await page.getByText('Working copy · revision 2',{exact:true}).waitFor({timeout:15000});
 // Build and save a chart, export actual SVG and PNG, and a self-contained visual report.
 await page.getByRole('tab',{name:'Visualize',exact:true}).click();
 await page.getByLabel('Operation',{exact:true}).selectOption('chart');
 await page.getByLabel('Chart',{exact:true}).selectOption('scatter');
 await page.getByLabel('X/category column',{exact:true}).selectOption('age');
 await page.getByLabel('Y/value column',{exact:true}).selectOption('income');
 await page.getByRole('button',{name:'Preview',exact:true}).click();await page.locator('.lab-preview').waitFor();
 await page.getByRole('button',{name:'Close preview',exact:true}).click();
 const svg=page.waitForEvent('download');await page.getByRole('button',{name:'Export SVG',exact:true}).click();assert.equal((await svg).suggestedFilename(),'chart.svg');
 const png=page.waitForEvent('download');await page.getByRole('button',{name:'Export PNG',exact:true}).click();assert.equal((await png).suggestedFilename(),'chart.png');
 await page.getByLabel('Chart name',{exact:true}).fill('Income relationship');await page.getByRole('button',{name:'Save chart / add to report',exact:true}).click();await page.getByText('Chart definition and full-data result saved with its input hash.',{exact:true}).waitFor();
 await page.getByText('Report · 1 saved visualizations',{exact:true}).click();const report=page.waitForEvent('download');await page.getByRole('button',{name:'Export report',exact:true}).click();assert.equal((await report).suggestedFilename(),'visualization-report.html');
 // Inspect version feature differences.
 await page.getByRole('tab',{name:'Versions',exact:true}).click();const left=page.getByLabel('From',{exact:true});const saved=await left.locator('option').nth(1).getAttribute('value');await left.selectOption(saved);await page.getByRole('button',{name:'Compare versions',exact:true}).click();await page.getByText('Columns added: double_age',{exact:false}).waitFor();
 // Function Explorer reads the installed Pandas API.
 await page.locator('.sensei-nav').getByRole('button',{name:'Documentation',exact:true}).click();await page.getByRole('button',{name:'Function Explorer',exact:true}).click();await page.getByLabel('Find a concept',{exact:true}).fill('groupby');await page.getByRole('heading',{name:'pandas.DataFrame.groupby',exact:true}).waitFor();
 await page.screenshot({path:'.audit/batch-function-explorer.png',fullPage:true});

 await page.reload();await page.getByText('API online',{exact:true}).waitFor();await page.locator('.sensei-nav').getByRole('button',{name:'Data Lab',exact:true}).click();await page.getByRole('tab',{name:'Versions',exact:true}).click();await page.locator('.lab-version-list').getByText('Clean v1',{exact:true}).waitFor();
 assert.equal(await page.getByLabel('Color scheme').inputValue(),'forest');
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'.audit/workbench-mobile.png',fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+2);
 assert.equal(overflow,false,'Mobile page must not overflow horizontally');assert.deepEqual(errors,[]);
 const result={ok:true,project,checks:['CSV upload and worker','dataset adoption','profile','preview','operation execution','immutable version','Parquet download','recipe persistence','intent search','heatmap','reload persistence','mobile layout','four theme palettes and persistence','compound query and selection','recipe import and typed binding','saved workflow','notebook export','chart SVG/PNG/report export','version feature diff','installed Function Explorer'],pageErrors:errors};
 await writeFile('.audit/batch-browser.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){await page.screenshot({path:'.audit/browser-failure.png',fullPage:true});console.log(await page.locator('body').innerText());throw e;}finally{await browser.close();}
