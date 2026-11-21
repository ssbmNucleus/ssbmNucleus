// Real React/Electron lifecycle, with controllable transport and no native
// viewer or user vault. Run with the app/frontend and app dependencies installed.
// NUCLEUS_TEST_DEPENDENCIES may point at another checkout's app/ for worktrees.
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')

const root = path.resolve(__dirname, '../..')
const dependencyRoot = process.env.NUCLEUS_TEST_DEPENDENCIES || path.join(root, 'app')
let electron, build, executablePath
try {
  const appRequire = createRequire(path.join(dependencyRoot, 'package.json'))
  const frontendRequire = createRequire(path.join(dependencyRoot, 'frontend/package.json'))
  electron = appRequire('playwright-core')._electron
  executablePath = appRequire('electron')
  build = frontendRequire('esbuild').build
} catch {}

test('vault deletion retires the right selection and cannot leave ghost cards', {
  skip: !electron || !build ? 'Install app and frontend dependencies for the renderer test' : false,
  timeout: 60000,
}, async () => {
  const scratchRoot = path.join(root, 'app/scratch')
  fs.mkdirSync(scratchRoot, { recursive: true })
  const scratch = fs.mkdtempSync(path.join(scratchRoot, 'vault-delete-renderer-'))
  fs.writeFileSync(path.join(scratch, 'main.cjs'), `
    const {app,BrowserWindow}=require('electron');
    app.setPath('userData',${JSON.stringify(path.join(scratch, 'profile'))});
    app.whenReady().then(()=>{const window=new BrowserWindow({show:false,width:1200,height:900});
      window.loadFile(${JSON.stringify(path.join(scratch, 'index.html'))});});
    app.on('window-all-closed',()=>app.quit());`)
  fs.writeFileSync(path.join(scratch, 'index.html'), '<div id="root" class="app-content"></div><script src="bundle.js"></script>')
  await build({
    stdin: { resolveDir: path.join(root, 'app/frontend'), sourcefile: 'delete-fixture.jsx', loader: 'jsx', contents: `
      import React,{useState}from'react';import{createRoot}from'react-dom/client';
      import{useEditModal}from'./src/vault/hooks/useEditModal.js';
      import CharacterDetailView from'./src/vault/characters/CharacterDetailView.jsx';
      import{createMetadataRefresh}from'./src/vault/metadataRefresh.js';
      import{api}from'./src/shared/transport/api.js';
      window.requests=[];window.alerts=[];window.alert=message=>window.alerts.push(message);
      window.fetch=(url,init={})=>new Promise((resolve,reject)=>window.requests.push({url,body:init.body,
        finish:(data,status=200)=>resolve(new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}})),reject}));
      const a={id:'vibrant',color:'Vibrant',has_csp:false,has_stock:false};
      const b={id:'other',color:'Other',has_csp:false,has_stock:false};window.a=a;window.b=b;
      function App(){const[metadata,setMetadata]=useState({characters:{Luigi:{skins:[a,b,a]},Mario:{skins:[b]}}});
        const[character,setCharacter]=useState('Luigi');const[last,setLast]=useState(0);const[csp,setCsp]=useState(null);
        const[refresh]=useState(()=>createMetadataRefresh({read:()=>api.get('/storage/metadata'),setMetadata,setLoading:()=>{}}));
        const edit=useEditModal({onRefresh:refresh,setLastImageUpdate:setLast});
        window.h={edit,refresh,setMetadata,setCharacter,setCsp,metadata,csp};
        return <CharacterDetailView sort={{key:'custom',dir:'asc'}} selectedCharacter={character} allCharacters={metadata.characters}
          expandedFolders={{}} setExpandedFolders={()=>{}} dragDrop={{}} editModal={edit}
          cspManager={{lastImageUpdate:last,portraits:[],cspManagerSkin:csp,closeCspManager:()=>setCsp(null)}}
          slippiDialog={{}} contextMenuApi={{}} skinCreator={{}} onRefresh={refresh}/>;
      }createRoot(document.getElementById('root')).render(<App/>);` },
    bundle: true, jsx: 'automatic', outfile: path.join(scratch, 'bundle.js'),
    // Vite always defines import.meta.env; shared/config/features.js reads it at load (pulled in via the skin
    // editor header's MCP import chip). Empty here = a non-DEV build with no preview flags.
    define: { 'import.meta.env': '{}' },
    loader: { '.css': 'empty', '.png': 'dataurl', '.svg': 'dataurl' }, logLevel: 'silent',
    banner: { js: 'window.Audio=class{load(){} play(){return Promise.resolve()} pause(){}};' },
    nodePaths: [path.join(dependencyRoot, 'frontend/node_modules')],
  })
  const app = await electron.launch({ executablePath, args: [path.join(scratch, 'main.cjs')] })
  const results = []
  const b = {id:'other',color:'Other',has_csp:false,has_stock:false}
  try {
    const page = await app.firstWindow()
    await page.waitForFunction(() => window.h?.edit)
    const settleCards = n => page.waitForFunction(n => document.querySelectorAll('.skin-card').length === n, n)
    const openA = async () => {
      await page.evaluate(() => {
        h.setCharacter('Luigi'); h.setMetadata({characters:{Luigi:{skins:[a,b]},Mario:{skins:[b]}}})
        h.edit.handleEditClick('costume',{...a,character:'Luigi'})
      })
      await page.waitForFunction(() => h.edit.editingItem?.data.id === a.id)
    }
    const startDelete = async () => {
      await page.evaluate(() => h.edit.handleDelete())
      await page.waitForFunction(() => h.edit.showConfirmDialog)
      await page.evaluate(() => { h.edit.confirmDelete(); h.edit.confirmDelete() })
    }
    const finish = async (suffix, data, status=200) => {
      await page.waitForFunction(suffix => requests.some(r=>r.url.endsWith(suffix)&&!r.done), suffix)
      await page.evaluate(({suffix,data,status}) => {
        const request=requests.find(r=>r.url.endsWith(suffix)&&!r.done);request.done=true;request.finish(data,status)
      }, {suffix,data,status})
    }
    await settleCards(2)
    // Reorder legacy duplicate keys, then remove all rows for the deleted ZIP.
    for (const order of ['top','bottom','deleted']) {
      await page.evaluate(order => h.setMetadata({characters:{Luigi:{skins:order==='top'?[a,a,b]:order==='bottom'?[a,b,a]:[b]}}}),order)
      await page.waitForFunction(order=>h.metadata.characters.Luigi.skins.length===(order==='deleted'?1:3),order)
    }
    await settleCards(1)
    await page.getByRole('button',{name:'Edit Luigi Other',exact:true}).click()
    await page.waitForFunction(()=>h.edit.editingItem?.data.id===b.id)
    results.push('legacy duplicate reorder/delete leaves one correct clickable card')

    // Old metadata lands after the post-delete refresh.
    await page.evaluate(()=>{h.refresh();h.refresh()})
    await page.evaluate(()=>{const r=requests.filter(r=>r.url.endsWith('/metadata'));r[1].done=true;r[1].finish({metadata:{characters:{Luigi:{skins:[b]}}}})})
    await page.waitForFunction(()=>h.metadata.characters.Luigi.skins.length===1)
    await page.evaluate(()=>{const r=requests.find(r=>r.url.endsWith('/metadata')&&!r.done);r.done=true;r.finish({metadata:{characters:{Luigi:{skins:[a,b]}}}})})
    await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,50)))
    assert.equal(await page.evaluate(()=>h.metadata.characters.Luigi.skins.length),1)
    results.push('late metadata cannot resurrect deleted costume')

    await openA();await startDelete()
    assert.equal(await page.evaluate(()=>requests.filter(r=>r.url.endsWith('/costumes/delete')).length),1)
    await page.evaluate(()=>{h.setCharacter('Mario');h.edit.handleEditClick('costume',{...b,character:'Mario'})})
    await finish('/costumes/delete',{success:true})
    await finish('/storage/metadata',{metadata:{characters:{Luigi:{skins:[b]},Mario:{skins:[b]}}}})
    await page.waitForFunction(()=>h.edit.editingItem?.data.character==='Mario')
    results.push('double confirmation sends one delete; older completion preserves new character selection')

    // Cancel and failed requests retain the existing item; a confirmed 404
    // retires it, so there is no repeated stale-action loop.
    await openA();await page.evaluate(()=>h.edit.handleDelete())
    await page.waitForFunction(()=>h.edit.showConfirmDialog)
    await page.evaluate(()=>h.edit.cancelDelete())
    await page.waitForFunction(()=>!h.edit.showConfirmDialog)
    await startDelete();await finish('/costumes/delete',{success:false,error:'fixture denied'},500)
    await page.waitForFunction(()=>!h.edit.deleting)
    assert.equal(await page.evaluate(()=>h.edit.editingItem?.data.id),'vibrant')
    await startDelete();await finish('/costumes/delete',{success:false,error:'already removed'},404)
    await finish('/storage/metadata',{metadata:{characters:{Luigi:{skins:[b]}}}})
    await page.waitForFunction(()=>h.edit.editingItem===null)
    results.push('cancel/failure preserve selection; already-removed response retires selection')

    // Pending preview generation cannot populate a same-ID reimport.
    await openA();await page.evaluate(()=>{h.edit.handleGenerateStock();h.edit.handleRetakeCsp()})
    await page.evaluate(()=>{h.setCsp({...a,character:'Luigi'});h.setMetadata({characters:{Luigi:{skins:[]}}})})
    await page.waitForFunction(()=>h.edit.editingItem===null&&h.csp===null)
    await openA()
    await finish('/costumes/generate-stock',{dataUri:'stale-stock',method:'recolor'})
    await finish('/costumes/generate-csp',{dataUri:'stale-portrait',poseName:'old'})
    await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,50)))
    assert.deepEqual(await page.evaluate(()=>[h.edit.pendingGeneratedStock,h.edit.pendingGeneratedCsp]),[null,null])
    await page.evaluate(()=>h.setCharacter('Mario'))
    await page.waitForFunction(()=>h.edit.editingItem===null&&!h.edit.show3DViewer)
    results.push('bulk removal closes editor/portraits; same-ID reimport ignores old previews; character switch clears selection')

    // The real viewer is mounted, but its path request is still pending when
    // the selected costume disappears. It must never reach native startup.
    await openA()
    await page.evaluate(()=>{
      window.viewerStarts=0;window.electron={
        viewerStart:()=>{window.viewerStarts++;return Promise.resolve({success:true})},
        viewerStop:()=>Promise.resolve(),onViewerMessage:()=>()=>{},
      }
      h.edit.setShow3DViewer(true)
    })
    await page.waitForFunction(()=>requests.some(r=>r.url.endsWith('/api/viewer/paths')))
    await page.evaluate(()=>h.setMetadata({characters:{Luigi:{skins:[b]}}}))
    await page.waitForFunction(()=>h.edit.editingItem===null&&!h.edit.show3DViewer)
    await finish('/api/viewer/paths',{datFile:'fixture-only.dat'})
    await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,50)))
    assert.equal(await page.evaluate(()=>viewerStarts),0)

    const images=[]
    await page.route('**/storage/**',route=>images.push(route))
    await page.evaluate(()=>h.setMetadata({characters:{Luigi:{skins:[{...a,has_stock:true},b]}}}))
    await page.waitForFunction(()=>document.querySelector('img.stock-overlay-img'))
    await page.evaluate(()=>h.setMetadata({characters:{Luigi:{skins:[b]}}}))
    await settleCards(1)
    for (const route of images) await route.fulfill({status:404,body:''}).catch(()=>{})
    assert.equal(await page.getByRole('button',{name:'Edit Luigi Vibrant',exact:true}).count(),0)
    results.push('pending viewer paths and late thumbnail failure cannot revive deleted selection')
    fs.writeFileSync(path.join(scratch,'results.json'),JSON.stringify(results,null,2))
    assert.equal(results.length,6)
  } finally { await app.close() }
})
