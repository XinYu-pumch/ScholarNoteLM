/** Translation catalogue and application-owned copy contracts; no browser or user data. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
const root=new URL('../',import.meta.url),source=new URL('apps/desktop/src/',root);
const catalogue=JSON.parse(fs.readFileSync(new URL('locales/en.json',source),'utf8'));
const params=s=>[...new Set([...s.matchAll(/\{(p\d+)\}/g)].map(m=>m[1]))].sort();
for(const [key,value] of Object.entries(catalogue)){
 assert.ok(value.trim(),`Empty translation: ${key}`);
 assert.deepEqual(params(key),params(value),`Interpolation mismatch: ${key}`);
}
let calls=0;
for(const file of fs.readdirSync(source).filter(f=>/\.tsx?$/.test(f))){
 const text=fs.readFileSync(new URL(file,source),'utf8'),sf=ts.createSourceFile(file,text,99,true);
 function visit(n){
  if(ts.isCallExpression(n)&&['tr','t'].includes(n.expression.getText())&&n.arguments[0]&&ts.isStringLiteral(n.arguments[0])&&/[\u3400-\u9fff]/.test(n.arguments[0].text)){
   assert.ok(catalogue[n.arguments[0].text],`${file}: missing ${n.arguments[0].text}`);calls++;
  }
  if(ts.isJsxAttribute(n)&&n.name.getText()==='value'&&n.initializer&&ts.isJsxExpression(n.initializer)){
   const e=n.initializer.expression;
   assert.ok(!(e&&ts.isCallExpression(e)&&e.expression.getText()==='tr'),`${file}: never translate editable values`);
  }
  ts.forEachChild(n,visit);
 }
 visit(sf);
}
const compiled=ts.transpileModule(fs.readFileSync(new URL('i18n.ts',source),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,esModuleInterop:true,target:ts.ScriptTarget.ES2022}}).outputText;
const memory=new Map(),context={exports:{},require:name=>name==='react'?{useSyncExternalStore:()=>{}}:catalogue,document:{documentElement:{lang:''},title:''},navigator:{language:'en-US'},localStorage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)}};
vm.runInNewContext(compiled,context);const {t,configureLocale,uiLanguage}=context.exports;
assert.equal(uiLanguage(),'en');assert.equal(t('设置'),'Settings');
assert.equal(t('切换项目：{p0}',{p0:'中文研究'}),'Switch project: 中文研究');
assert.equal(t('切换项目：中文研究'),'Switch project: 中文研究');
assert.equal(t('用户自定义研究内容'),'用户自定义研究内容');
configureLocale('zh');assert.equal(t('设置'),'设置');assert.equal(context.document.documentElement.lang,'zh-CN');
configureLocale('en');assert.equal(memory.get('scholarnotelm-ui-language'),'en');
console.log(JSON.stringify({passed:true,translatedKeys:Object.keys(catalogue).length,checkedCalls:calls}));
