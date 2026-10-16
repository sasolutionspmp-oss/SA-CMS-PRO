import { readFile, writeFile, mkdir, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { chromium, expect } from '/workspace/cipher-framework-draft/apps/cipher/product/node_modules/@playwright/test/index.mjs';

// Noninteractive text may legitimately share its official title owner's transparent
// click surface. Interactive controls never receive this narrow classification.
function captureGeometry(element) {
  const r = element.getBoundingClientRect();
  const heading = element.matches('h1,h2,h3,h4,h5,h6,[role="heading"]');
  const text = document.createRange(); text.selectNodeContents(element);
  const rects = heading ? [...text.getClientRects()].filter(rect => rect.width > 0 && rect.height > 0) : [r];
  const direct = hit => { let target = element; while (target) { if (hit && (hit === target || target.contains(hit))) return true; target = target.getRootNode()?.host; } return false; };
  const samples = rects.map(rect => {
    const x = rect.left + Math.min(12, rect.width / 2), y = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(x, y), owner = element.closest('[data-component-name="ObjectPageTitle"]');
    const style = hit && getComputedStyle(hit);
    const pseudoEmpty = pseudo => ['none', 'normal', '""'].includes(getComputedStyle(hit, pseudo).content);
    const ownerOverlay = Boolean(heading && hit?.tagName === 'SPAN' && hit.getAttribute('data-component-name') === 'ObjectPageTitleClickElement' && owner && hit.closest('[data-component-name="ObjectPageTitle"]') === owner && !hit.children.length && !hit.textContent?.trim() && style?.backgroundColor === 'rgba(0, 0, 0, 0)' && style.backgroundImage === 'none' && style.boxShadow === 'none' && ['Top','Right','Bottom','Left'].every(side => parseFloat(style[`border${side}Width`]) === 0) && pseudoEmpty('::before') && pseudoEmpty('::after'));
    let textVisible = element.checkVisibility({ opacityProperty: true, visibilityProperty: true });
    for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
      const clip = ancestor.getBoundingClientRect(), css = getComputedStyle(ancestor);
      if (['hidden','clip','auto','scroll'].includes(css.overflowX) && (rect.left < clip.left - 1 || rect.right > clip.right + 1)) textVisible = false;
      if (['hidden','clip','auto','scroll'].includes(css.overflowY) && (rect.top < clip.top - 1 || rect.bottom > clip.bottom + 1)) textVisible = false;
      if (parseFloat(css.opacity) === 0 || css.visibility === 'hidden') textVisible = false;
    }
    return { left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,hit_tag:hit?.tagName,hit_component:hit?.getAttribute('data-component-name'),owner_overlay:ownerOverlay,direct_hit:direct(hit),visible:textVisible && rect.left >= -1 && rect.right <= innerWidth + 1 && rect.top >= -1 && rect.bottom <= innerHeight + 1 && (direct(hit) || ownerOverlay) };
  });
  return { left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,viewport:innerWidth,visible_hit:samples.length > 0 && samples.every(sample => sample.visible),samples };
}

