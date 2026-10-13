import {t as tr} from './i18n';
import type {DownloadBatch} from './download-api';
export const taskActive=(state?:string)=>!!state&&['queued','running','stopping'].includes(state);
export const downloadHeld=(state?:string)=>taskActive(state)||state==='paused';
/** Never hide a live/paused task behind a newer historical record. */
export function currentDownload(batches:DownloadBatch[],project:string){
 const own=batches.filter(b=>b.project===project).sort((a,b)=>b.created-a.created);
 return own.find(b=>downloadHeld(b.state))||own[0];
}
export type Pipeline={id:string;mode:string;state:string;stage:string;created:number;error?:string};
export function waitingStage(flow:Pipeline|null|undefined,kind:'download'|'markdown'|'index',created=0){
 if(!flow||flow.mode!=='update'||!taskActive(flow.state)||flow.state==='stopping'||flow.stage==='stopping'||created>=flow.created)return '';
 const order=['waiting','reconcile','download','markdown','index'];
 const current=order.indexOf(flow.stage),target=order.indexOf(kind);
 if(current<0||current>target)return '';
 if(current===target)return '正在准备';
 return current<=1?'等待文献检查':current===2?'等待下载完成':'等待转换完成';
}
export function taskDuration(seconds:number){
 const s=Math.max(0,Math.floor(seconds));
 return s>=3600?tr("{p0} 小时 {p1} 分",{p0:Math.floor(s/3600),p1:Math.floor(s%3600/60)}):s>=60?tr("{p0} 分 {p1} 秒",{p0:Math.floor(s/60),p1:s%60}):tr("{p0} 秒",{p0:s});
}
export function jobElapsed(job:{created?:number;finished?:number;state:string}|null|undefined,now:number){
 if(!job?.created)return undefined;
 const end=job.finished||(taskActive(job.state)?now:undefined);
 return end?Math.max(0,end-job.created):undefined;
}
export function taskResult(state:string,failed=0,deferred=0){
 if(state==='done')return failed||deferred?'已结束 · 部分未完成':'已完成';
 return ({queued:'排队中',running:'进行中',stopping:'正在停止',paused:'已暂停',cancelled:'已取消',stopped:'已停止',interrupted:'已中断',failed:'执行失败'} as Record<string,string>)[state]||state;
}

// Shared by the three rows and the sidebar badge, including automatic handoffs.
export function taskWaits(flow:Pipeline|null|undefined,batch:DownloadBatch|undefined,
 md:{state:string;created?:number;vectorFollowup?:{state:string}}|null|undefined,
 index:{state:string;created?:number}|null|undefined){
 const download=waitingStage(flow,'download',batch?.created);
 const markdown=waitingStage(flow,'markdown',md?.created)||(
  batch?.markdownFollowup?.state==='waiting'&&!['cancelled','failed'].includes(batch.state)
  &&!taskActive(md?.state)&&(!md||(md.created||0)<batch.created)?'等待下载完成':'');
 const indexing=waitingStage(flow,'index',index?.created)||(
  md?.vectorFollowup?.state==='waiting'&&!['stopped','failed','interrupted'].includes(md.state)
  &&!taskActive(index?.state)&&(!index||(index.created||0)<(md.created||0))?'等待转换完成':'');
 return {download,markdown,index:indexing};
}
