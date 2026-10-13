// No server, native window, credentials or project files. Fault injection at the persistence boundary.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../apps/desktop/src/exitProtocol.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {flushLatestState,resolveCloseRequest}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('native approval waits for the draft decision and final write',async()=>{
 const draft=deferred(),disk=deferred(),events=[];
 const task=resolveCloseRequest({canLeave:()=>draft.promise,flush:()=>{events.push('write');return disk.promise;},answer:async allow=>events.push(allow),saving:v=>events.push(v?'saving':'idle'),error:()=>assert.fail('unexpected failure')});
 await tick();assert.deepEqual(events,[]);draft.resolve(true);await tick();assert.deepEqual(events,['saving','write']);
 disk.resolve();await task;assert.deepEqual(events,['saving','write','idle',true]);
});
test('cancel keeps the app open and performs no write',async()=>{
 const answers=[];await resolveCloseRequest({canLeave:async()=>false,flush:()=>assert.fail('cancel must not write'),answer:async v=>answers.push(v),saving:()=>{},error:()=>assert.fail('unexpected error')});assert.deepEqual(answers,[false]);
});
test('disk failure denies exit; a later retry can succeed',async()=>{
 const answers=[],errors=[];let fail=true;
 const opts={canLeave:async()=>true,flush:async()=>{if(fail)throw Error('disk full');},answer:async v=>answers.push(v),saving:()=>{},error:e=>errors.push(e.message)};
 await resolveCloseRequest(opts);assert.deepEqual(answers,[false]);assert.deepEqual(errors,['disk full']);
 fail=false;await resolveCloseRequest(opts);assert.deepEqual(answers,[false,true]);
});
test('drains older autosaves and includes the last edit during I/O',async()=>{
 const old=deferred(),first=deferred(),written=[];let latest={notes:'first'};
 const task=flushLatestState(old.promise,()=>latest,async value=>{written.push(value.notes);if(written.length===1)await first.promise;});
 await tick();assert.deepEqual(written,[]);old.resolve();await tick();latest={notes:'last keystroke'};first.resolve();
 assert.equal(await task,latest);assert.deepEqual(written,['first','last keystroke']);
});
test('a previously failed autosave is retried; a new failure is not swallowed',async()=>{
 let writes=0;const state={notes:'retry'};
 assert.equal(await flushLatestState(Promise.reject(Error('old failure')),()=>state,async()=>{writes++;}),state);assert.equal(writes,1);
 await assert.rejects(flushLatestState(Promise.resolve(),()=>state,async()=>{throw Error('new failure');}),/new failure/);
});