// Source-only helper. Requires a separately root-selected release after deploy.
// Real UI authentication only; no business command, raw trace, HAR, headers or login DOM.
const [releasePath, releaseSha, output] = process.argv.slice(2);
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const requireThat = (value, message) => { if (!value) throw new Error(message); };
const readBound = async ref => { requireThat(ref && /^[a-f0-9]{64}$/.test(ref.sha256), 'Missing bound artifact.'); const bytes = await readFile(ref.path); requireThat(digest(bytes) === ref.sha256, 'Bound artifact changed.'); return JSON.parse(bytes); };
requireThat(releasePath && /^[a-f0-9]{64}$/.test(releaseSha || '') && path.isAbsolute(output || ''), 'Provide selected release path/SHA and new absolute private output.');
const releaseBytes = await readFile(releasePath); requireThat(digest(releaseBytes) === releaseSha, 'Release hash mismatch.');
const release = JSON.parse(releaseBytes);
requireThat(release.schema === 'cipher.main.ui-readonly-release.v1' && release.released_stage === 'main_postdeploy_readonly_smoke' && release.base_url === 'http://127.0.0.1:18880' && release.business_writes_allowed === false && release.gate_passed === true && typeof release.backend_epoch === 'string' && release.backend_epoch, 'Read-only stage is not released.');
const source = await readBound(release.ui_source_inventory), build = await readBound(release.build_inventory);
const gate = await readBound(release.gate_report), checkpointSources = await readBound(release.checkpoint_sources), backendSources = await readBound(release.backend_source_inventory), fullSnapshot = await readBound(release.full_snapshot_sources);
const snapshotOnly = ['AGENTS.md','apps/cipher/AGENTS.md','apps/cipher/product/.gitignore'];
requireThat(Object.keys(fullSnapshot).length === 621 && Object.keys(checkpointSources).length === 618 && Object.keys(fullSnapshot).filter(key => !Object.hasOwn(checkpointSources,key)).sort().join('\n') === [...snapshotOnly].sort().join('\n') && Object.entries(checkpointSources).every(([key,sha]) => fullSnapshot[key] === sha), 'Full snapshot and runner map differ outside the exact three declared exclusions.');
requireThat(gate.schema === 'cipher.new-stack.validation.v1' && gate.status === 'passed' && gate.failure === null && Array.isArray(gate.source_changed_during_run) && gate.source_changed_during_run.length === 0 && Array.isArray(gate.stages) && gate.stages.every(row => row.status === 'passed'), 'The actual gate report did not pass unchanged.');
requireThat(gate.source_sha256 && Object.keys(gate.source_sha256).length === Object.keys(checkpointSources).length && Object.entries(checkpointSources).every(([key,sha]) => gate.source_sha256[key] === sha), 'Gate source map differs from the selected checkpoint.');
requireThat(Object.keys(backendSources).length > 0 && Object.entries(backendSources).every(([key,sha]) => checkpointSources[key] === sha), 'Backend snapshot is not bound to the passed checkpoint.');
requireThat(Object.entries(source).every(([key,sha]) => fullSnapshot[`apps/cipher/product/${key}`] === sha) && Object.keys(source).filter(key => !snapshotOnly.includes(`apps/cipher/product/${key}`)).length === 119 && Object.entries(source).every(([key,sha]) => snapshotOnly.includes(`apps/cipher/product/${key}`) || checkpointSources[`apps/cipher/product/${key}`] === sha), 'UI120 must match the full snapshot and its 119 runner entries.');
requireThat(Object.keys(source).length === 120, 'This helper requires the exact frozen UI120 variant.');
const parity = async (root, inventory) => { for (const [relative, sha] of Object.entries(inventory)) { requireThat(relative && !path.isAbsolute(relative) && !relative.split('/').includes('..') && /^[a-f0-9]{64}$/.test(sha), 'Invalid inventory.'); requireThat(digest(await readFile(path.join(root, relative))) === sha, 'Inventory parity failed.'); } };
await parity(release.checkpoint_source_root,fullSnapshot);await parity(release.ui_source_root, source); await parity(release.served_build_root, build);
try { await stat(output); throw new Error('Output exists; preserve prior attempts.'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
await mkdir(output, { mode: 0o700 });
const save = (name, value) => writeFile(path.join(output, name), JSON.stringify(value, (_key,item) => typeof item === 'string' ? item.replaceAll(actor.password, '[redacted-credential]') : item, 2) + '\n', { mode: 0o600 });
const fixture = JSON.parse(await readFile('/tmp/cipher-r0-runtime/fixture.secret.json', 'utf8'));
requireThat(fixture.project === 'PROJ-0001' && fixture.users?.primary?.user && fixture.users.primary.person && fixture.users.primary.password, 'Original fixture identity is unavailable.');
const base = release.base_url, actor = fixture.users.primary;
let stage = 'anonymous readiness', authenticated = false, browser, page;
const observerErrors = [], externalRequests = [], successfulReads = new Set();
const blockedPosts = [], pageErrors = [], consoleErrors = [], failedRequests = [], nonSuccess = [], assets = new Map(), pending = new Set(), checks = [];
const observedSessions = [];
let loginPosts = 0;
try {
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME || '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== base && !['data:', 'blob:'].includes(url.protocol)) { externalRequests.push({ origin:url.origin,path:url.pathname }); return route.abort('blockedbyclient'); }
    if (request.method() === 'POST') {
      if (url.pathname === '/api/method/login' && loginPosts++ === 0) return route.continue();
      blockedPosts.push({ method: request.method(), path: url.pathname }); return route.abort('blockedbyclient');
    }
    if (!['GET', 'HEAD'].includes(request.method())) { blockedPosts.push({ method: request.method(), path: url.pathname }); return route.abort('blockedbyclient'); }
    return route.continue();
  });
  page.on('pageerror', error => pageErrors.push({ name: error.name, message_sha256: digest(error.message) }));
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push({ text: message.text(), path: new URL(message.location().url || base).pathname }); });
  page.on('requestfailed', request => failedRequests.push({ url:request.url(),path:new URL(request.url()).pathname, method:request.method(),error:request.failure()?.errorText }));
  page.on('response', response => {
    const task = (async () => {
      const url = new URL(response.url());
      if (url.origin !== base) return;
      if (response.request().method() === 'GET' && response.status() === 200) successfulReads.add(response.url());
      if (url.pathname === '/api/method/cipher_aec.api.v1.session') {
        const json = await response.json(); const data = json.message?.data;
        observedSessions.push({ status: response.status(), authenticated: Boolean(data?.authenticated), error_code: json.message?.error?.code });
      }
      if (response.status() >= 400) nonSuccess.push({ path: url.pathname, status: response.status() });
      const resource = response.request().resourceType();
      if (!['document','script','stylesheet','font','image'].includes(resource) || url.pathname.startsWith('/api/')) return;
      const relative = resource === 'document' ? 'index.html' : decodeURIComponent(url.pathname).replace(/^\//, '');
      requireThat(Object.hasOwn(build, relative), `A served asset is outside the selected build: ${relative}`);
      requireThat(response.status() === 200, `Static build asset did not return 200: ${relative}`);
      if (relative === 'cipher-mark.svg') requireThat(/^image\/svg\+xml(?:;|$)/i.test(response.headers()['content-type'] || ''), 'Logo MIME is not SVG.');
      const bytes = await response.body(); requireThat(digest(bytes) === build[relative], `Served build bytes differ from selected inventory: ${relative}`);
      assets.set(relative, { path: relative, sha256: digest(bytes), byte_length: bytes.length, content_type: response.headers()['content-type'] });
    })();
    pending.add(task); void task.catch(error => observerErrors.push({name:error.name,message:error.message,stack:error.stack})).finally(() => pending.delete(task));
  });
  await page.goto(base + '/projects');
  await expect(page.getByRole('heading', { name: 'Sign in to your workspace', exact: true })).toBeVisible();
  const username = page.getByRole('textbox', { name: 'Email or username', exact: true });
  const password = page.getByRole('textbox', { name: 'Password', exact: true });
  stage = 'normal sign-in and App bootstrap';
  await username.focus(); await expect(username).toBeFocused(); await username.fill(actor.user); await page.keyboard.press('Tab'); await expect(password).toBeFocused(); await password.fill(actor.password);
  const signIn = page.getByRole('button', { name: 'Sign in', exact: true });
  await expect(signIn).toBeEnabled(); await expect(password).toBeFocused();
  await page.keyboard.press('Tab'); await expect(signIn).toBeFocused();
  const appSession = page.waitForResponse(response => response.url().startsWith(base + '/api/method/cipher_aec.api.v1.session') && response.status() === 200);
  await page.keyboard.press('Enter');
  const session = (await (await appSession).json()).message?.data;
  requireThat(session?.authenticated && session.user === actor.user && session.person?.id === actor.person, 'App bootstrap identity differs from original User/Person.');
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Sign in to your workspace', exact: true })).toHaveCount(0); authenticated = true;
  checks.push('Normal keyboard sign-in; App session response consumed without an extra concurrent session GET.');
  let projectName = '';
  const settle = async (heading, control, width) => {
    await expect(heading).toBeVisible(); await expect(page.locator('.loading-state')).toHaveCount(0);
    if (width < 600) await expect.poll(async () => page.locator('ui5-side-navigation').evaluate(element => Math.round(element.getBoundingClientRect().right))).toBeLessThanOrEqual(1);
    const geometry = async locator => locator.evaluate(captureGeometry);
    await expect.poll(async () => { const g = await geometry(heading); return g.visible_hit && g.left >= -1 && g.right <= g.viewport + 1; }).toBe(true);
    await control.focus(); await expect(control).toBeFocused();
    const after = await geometry(heading); requireThat(after.visible_hit && after.left >= -1 && after.right <= after.viewport + 1, 'Focused control occludes title.');
    const controlGeometry=await geometry(control);requireThat(controlGeometry.visible_hit && controlGeometry.left>=-1 && controlGeometry.right<=controlGeometry.viewport+1,'Focused public control is clipped or occluded.');const workspace=await page.locator('.workspace-main').evaluate(element=>({client_width:element.clientWidth,scroll_width:element.scrollWidth,scroll_left:element.scrollLeft}));requireThat(workspace.scroll_width<=workspace.client_width+2 && Math.abs(workspace.scroll_left)<=1,'Nested workspace overflows or has scrolled sideways.');return {heading:after,control:controlGeometry,workspace};
  };
  const tableAligned = async table => { await expect(table).toBeVisible(); const headers = table.getByRole('columnheader'); const row = table.getByRole('row').nth(1).getByRole('gridcell'); if (await row.count()) { await expect(row).toHaveCount(await headers.count()); await expect.poll(async () => Math.max(...await Promise.all((await headers.all()).map(async (header,index) => {const a=await header.boundingBox(),b=await row.nth(index).boundingBox();return a&&b?Math.max(Math.abs(a.x-b.x),Math.abs(a.width-b.width)):999;})))).toBeLessThanOrEqual(2); } };
  for (const width of [1440,900,390]) {
    stage = `project register ${width}`; await page.setViewportSize({ width, height: 1000 }); await page.goto(base + '/projects');
    const heading = page.getByRole('heading', { name:'Projects',exact:true }); const nav = page.getByRole('button', { name:'Toggle navigation',exact:true });
    const registerGeometry = await settle(heading,nav,width); await expect(page.getByRole('grid', {name:'Projects',exact:true})).toBeVisible(); await page.screenshot({path:path.join(output,`actual-project-register-${width}.png`)});
    stage = `exact original project and Tasks ${width}`;
    const projectResponse = page.waitForResponse(response => { const url=new URL(response.url());return url.pathname === '/api/method/cipher_aec.api.v1.project' && url.searchParams.get('project') === fixture.project && response.status() === 200; });
    await page.goto(base + '/projects/PROJ-0001'); const project = (await (await projectResponse).json()).message?.data; requireThat(project?.id === fixture.project && project.company === fixture.company && typeof project.name === 'string', 'Original project identity differs.'); projectName = project.name;
    const projectHeading = page.getByRole('heading',{name:projectName,exact:true}).first(); const detailGeometry = await settle(projectHeading,nav,width); const tasks=page.locator('ui5-table[accessible-name="Project tasks"]');
    await expect(page.getByRole('heading',{name:'Project work',exact:true})).toBeVisible(); if(await tasks.count())await tableAligned(tasks); else await expect(page.getByRole('heading',{name:'No tasks yet',exact:true})).toBeVisible();
    await expect(page.locator('.loading-state')).toHaveCount(0); await page.screenshot({path:path.join(output,`actual-original-project-tasks-${width}.png`)});
    if(width<600){await nav.click();await page.getByRole('treeitem',{name:'Ricky',exact:true}).click();}else await page.getByRole('button',{name:'Toggle Ricky assistant',exact:true}).click();
    stage = `honest unavailable Ricky ${width}`; await expect(page.getByRole('heading',{name:'Ricky is not connected',exact:true})).toBeVisible(); await expect(page.getByRole('button',{name:'Send question to Ricky',exact:true})).toBeDisabled(); await expect(page.locator('.loading-state')).toHaveCount(0); await settle(page.getByRole('heading',{name:'Ricky is not connected',exact:true}),page.getByRole('button',{name:'Close Ricky',exact:true}),width);await page.screenshot({path:path.join(output,`actual-unavailable-ricky-${width}.png`)}); await page.getByRole('button',{name:'Close Ricky',exact:true}).click();
    checks.push({width,register_geometry:registerGeometry,detail_geometry:detailGeometry,task_table_checked:await tasks.count()>0,capture_scope:'Visible viewport; no document or full-page-PDF claim.'});
  }
  stage = 'final source, served asset and browser closure'; await Promise.all([...pending]);
  const notice = await page.request.get(base + '/THIRD_PARTY_NOTICES.txt'); const noticeBytes = await notice.body(); requireThat(notice.status() === 200 && /^text\/plain(?:;|$)/i.test(notice.headers()['content-type'] || '') && digest(noticeBytes) === build['THIRD_PARTY_NOTICES.txt'], 'Served dependency notice differs from the selected build.'); checks.push('Original public logo and dependency notice served with selected bytes and correct MIME.');
  await parity(release.checkpoint_source_root,fullSnapshot);await parity(release.ui_source_root,source); await parity(release.served_build_root,build);requireThat(digest(await readFile(releasePath))===releaseSha,'Release changed during capture.');await readBound(release.gate_report);await readBound(release.checkpoint_sources);await readBound(release.backend_source_inventory);await readBound(release.full_snapshot_sources);
  const classifiedAbortedReads=failedRequests.filter(row=>row.method==='GET' && row.error==='net::ERR_ABORTED' && row.path.startsWith('/api/method/') && successfulReads.has(row.url));requireThat(blockedPosts.length===0 && loginPosts===1 && pageErrors.length===0 && externalRequests.length===0 && observerErrors.length===0 && failedRequests.length===classifiedAbortedReads.length,'Unexpected browser fault, asset mismatch or write attempt.');
  const initial401=observedSessions[0]?.status===401 && ['authentication_required','unauthenticated'].includes(observedSessions[0]?.error_code);
  requireThat(observedSessions.filter(row=>row.status!==200).length===(initial401?1:0),'Unexpected session response.');
  const unexpectedResponses=nonSuccess.filter((row,index)=>!(initial401 && row.path==='/api/method/cipher_aec.api.v1.session' && row.status===401 && nonSuccess.findIndex(item=>item.path===row.path&&item.status===401)===index));requireThat(unexpectedResponses.length===0,'Unexpected non-success response.');
  const expectedConsole=consoleErrors.filter(row=>initial401 && row.path==='/api/method/cipher_aec.api.v1.session' && row.text==='Failed to load resource: the server responded with a status of 401 (UNAUTHORIZED)');requireThat(consoleErrors.length===expectedConsole.length && expectedConsole.length<=1,'Unexpected console error.');
  await save('verification.json',{schema:'cipher.main.ui-readonly-capture.v1',status:'passed',captured_at:new Date().toISOString(),mode:'actual-synthetic-frappe-read-only',release_sha256:releaseSha,backend_epoch:release.backend_epoch,ui_source_inventory:release.ui_source_inventory,build_inventory:release.build_inventory,gate_report:release.gate_report,project_id:fixture.project,company:fixture.company,person_id:session.person.id,checks,served_assets:[...assets.values()],expected_initial_session_401:initial401,classified_aborted_reads_with_exact_success:classifiedAbortedReads.map(({path,method,error})=>({path,method,error})),business_commands:0,authentication_posts:1,mocked_responses:false,limits:['No domain writes, source-document selection, award or Company Ricky qualification.','Screenshots are viewport captures after settled public-navigation/title/control checks.','No trace/HAR/raw authentication/session payload or login DOM retained.']});
  console.log('Read-only main smoke completed; private evidence saved.');
} catch(error) {
  await save('incomplete.json',{schema:'cipher.main.ui-readonly-capture.v1',status:'failed',stage,error_name:error.name,error_message:error.message,error_stack:error.stack,business_post_attempts:blockedPosts,page_errors:pageErrors,observer_errors:observerErrors,external_requests:externalRequests,failed_requests:failedRequests,non_success_responses:nonSuccess,console_errors:consoleErrors,observed_sessions:observedSessions,served_assets:[...assets.values()],expected_actor_context_retained:true,release_sha256:releaseSha});
  if(authenticated && page && await page.getByRole('heading',{name:'Sign in to your workspace',exact:true}).count()===0)await page.screenshot({path:path.join(output,'incomplete-authenticated-viewport.png')}).catch(()=>{});
  console.error(`Read-only capture failed at ${stage}; private evidence preserved.`);process.exitCode=1;
} finally {if(browser)await browser.close();}
