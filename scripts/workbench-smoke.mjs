import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
const browser=await chromium.launch({...(process.env.MEDIASENSEI_BROWSER_PATH?{executablePath:process.env.MEDIASENSEI_BROWSER_PATH}:{channel:'msedge'}),headless:true});
const page=await browser.newPage({viewport:{width:1512,height:982}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const api=process.env.NEXT_PUBLIC_CORE_API_URL||'http://127.0.0.1:8010/api/v1';
const web=process.env.MEDIASENSEI_SMOKE_WEB_URL||'http://127.0.0.1:3010/';
const projectName=`Customer research ${Date.now()}`;
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
 await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'.audit/workbench-desktop.png',fullPage:true});
 await page.reload();await page.getByText('API online',{exact:true}).waitFor();await page.locator('.sensei-nav').getByRole('button',{name:'Data Lab',exact:true}).click();await page.getByRole('tab',{name:'Versions',exact:true}).click();await page.locator('.lab-version-list').getByText('Clean v1',{exact:true}).waitFor();
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'.audit/workbench-mobile.png',fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+2);
 assert.equal(overflow,false,'Mobile page must not overflow horizontally');assert.deepEqual(errors,[]);
 const result={ok:true,project,checks:['CSV upload and worker','dataset adoption','profile','preview','operation execution','immutable version','Parquet download','recipe persistence','intent search','heatmap','reload persistence','mobile layout'],pageErrors:errors};
 await writeFile('.audit/workbench-browser.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){await page.screenshot({path:'.audit/browser-failure.png',fullPage:true});console.log(await page.locator('body').innerText());throw e;}finally{await browser.close();}
