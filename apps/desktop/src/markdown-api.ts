import {useQuery} from './useQuery';
import {rpc} from './research-api';



export type MarkdownConfig={device:string;pdftextWorkers:'auto'|number};
export type EngineInfo={ready:boolean;runtime:string;models:string;missing:string[];label:string;backend:string};
export type ComputeDevice={device:string;name:string;reason:string;available:string[];checkedAt?:number};
let computeProbe:Promise<ComputeDevice>|undefined;
export function probeCompute(){return computeProbe??=rpc<ComputeDevice>('markdown.devices',{});}
export type MarkdownSettingsData=EngineInfo&{config:MarkdownConfig;compute?:ComputeDevice|null};
export type MarkdownJob={device?:string;compute?:ComputeDevice;acceleratorFallbacks?:{kind:string;reason:string}[];created?:number;finished?:number;id:string;state:string;mode:string;completed:number;failed:number;skipped:number;current:string;page?:number;pages?:number;engine?:string;pmids:string[];error?:string;vectorFollowup?:{state:string;error?:string};items:{pmid:string;state:string;error?:string}[]};
export type MarkdownStatus=MarkdownSettingsData&{downloadStatus?:{latest:boolean;pending:number;pendingPmids:string[];attemptedMissing:number;missing:number};pdfCount:number;abstractCount:number;sourceReadyCount:number;markdownCount:number;latestCount:number;files:{archived:number;restored:number;redundant:number;errors:{pmid:string;error:string}[]};job:MarkdownJob|null;items:{pmid:string;abstractFallback:boolean;sourceReady:boolean;pdfState:string;markdownState:string;pdf:boolean;ready:boolean;raw:boolean;needsCleaning:boolean;needsConversion:boolean;engine:string;layoutRemoved:number;removed:number}[]};
export function useMarkdown(project:string){
 const result=useQuery<MarkdownStatus>('markdown.status',{project},15000,2500,d=>!!d.job&&['queued','running','stopping'].includes(d.job.state));
 return {data:result.data||null,error:result.error};
}
