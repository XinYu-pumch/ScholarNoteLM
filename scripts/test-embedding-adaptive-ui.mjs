/** Real settings UI, isolated mocked RPC: no user configuration or API calls. */
import {webkit,expect} from '@playwright/test';
import {createServer} from 'vite';
import {mkdtemp,writeFile,rm,mkdir} from 'node:fs/promises';
import path from 'node:path';
const root=process.cwd(),tmp=await mkdtemp(path.join(root,'tmp/embedding-ui-')),out=path.join(root,'docs/embedding-resilience-20260929');let server,browser;
try{
 await mkdir(out,{recursive:true});
 await writeFile(path.join(tmp,'index.html'),'<div id="root"></div><script type="module" src="/main.jsx"></script>');
 await writeFile(path.join(tmp,'main.jsx'),`import React from 'react';import {createRoot} from 'react-dom/client';
import Settings from '/@fs/${root}/apps/desktop/src/EmbeddingSettings.tsx';
import '/@fs/${root}/apps/desktop/src/styles.css';import '/@fs/${root}/apps/desktop/src/workbench.css';import '/@fs/${root}/apps/desktop/src/vector.css';import '/@fs/${root}/apps/desktop/src/panels.css';
window.saved={id:'fixture',name:'默认配置',baseUrl:'https://api.example.test/v1',model:'Pro/BAAI/bge-m3',modelRevision:'',hasKey:true,rpm:1800,tpm:450000,batchSize:32,concurrency:4,timeout:120,autoIndex:true,adaptive:false};
window.fetch=async(url,opts)=>{if(url!=='/__research')throw Error('unexpected request');const {action,args}=JSON.parse(opts.body);if(action==='vector.settings.save')window.saved={...window.saved,...args};else if(action!=='vector.settings')throw Error('unexpected RPC '+action);return new Response(JSON.stringify({ok:true,data:{profiles:[window.saved],activeProfile:'fixture',savedProfile:'fixture',runtimeReady:true}}));};
createRoot(document.getElementById('root')).render(<main className="page" style={{padding:40}}><Settings/></main>);`);
 server=await createServer({configFile:false,root:tmp,cacheDir:path.join(tmp,'cache'),esbuild:{jsx:'automatic'},optimizeDeps:{include:['react','react-dom/client','react/jsx-runtime','lucide-react','@tauri-apps/api/core']},server:{host:'127.0.0.1',port:0,fs:{allow:[root]}},plugins:[{name:'mock-context',enforce:'pre',resolveId(src,importer){if(importer?.startsWith(root+'/apps/desktop/src/')&&src==='./context')return '\0test-context';},load(id){if(id==='\0test-context')return 'export const useApp=()=>({notify:()=>{}});';}}]});await server.listen();
 browser=await webkit.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());await page.goto(`http://127.0.0.1:${server.httpServer.address().port}`);
 await page.getByText('高级请求参数',{exact:true}).click();const auto=page.getByRole('checkbox',{name:'自动调度索引请求'}),batch=page.getByLabel('每批文本数'),concurrency=page.getByLabel('并发请求');
 await expect(batch).toBeEnabled();await auto.check();await expect(batch).toBeDisabled();await expect(concurrency).toBeDisabled();await expect(page.getByLabel('每分钟请求数')).toBeEnabled();await expect(page.getByLabel('每分钟输入量 · token')).toHaveValue('450000');
 await page.getByRole('button',{name:'保存配置'}).click();await expect(auto).toBeChecked();expect(await page.evaluate(()=>({adaptive:window.saved.adaptive,batch:window.saved.batchSize,concurrency:window.saved.concurrency,rpm:window.saved.rpm,tpm:window.saved.tpm}))).toEqual({adaptive:true,batch:32,concurrency:4,rpm:1800,tpm:450000});
 await page.screenshot({path:path.join(out,'embedding-auto-settings.png'),fullPage:true,animations:'disabled'});
 await auto.uncheck();await expect(batch).toBeEnabled();await expect(concurrency).toBeEnabled();await expect(batch).toHaveValue('32');await expect(concurrency).toHaveValue('4');expect(errors).toEqual([]);
 console.log(JSON.stringify({passed:true,checks:['auto setting saved','fixed controls disabled only in automatic mode','quotas editable','manual values preserved','no browser errors']}));
}finally{await browser?.close();await server?.close();await rm(tmp,{recursive:true,force:true});}
