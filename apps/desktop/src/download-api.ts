import {useQuery} from './useQuery';
import {useCallback} from 'react';
import {rpc} from './research-api';
export type PdfAsset={pmid:string;source:string;path:string;bytes:number;pages:number;sha256:string;downloaded?:number;pmcid?:string;version?:string|number;isManuscript?:boolean;exists:boolean;url?:string;key?:string;selectionReason?:string;identity?:string|{status?:string;reason?:string;[key:string]:unknown}};
export type DownloadItem={pmid:string;title:string;state:string;stage:string;source:string;error:string;bytes:number;progress?:{bloomHit?:boolean;retryStatus?:string;nextAttemptAt?:number;retryUsed?:number;zotero?:{outcome?:string;reason?:string;attachmentTitle?:string;manuscriptKind?:string};retrySpentSeconds?:number;retryNetworkSeconds?:number;retryWaitSeconds?:number}};
export type DownloadConfig={downloadMode?:'zotero';zoteroAddress:string;email:string;fastOa:boolean;unpaywallConcurrency:number;pmcConcurrency:number;europePmcConcurrency:number;europePmcTimeout:number;europePmcAttempts:number;timeout:number;attempts:number;oaFileTimeout:number;oaArticleTimeout:number;s3ArticleTimeout:number;mirrors:string[];};
export type DownloadBatch={markdownFollowup?:{state:string;error?:string;id?:string};id:string;project:string;state:string;control:string;created:number;snapshot:string;config:DownloadConfig;items:DownloadItem[];counts:Record<string,number>;reportPath:string;error:string;elapsed:number;bloomSummary?:{hits:number;firstSuccess:number;retrySuccess:number;otherRecovery:number;failed:number;deferred?:number;pending:number}};
export type DownloadState={batches:DownloadBatch[];assets:Record<string,PdfAsset>};
export const downloadChanged=()=>window.dispatchEvent(new Event('downloads-changed'));
export const downloadLabels:Record<string,string>={queued:'排队中',running:'下载中',success:'已下载',skipped:'已有 PDF',done:'已完成',paused:'已暂停',cancelled:'已取消',failed:'未获取全文',deferred:'未完成，可重试'};
export const stageLabels:Record<string,string>={zotero:'Zotero 本地补充',scihub_bloom:'Sci-Hub 下载',unpaywall:'Unpaywall',pmc_s3:'PMC S3',europe_pmc_getpdf:'Europe PMC getPdf',pmc_parallel:'PMC / Europe PMC 下载',scihub_retry:'Sci-Hub 补救 / 重试',oa_slow:'开放获取来源重试',europe_pmc:'Europe PMC 重试',slow_rescue:'PMC 重试'};
const emptyDownloads:DownloadState={batches:[],assets:{}};
export function useDownloads(project:string){
 const result=useQuery<DownloadState>('download.list',{project},10000,2000,d=>d.batches.some(b=>['queued','running'].includes(b.state)));
 const data=result.data||emptyDownloads;const error=result.error;
 const item=useCallback((pmid:string)=>data.batches.flatMap(b=>b.items).find(i=>i.pmid===pmid),[data]);
 return {data,error,item,loading:result.data===undefined&&!error};
}
export async function startDownload(project:string,pmids?:string[]){const r=await rpc<{id:string;count:number}>('download.start',{project,...(pmids?{pmids}: {})});downloadChanged();return r;}
export const mb=(n:number)=>n>=1048576?`${(n/1048576).toFixed(1)} MB`:`${Math.round(n/1024)} KB`;

export function recoveryLabel(item:DownloadItem){
 if(['paused','cancelled'].includes(item.state))return downloadLabels[item.state];
 if(item.state==='deferred')return '未完成，可重试';
 const status=item.progress?.retryStatus;
 if(status==='success')return '补救成功';
 if(status==='recovered_elsewhere')return '其他来源已补全';
 if(item.state==='failed'&&item.progress?.bloomHit)return '补救未成功';
 if(status==='waiting')return '等待补救';
 if(status==='running')return '补救中';
 return downloadLabels[item.state]||item.state;
}
export async function retryBloomDownloads(project:string){
 const r=await rpc<{id:string;count:number}>('download.start',{project,mode:'bloom_retry'});
 downloadChanged();return r;
}
