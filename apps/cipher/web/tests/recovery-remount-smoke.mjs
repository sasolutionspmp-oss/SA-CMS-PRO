import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
const web=path.dirname(path.dirname(fileURLToPath(import.meta.url))), repository=path.resolve(web,'../../..');
const artifacts=process.env.CIPHER_RECOVERY_ARTIFACTS??path.resolve(repository,'recovery-artifacts'); await mkdir(artifacts,{recursive:true});
const apps=process.env.CIPHER_RECOVERY_APPS?.split(',')??['commercial','ar','library'];
const widths=process.env.CIPHER_RECOVERY_WIDTHS?.split(',').map(Number)??[1440];
const report={cases:[],errors:[],source:'real native effects/source changes; original UI client and fixed API'};
let server,lines,base,prefix,browser;
async function control(command){const p=once(lines,'line',{signal:AbortSignal.timeout(10000)});server.stdin.write(command+'\n');return JSON.parse((await p)[0]);}
async function stop(){if(server&&server.exitCode===null){const p=once(server,'exit');server.kill('SIGTERM');await p;}lines?.close();server=undefined;}
async function start(kind){
 const source=await readFile(path.join(web,'tests',`${kind}-smoke.mjs`),'utf8');const match=source.match(/const fixtureControl = `([\s\S]*?)`;/);assert.ok(match);
 const fixture=match[1].replaceAll('\\\\','\\');const port={commercial:19386,ar:19387,library:19388}[kind];base=`http://127.0.0.1:${port}`;prefix=`/api/${kind}-practice/v1`;
 server=spawn(process.env.CIPHER_PYTHON??'python',['-u','-c',fixture,String(port)],{cwd:repository,stdio:['pipe','pipe','pipe']});lines=createInterface({input:server.stdout});let diagnostic='';server.stderr.on('data',chunk=>{diagnostic+=chunk;});
 for(let i=0;i<100;i++){if(server.exitCode!==null)throw new Error(diagnostic);try{if((await fetch(base)).ok)return;}catch{}await delay(100);}throw new Error(diagnostic);
}
async function json(context,route){const r=await context.request.get(base+prefix+route);assert.equal(r.status(),200,await r.text());return r.json();}
async function settled(page){await page.waitForFunction(()=>{const main=document.querySelector('main');return main&&main.getAttribute('aria-busy')!=='true'&&!main.querySelector('[role="progressbar"],[data-action][aria-busy="true"]');});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));}
async function text(page,label,value){await page.getByRole('textbox',{name:label,exact:true}).fill(value);}
async function choice(page,label){const select=page.getByRole('combobox',{name:label,exact:true});await select.waitFor();const value=await select.locator('option').evaluateAll(options=>options.find(option=>option.value&&!option.disabled)?.value);assert.ok(value,label);await select.selectOption(value);return value;}
async function spa(page,href){await page.locator(`main a[href="${href}"]`).first().click();await page.waitForURL(base+href);await settled(page);}
async function review(page,action,label){const before=await control('counts');const panel=page.locator(`[data-action="${action}"]`);await panel.getByRole('button',{name:label,exact:true}).click();await panel.getByRole('heading',{name:'Current checks',exact:true}).waitFor();await settled(page);assert.deepEqual(await control('counts'),before);}
async function drop(page,action,routePath,label){
 const panel=page.locator(`[data-action="${action}"]`);let original,dropped=false;
 const intercept=async route=>{if(dropped)return route.continue();dropped=true;const actual=await route.fetch();assert.equal(actual.status(),200,await actual.text());original={value:await actual.json(),key:route.request().headers()['repeatability-request-id'],version:route.request().headers()['if-match'],body:route.request().postData(),route:routePath};await route.abort('failed');};
 await page.route(`**${prefix}${routePath}`,intercept);await panel.getByRole('button',{name:label,exact:true}).click();await panel.getByRole('alert').waitFor();await settled(page);await page.unroute(`**${prefix}${routePath}`,intercept);assert.ok(original);assert.equal(original.value.effectApplied,true);assert.equal(await panel.getByRole('button',{name:'Start a new current review',exact:true}).count(),0);return original;
}
async function retrieve(page,action,original,result){
 const before=await control('counts');const pending=page.waitForResponse(r=>new URL(r.url()).pathname===prefix+original.route&&r.request().method()==='POST');await page.locator(`[data-action="${action}"]`).getByRole('button',{name:'Retry same action',exact:true}).click();const r=await pending;assert.equal(r.status(),200,await r.text());const value=await r.json();
 assert.equal(r.request().headers()['repeatability-request-id'],original.key);assert.equal(r.request().headers()['if-match'],original.version);assert.equal(r.request().postData(),original.body);assert.equal(value.receiptId,original.value.receiptId);assert.deepEqual(value.result,original.value.result);assert.equal(value.replayed,true);assert.equal(value.effectApplied,false);await settled(page);assert.deepEqual(await control('counts'),before);result.recovered=true;
}
async function remountCheck(page,action,original,result){
 const panel=page.locator(`[data-action="${action}"]`);result.original=original;result.afterSource=await control('counts');result.retryButtonsAfterRemount=await panel.getByRole('button',{name:'Retry same action',exact:true}).count();
 await page.screenshot({path:path.join(artifacts,`${result.kind}-remount-${result.width}.png`),fullPage:true});assert.equal(await page.evaluate(()=>window.__recoveryDocument),result.documentToken,'The recovery must cross SPA remount, not document reload');assert.equal(result.retryButtonsAfterRemount,1,`${result.kind}: source-invalid SPA remount hid the original unresolved UUID`);await retrieve(page,action,original,result);assert.deepEqual(await control('counts'),result.afterSource);
}
async function commercial(page,context,result){
 const project=(await json(context,'/projects')).items[0].id,form=`/projects/${project}/estimate-preparation`;await page.goto(base+form);await choice(page,'Owned drawing revision');await text(page,'Manual measurement basis','Synthetic trace; geometry unverified');await text(page,'Contingency percentage','0');
 for(const[label,value]of[['Description','Synthetic recovery piping'],['Quantity','13.125'],['Unit price','25.01'],['Source locator','A-101 / run4'],['Cost code','33-110']])await text(page,`${label} for manual line 1`,value);await page.getByRole('combobox',{name:'Unit for manual line 1',exact:true}).selectOption('LF');
 const action='estimate.create';await review(page,action,'Review manual estimate');const before=await control('counts');const original=await drop(page,action,`/projects/${project}/create-estimate`,'Create draft estimate');assert.equal((await control('counts')).estimates-before.estimates,1);
 await control('advance_drawing');const p=await json(context,`/projects/${project}/estimate-preparation`);assert.equal(p.drawingRevisions.some(s=>s.documentRevisionId===JSON.parse(original.body).documentRevisionId&&s.current),false);result.documentToken=`commercial-${result.width}`;await page.evaluate(t=>{window.__recoveryDocument=t;},result.documentToken);
 await spa(page,'/projects');await spa(page,form);await page.getByRole('combobox',{name:'Owned drawing revision',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Review manual estimate',exact:true}).count(),0);await remountCheck(page,action,original,result);
}
async function ar(page,context,result){
 const basis=(await json(context,'/owner-bases')).items[0].id,form=`/owner-bases/${basis}/preparation`;await page.goto(base+form);for(const label of['Claimed progress document','Reviewed progress document','Owner billing period'])await choice(page,label);
 for(const[id,claim,checked]of[['U1','12','10'],['L2','15000','12500']])for(const[label,value]of[['Claimed cumulative',claim],['Reviewed cumulative',checked],['Difference reason','Synthetic review difference'],['Claim source locator',`Claim / ${id}`],['Review source locator',`Review / ${id}`]])await text(page,`${label} for owner line ${id}`,value);
 const action='ownerBill.prepare';await review(page,action,'Review owner pay app');const before=await control('counts');const original=await drop(page,action,`/owner-bases/${basis}/prepare-bill`,'Prepare owner bill');assert.equal((await control('counts')).prime_bills-before.prime_bills,1);
 await control('advance_review_revision');const p=await json(context,`/owner-bases/${basis}/preparation`);assert.equal(p.reviewSources.some(s=>s.revisionId===JSON.parse(original.body).reviewRevisionId),false);result.documentToken=`ar-${result.width}`;await page.evaluate(t=>{window.__recoveryDocument=t;},result.documentToken);
 await spa(page,'/owner-bases');await spa(page,form);await page.getByRole('combobox',{name:'Reviewed progress document',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Review owner pay app',exact:true}).count(),0);await remountCheck(page,action,original,result);
}
async function library(page,context,result){
 const project=(await json(context,'/projects')).items[0].id;await page.goto(base+`/projects/${project}/library-preparation`);await page.getByRole('combobox',{name:'Library entry kind',exact:true}).selectOption('contract_clause');await text(page,'Library entry title','Synthetic recovery clause');await text(page,'Authored source text','Original exact synthetic clause.');await text(page,'Author source locator','Owned editor / initial');await review(page,'library.create','Review authored entry');
 const pending=page.waitForResponse(r=>new URL(r.url()).pathname===prefix+`/projects/${project}/create-entry`&&r.request().method()==='POST');await page.getByRole('button',{name:'Create authored entry',exact:true}).click();const created=await pending;assert.equal(created.status(),200,await created.text());const entry=(await created.json()).result.entryId;await settled(page);await spa(page,`/library-entries/${entry}`);const form=`/library-entries/${entry}/revise`;await spa(page,form);
 await text(page,'Authored source text','Exact synthetic attempted successor.');await text(page,'Revision source locator','Owned editor / successor');await text(page,'Revision change reason','Actual original successor review');const action='library.revise';await review(page,action,'Review authored revision');const before=await control('counts');const original=await drop(page,action,`/library-entries/${entry}/revise`,'Create next revision');assert.equal((await control('counts')).library_revisions-before.library_revisions,1);
 await control('advance_revision');const current=await json(context,`/library-entries/${entry}`);assert.notEqual(current.currentRevision.id,JSON.parse(original.body).previousRevisionId);result.documentToken=`library-${result.width}`;await page.evaluate(t=>{window.__recoveryDocument=t;},result.documentToken);
 await spa(page,`/library-entries/${entry}`);await spa(page,form);await page.getByRole('textbox',{name:'Revision change reason',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Review authored revision',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'Use current authored predecessor',exact:true}).count(),0);await remountCheck(page,action,original,result);
}
try{
 browser=await chromium.launch({executablePath:process.env.CIPHER_CHROME??'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 for(const kind of apps)for(const width of widths){const result={kind,width,recovered:false};report.cases.push(result);let context;
  try{await start(kind);context=await browser.newContext({viewport:{width,height:1000},hasTouch:width<1024,reducedMotion:'reduce'});const page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',e=>report.errors.push({kind,width,message:e.stack??String(e)}));await page.goto(base);await page.getByRole('button',{name:/^Start as /}).first().click();await page.getByRole('button',{name:'Change practice person',exact:true}).waitFor();await settled(page);assert.equal((await json(context,'/session')).person.personaId,kind==='library'?'author':'preparer');await({commercial,ar,library})[kind](page,context,result);}
  catch(error){result.error=error.stack??String(error);}finally{await context?.close();await stop();}
 }
}finally{await browser?.close();await stop();await writeFile(path.join(artifacts,'recovery-remount-result.json'),JSON.stringify(report,null,2)+'\n');}
console.log(JSON.stringify(report.cases.map(({kind,width,recovered,retryButtonsAfterRemount,error})=>({kind,width,recovered,retryButtonsAfterRemount,error})),null,2));assert.equal(report.cases.every(c=>c.recovered),true);assert.deepEqual(report.errors,[]);
