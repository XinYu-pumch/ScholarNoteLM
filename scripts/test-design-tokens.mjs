// Design contract check; no browser, project data, or network.
import assert from 'node:assert/strict';import {test} from 'node:test';import {readFile,readdir} from 'node:fs/promises';
const root=new URL('../apps/desktop/src/',import.meta.url),tokens=await readFile(new URL('tokens.css',root),'utf8');
test('component styles use tokens for palette, typography, shape and animation timing',async()=>{
 const failures=[];
 for(const file of (await readdir(root)).filter(f=>f.endsWith('.css')&&f!=='tokens.css')){
  const css=(await readFile(new URL(file,root),'utf8')).replace(/\/\*[\s\S]*?\*\//g,'');
  for(const [name,pattern] of Object.entries({palette:/#[\da-f]{3,8}\b|rgba?\(/ig,weight:/font-weight:\s*\d+/g,size:/font-size:\s*[\d.]+(?:px|rem)/g,radius:/border-radius:\s*[1-9][\d.]*px/g,timing:/(?<![\w-])(?:\d*\.\d+|\d+)(?:ms|s)\b/g}))
   for(const match of css.matchAll(pattern))failures.push(`${file}: ${name} ${match[0]}`);
 }
 assert.deepEqual(failures,[]);
});
const color=value=>{const hex=value.replace('#','');const full=hex.length===3?[...hex].map(v=>v+v).join(''):hex;return [0,2,4].map(i=>{const v=parseInt(full.slice(i,i+2),16)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);};
const ratio=(a,b)=>{const x=color(a),y=color(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
test('both palettes meet text, focus and control-boundary contrast on their intended surfaces',()=>{
 const [light,dark]=tokens.split(":root[data-theme='dark']");
 const extract=source=>Object.fromEntries([...source.matchAll(/(--[\w-]+):\s*(#[\da-fA-F]+)\s*;/g)].map(m=>[m[1],m[2]]));
 const base=extract(light);for(const palette of [base,{...base,...extract(dark)}]){
  for(const surface of ['--bg','--surface','--panel','--surface-raised'])for(const ink of ['--text','--muted','--faint'])assert.ok(ratio(palette[ink],palette[surface])>=4.5,`${ink} on ${surface}`);
  for(const ink of ['--accent','--control-border'])for(const surface of ['--surface','--panel','--surface-raised'])assert.ok(ratio(palette[ink],palette[surface])>=3,`${ink} boundary`);
  assert.ok(ratio(palette['--on-accent'],palette['--accent'])>=4.5);assert.ok(ratio(palette['--on-danger'],palette['--red'])>=4.5);
 }
});
