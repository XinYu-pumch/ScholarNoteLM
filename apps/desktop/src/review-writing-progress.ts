export type WritingJob={token?:string;created?:number;updated?:number;mode?:string;state?:string;phase?:string;error?:string;total?:number;completed?:number;failed?:number;pending?:number;running?:number;cancelled?:number;settled?:number;items?:Record<string,{state:string;received?:number;reasoningCharacters?:number;error?:string;finished?:number}>};
type Unit={id:string;nodes:string[];leafIds:string[];state:string;completed:boolean;latest:boolean;hasContent:boolean;promptReady:boolean;error:string;received:number;reasoningCharacters:number;revision:string};
type Stage={state:string;completed:number;total:number;shortfalls?:number};
type State={job:WritingJob;units:Unit[];fileRevision:string;hasContent?:boolean;completed:number;prepared:number;latest:number;stages?:{preparation:Stage;writing:Stage}};

/** Counters describe worker publications, never authorize generation or export. */
export function mergeWritingProgress<T extends State>(state:T,job?:WritingJob):T{
 if(!job?.token||job.token!==state.job.token||(job.updated||0)<=(state.job.updated||0))return state;
 const units=state.units.map(u=>{
  const item=job.items?.[u.id];if(!item)return u;
  const written=job.mode==='write'&&item.state==='done',prepared=job.mode==='prepare'&&item.state==='done';
  return {...u,state:item.state,error:item.error||'',received:item.received||0,reasoningCharacters:item.reasoningCharacters||0,
   completed:u.completed||written,hasContent:u.hasContent||written,latest:written||u.latest,promptReady:u.promptReady||prepared,
   revision:written||prepared?`${job.token}:${item.finished||'done'}`:u.revision};
 });
 const completed=units.filter(u=>u.completed).length,prepared=units.filter(u=>u.promptReady).length;
 const fileRevision=units.map(u=>u.revision).join('|');
 return {...state,job,units,completed,prepared,latest:units.filter(u=>u.latest).length,hasContent:units.some(u=>u.hasContent),fileRevision,
  stages:state.stages?{...state.stages,
   preparation:{...state.stages.preparation,completed:Math.max(state.stages.preparation.completed,units.filter(u=>u.promptReady).reduce((n,u)=>n+u.leafIds.length,0)),state:prepared===units.length?'ready':state.stages.preparation.state},
   writing:{...state.stages.writing,completed:units.filter(u=>u.completed).reduce((n,u)=>n+u.nodes.length,0),state:completed===units.length?'complete':completed?'partial':state.stages.writing.state}}:undefined};
}
