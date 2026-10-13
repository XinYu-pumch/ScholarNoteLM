// Pure navigation coordination tests; no app server, user data, or model calls.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const source=await readFile(new URL('../apps/desktop/src/navigation.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {registerNavigationGuard,canNavigate,requestNavigation}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('keeps the original destination while a draft decision/save is pending',async()=>{
  let decide;let calls=0;const visited=[];
  const unregister=registerNavigationGuard(()=>{calls++;return new Promise(resolve=>{decide=resolve;});});
  requestNavigation(()=>visited.push('original'));
  requestNavigation(()=>visited.push('second click'));
  await tick();assert.equal(calls,1);assert.deepEqual(visited,[]);
  decide(true);await tick();assert.deepEqual(visited,['original']);unregister();
});

test('continue editing cancels navigation and permits a later attempt',async()=>{
  let allow=false;const visited=[];
  const unregister=registerNavigationGuard(()=>allow);
  requestNavigation(()=>visited.push('cancelled'));await tick();assert.deepEqual(visited,[]);
  allow=true;requestNavigation(()=>visited.push('saved'));await tick();assert.deepEqual(visited,['saved']);unregister();
});

test('all active editors must allow leaving; unmounted guards are removed',async()=>{
  const first=registerNavigationGuard(()=>true);
  const second=registerNavigationGuard(()=>false);
  assert.equal(await canNavigate(),false);second();assert.equal(await canNavigate(),true);first();
  assert.equal(await canNavigate(),true);
});

test('notification severity chooses accessible status and never marks failure as success',async()=>{
  const source=await readFile(new URL('../apps/desktop/src/Notification.tsx',import.meta.url),'utf8');
  const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const module={exports:{}};
  new Function('require','module','exports',compiled)(createRequire(import.meta.url),module,module.exports);
  const {Notification}=module.exports;
  for(const [tone,icon,role] of [['error','circle-alert','alert'],['warning','triangle-alert','status'],['info','info','status'],['success','check','status']]){
    const html=renderToStaticMarkup(Notification({notice:{message:'验收通知',tone},onClose:()=>{}}));
    assert.match(html,new RegExp(`lucide-${icon}`));assert.match(html,new RegExp(`role="${role}"`));
    assert.match(html,/aria-label="关闭通知"/);
    if(tone!=='success')assert.doesNotMatch(html,/lucide-check/);
  }
});
