// Actual project/add/export React surfaces in a private, hidden Electron window.
// API responses are controlled; no game assets, native tools or user storage.
// NUCLEUS_TEST_DEPENDENCIES can point at another checkout's app/ in a worktree.
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')

const root = path.resolve(__dirname, '../..')
const deps = process.env.NUCLEUS_TEST_DEPENDENCIES || path.join(root, 'app')
let electron, build, executablePath
try {
  const appRequire = createRequire(path.join(deps, 'package.json'))
  electron = appRequire('playwright-core')._electron
  executablePath = appRequire('electron')
  build = createRequire(path.join(deps, 'frontend/package.json'))('esbuild').build
} catch {}

test('project roster warnings follow batches, removals, reopen and current responses without blocking export', {
  skip: !electron || !build ? 'Install app and frontend dependencies for the renderer test' : false,
  timeout: 120000,
}, async () => {
  const scratchRoot = path.join(root, 'app/scratch')
  fs.mkdirSync(scratchRoot, { recursive: true })
  const scratch = fs.mkdtempSync(path.join(scratchRoot, 'roster-warning-renderer-'))
  fs.writeFileSync(path.join(scratch, 'main.cjs'), `
    const {app,BrowserWindow}=require('electron');
    app.setPath('userData',${JSON.stringify(path.join(scratch, 'profile'))});
    app.whenReady().then(()=>{const win=new BrowserWindow({show:false,width:1200,height:900});
      win.loadFile(${JSON.stringify(path.join(scratch, 'index.html'))});});
    app.on('window-all-closed',()=>app.quit());`)
  fs.writeFileSync(path.join(scratch, 'index.html'), '<link rel="stylesheet" href="bundle.css"><div id="root" style="height:100vh"></div><script src="bundle.js"></script>')
  await build({
    stdin: { resolveDir: path.join(root, 'app/frontend'), sourcefile: 'roster-fixture.jsx', loader: 'jsx', contents: `
      import React,{useState}from'react';import{createRoot}from'react-dom/client';
      import MexPanel from'./src/projects/MexPanel.jsx';
      import{api}from'./src/shared/transport/api.js';
      import{setAppDialogHandler}from'./src/shared/ui/appDialogs.js';
      import'./src/index.css';import'./src/shared/ui/buttons.css';import'./src/shared/ui/modals.css';
      window.alerts=[];window.alert=message=>alerts.push(message);
      const vanilla=['Mario','Fox','Captain Falcon','Donkey Kong','Kirby','Bowser','Link','Sheik','Ness','Peach','Popo','Nana','Pikachu','Samus','Yoshi','Jigglypuff','Mewtwo','Luigi','Marth','Zelda','Young Link','Dr. Mario','Falco','Pichu','Mr. Game & Watch','Ganondorf','Roy'];
      const special=['Master Hand','Wireframe Male','Wireframe Female','Giga Bowser','Crazy Hand','Sandbag'];
      const makeRoster=count=>Array.from({length:count},(_,internalId)=>({internalId,externalId:internalId,
        name:internalId<27?vanilla[internalId]:internalId>=count-6?special[internalId-count+6]:internalId===34?'NONE':'Custom '+internalId,
        isMexFighter:internalId>=27&&internalId<count-6,costumeCount:0}));
      window.fixture={count:62,project:'Fixture Project',calls:[],pending:[],hold:false,fail:false,partial:false,confirm:true};
      setAppDialogHandler(()=>Promise.resolve(fixture.confirm));
      api.get=async p=>{
        fixture.calls.push({method:'GET',path:p});
        if(p==='/status')return {connected:true,projectLoaded:true,project:{name:fixture.project,path:'C:/fixture/'+fixture.project+'/project.mexproj'}};
        if(p==='/fighters'){
          if(fixture.hold)return new Promise((resolve,reject)=>fixture.pending.push({resolve,reject}));
          if(fixture.fail)throw Error('Controlled roster failure');
          return {fighters:makeRoster(fixture.count)};
        }
        if(p==='/project/build')return {longName:fixture.project};
        if(p==='/project/disc-usage')return null;
        if(p==='/custom-characters/list')return {characters:[1,2,3].map(n=>({slug:'fixture-'+n,name:'Fixture '+n,costume_count:1}))};
        if(p==='/menus/css/layout')return {icons:[],template:{}};
        if(p==='/recommended-compression')return {ratio:1};
        if(p.includes('/costumes'))return {costumes:[]};
        return {};
      };
      api.post=async(p,body)=>{
        fixture.calls.push({method:'POST',path:p,body});
        if(p==='/custom-characters/install-batch'){
          const added=fixture.partial?1:body.slugs.length;
          const reserved=fixture.count<=40&&fixture.count+added>40?1:0;
          fixture.count+=added+reserved;
          return {success:true,totalAdded:added,failed:fixture.partial?[{slug:'fixture-2',error:'Controlled partial failure'}]:[]};
        }
        if(p==='/custom-characters/remove-from-project'){fixture.count--;return {success:true}};
        if(p==='/export/start')throw Error('Fixture stopped before any build');
        return {success:true};
      };
      fixture.finish=(index,count)=>fixture.pending[index].resolve({fighters:makeRoster(count)});
      fixture.change=()=>window.dispatchEvent(new Event('nucleus:project-changed'));
      function App(){const[key,setKey]=useState(0);fixture.reopen=()=>setKey(k=>k+1);return <MexPanel key={key} active vaultMetadata={{}}/>}
      createRoot(document.getElementById('root')).render(<App/>);` },
    bundle: true, jsx: 'automatic', outfile: path.join(scratch, 'bundle.js'), logLevel: 'silent',
    external: ['/fonts/*'], loader: { '.png': 'dataurl', '.svg': 'dataurl' },
    nodePaths: [path.join(deps, 'frontend/node_modules')],
    plugins: [{ name: 'private-transport', setup(b) {
      b.onResolve({ filter: /shared\/transport\/socket(?:\.js)?$/ }, () => ({ path: 'socket', namespace: 'fixture' }))
      b.onResolve({ filter: /shared\/audio\/sounds(?:\.js)?$/ }, () => ({ path: 'sounds', namespace: 'fixture' }))
      b.onLoad({ filter: /.*/, namespace: 'fixture' }, ({ path: p }) => ({ contents: p === 'socket'
        ? 'export const channel=()=>({on(){},off(){},disconnect(){}});'
        : 'export const playSound=()=>{};export const playHoverSound=()=>{};export const playCharacterSound=()=>{};' }))
    } }],
  })
  const app = await electron.launch({ executablePath, args: [path.join(scratch, 'main.cjs')] })
  const results = [], errors = []
  try {
    const page = await app.firstWindow()
    page.setDefaultTimeout(10000)
    page.on('pageerror', err => errors.push(err.message))
    await page.getByRole('button', { name: '+ Add Character', exact: true }).waitFor()
    const topWarning = page.locator('.mex-panel > .large-roster-warning')
    const modal = page.locator('.add-character-modal')
    const openAdd = () => page.getByRole('button', { name: '+ Add Character', exact: true }).click()
    const refreshTo = async count => {
      await page.evaluate(count => { fixture.count = count; fixture.change() }, count)
      await page.waitForFunction(count => document.querySelectorAll('.fighter-item').length === count - 8 - (count > 40 ? 1 : 0), count)
    }
    assert.equal(await topWarning.count(), 0)
    await openAdd()
    await modal.getByRole('button', { name: 'Fixture 1 1 costumes', exact: true }).click()
    assert.equal(await modal.locator('.large-roster-warning').count(), 0)
    await modal.getByRole('button', { name: 'Fixture 2 1 costumes', exact: true }).click()
    assert.match(await modal.locator('.large-roster-warning').innerText(), /from 62 to 64 fighter entries/)
    assert.equal(await modal.getByRole('button', { name: 'Add Selected (2)', exact: true }).isEnabled(), true)
    await modal.locator('summary').click()
    await page.screenshot({ path: path.join(scratch, 'batch-64.png') })
    await modal.getByRole('button', { name: 'Clear', exact: true }).click()
    assert.equal(await modal.locator('.large-roster-warning').count(), 0)
    await modal.getByRole('button', { name: 'Fixture 1 1 costumes', exact: true }).click()
    await modal.getByRole('button', { name: 'Fixture 2 1 costumes', exact: true }).click()
    await modal.getByRole('button', { name: 'Add Selected (2)', exact: true }).click()
    await modal.waitFor({ state: 'detached' })
    await topWarning.waitFor()
    assert.match(await topWarning.innerText(), /This project has 64 fighter entries/)
    assert.deepEqual(errors, [], 'batch completion must not throw')
    results.push('62 + two selected warns before install; clear removes warning; completed 64-entry batch is reflected')

    await page.locator('.fighter-remove-btn').last().click()
    await topWarning.waitFor({ state: 'detached' })
    assert.equal(await page.evaluate(() => fixture.count), 63)
    await openAdd()
    await modal.getByRole('button', { name: 'Fixture 1 1 costumes', exact: true }).click()
    assert.match(await modal.locator('.large-roster-warning').innerText(), /from 63 to 64/)
    await modal.locator('.modal-close').click()
    await refreshTo(62)
    await page.evaluate(() => { fixture.partial = true })
    await openAdd()
    await modal.getByRole('button', { name: 'Fixture 1 1 costumes', exact: true }).click()
    await modal.getByRole('button', { name: 'Fixture 2 1 costumes', exact: true }).click()
    await modal.getByRole('button', { name: 'Add Selected (2)', exact: true }).click()
    await modal.waitFor({ state: 'detached' })
    assert.equal(await topWarning.count(), 0)
    assert.equal(await page.evaluate(() => fixture.count), 63)
    results.push('removal clears warning; reopening add recomputes; partial install uses actual returned roster')

    await page.evaluate(() => { fixture.count = 64; fixture.reopen() })
    await topWarning.waitFor()
    await page.screenshot({ path: path.join(scratch, 'existing-project-64.png') })
    await page.getByRole('button', { name: 'Export', exact: true }).click()
    const exportModal = page.locator('.iso-builder-modal')
    assert.match(await exportModal.locator('.large-roster-warning').innerText(), /64 fighter entries/)
    await page.screenshot({ path: path.join(scratch, 'export-64.png') })
    const exportButton = exportModal.locator('.accent-cyan .btn-option')
    assert.equal(await exportButton.isEnabled(), true)
    await exportButton.click()
    await exportModal.getByText('Export Failed', { exact: true }).waitFor()
    assert.equal(await page.evaluate(() => fixture.calls.filter(c => c.path === '/export/start').length), 1)
    await exportModal.getByRole('button', { name: 'Close', exact: true }).click()
    results.push('existing oversized project warns on reopen and export; warning allows the export request')

    await page.evaluate(() => { fixture.hold = true; fixture.change() })
    await page.waitForFunction(() => fixture.pending.length === 1)
    await openAdd()
    assert.match(await modal.locator('.large-roster-warning').innerText(), /Checking roster size/)
    await page.evaluate(() => { fixture.project = 'Different Project'; fixture.change() })
    await page.waitForFunction(() => fixture.pending.length === 2)
    await page.evaluate(() => fixture.finish(1, 63))
    await modal.locator('.large-roster-warning').waitFor({ state: 'detached' })
    await page.evaluate(() => fixture.finish(0, 65))
    await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 30)))
    assert.equal(await modal.locator('.large-roster-warning').count(), 0)
    await page.evaluate(() => { fixture.hold = false; fixture.fail = true; fixture.change() })
    await modal.getByText('Roster size unavailable', { exact: true }).waitFor()
    await page.evaluate(() => { fixture.fail = false; fixture.count = 64 })
    await modal.getByRole('button', { name: 'Retry roster check', exact: true }).click()
    await modal.getByText('Large roster: Slippi desync risk', { exact: true }).waitFor()
    results.push('pending and failed checks are explicit; older response cannot restore stale count; retry recovers')

    await modal.locator('.modal-close').click()
    await app.browserWindow(page).then(w => w.evaluate(w => w.setSize(800, 700)))
    await openAdd()
    await modal.locator('summary').click()
    const bounds = await modal.boundingBox()
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 801, 'narrow modal stays in viewport')
    await page.screenshot({ path: path.join(scratch, 'narrow-add-64.png') })
    await modal.getByRole('button', { name: 'Fixture 3 1 costumes', exact: true }).click()
    const narrowAdd = modal.getByRole('button', { name: 'Add Selected (1)', exact: true })
    await narrowAdd.scrollIntoViewIfNeeded()
    const buttonBounds = await narrowAdd.boundingBox()
    assert.ok(buttonBounds.y >= bounds.y && buttonBounds.y + buttonBounds.height <= bounds.y + bounds.height, 'selection controls remain reachable inside the modal')
    await page.screenshot({ path: path.join(scratch, 'narrow-selected-65.png') })
    await page.evaluate(() => { fixture.partial = false })
    await narrowAdd.click()
    await modal.waitFor({ state: 'detached' })
    await topWarning.getByText(/65 fighter entries/).waitFor()
    results.push('expanded warning at 800x700 scrolls to cards and selection controls; one selected fighter installs')
    assert.deepEqual(errors, [])
    fs.writeFileSync(path.join(scratch, 'results.json'), JSON.stringify({ results, errors, screenshots: ['batch-64.png','existing-project-64.png','export-64.png','narrow-add-64.png','narrow-selected-65.png'] }, null, 2))
  } catch (err) {
    fs.writeFileSync(path.join(scratch, 'failure.json'), JSON.stringify({ message: err.message, results, errors }, null, 2))
    throw err
  } finally {
    await app.close()
    console.log(`Roster warning evidence: ${scratch}`)
  }
})
