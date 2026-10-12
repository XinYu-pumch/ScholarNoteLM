/** Local PDF fonts, CMaps and codecs; never fetch them from a CDN. */
import type {Plugin} from 'vite';
import {createReadStream,readdirSync,readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const base=fileURLToPath(new URL('../../node_modules/pdfjs-dist/',import.meta.url));
export function pdfAssets():Plugin{
 const files=new Map(['cmaps','standard_fonts','wasm'].flatMap(folder=>readdirSync(`${base}${folder}`,{withFileTypes:true}).filter(f=>f.isFile()).map(f=>[`pdfjs/${folder}/${f.name}`,`${base}${folder}/${f.name}`])));
 const serve=(req:{url?:string},res:any,next:()=>void)=>{const key=(req.url||'').split('?')[0].slice(1),file=files.get(key);if(!file)return next();res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.wasm')?'application/wasm':'application/octet-stream');createReadStream(file).pipe(res);};
 return {name:'local-pdf-assets',configureServer(s){s.middlewares.use(serve);},generateBundle(){for(const [fileName,path] of files)this.emitFile({type:'asset',fileName,source:readFileSync(path)});}};
}
