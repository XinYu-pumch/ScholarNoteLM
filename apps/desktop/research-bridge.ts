import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import type { IncomingMessage,ServerResponse } from 'node:http';
const root=fileURLToPath(new URL('../..',import.meta.url));
const binary=path.join(root,'cache/tauri-target/debug',process.platform==='win32'?'research-cli.exe':'research-cli');
const env={...process.env,SCHOLARNOTELM_ROOT:process.env.SCHOLARNOTELM_ROOT||root};
export function autoMesh(){const child=spawn(binary,['--auto-mesh'],{cwd:root,env,stdio:'ignore'});child.on('error',()=>{});return child;}
export async function researchBridge(req:IncomingMessage,res:ServerResponse,next:()=>void){
 const streaming=req.url==='/__research/stream';if(req.url!=='/__research'&&!streaming)return next();res.setHeader('Content-Type',streaming?'application/x-ndjson':'application/json');res.setHeader('Cache-Control','no-store');
 const origin=req.headers.origin;
 const host=req.headers.host||'';
 if(req.method!=='POST'||!/^application\/json(?:;|$)/i.test(req.headers['content-type']||'')||! /^(127\.0\.0\.1|localhost):\d+$/.test(host)||(origin&&origin!==`http://${host}`)){res.statusCode=403;res.end(JSON.stringify({ok:false,error:'请求来源不允许'}));return;}
 try{let body='';for await(const chunk of req){body+=chunk;if(body.length>45_000_000){res.statusCode=413;res.end(JSON.stringify({ok:false,error:'请求文件过大'}));return;}}const request=JSON.parse(body);
 const child=spawn(binary,streaming?['--stream']:[],{cwd:root,env,stdio:['pipe','pipe','pipe']});let output='';let completed=false;
 res.on('close',()=>{if(!completed&&streaming){ /* End stdin response; engine notices cancel or disconnected stdout. */ child.stdout.destroy(); }});
 child.stdout.on('data',chunk=>{if(streaming){res.write(chunk);return;}output+=chunk;if(output.length>100_000_000&&!(typeof request.action==='string'&&request.action.startsWith('qa.'))){child.kill();}});child.stderr.resume();
 child.on('error',()=>{if(completed)return;completed=true;res.statusCode=503;res.end(JSON.stringify({ok:false,error:'研究引擎尚未构建，请运行 npm run research:build'}));});
 child.on('close',code=>{if(completed)return;completed=true;if(streaming){res.end();return;}try{const result=JSON.parse(output);res.statusCode=result.ok?200:400;res.end(JSON.stringify(result));}catch{res.statusCode=500;res.end(JSON.stringify({ok:false,error:`研究引擎意外退出 (${code})，已有结果仍保留`}));}});child.stdin.end(body);
 }catch{res.statusCode=400;res.end(JSON.stringify({ok:false,error:'无效请求'}));}
}
