import SearchResponse,{ProposalActions} from './SearchResponse';
import {renderSearchTrace} from './search-stream-diagnostics';
import {queryTextKey} from './search-proposals';
import {usePageState,pageMemory,rememberPage} from './page-memory';
import ModelPicker,{useWorkspaceModel} from './ModelPicker';
import TurnIndex from './TurnIndex';
import {useSearchSessions,searchSession,runningSearchThreads,startSearchSession,stopSearchSession,forgetSearchSessions,dismissSearchError} from './search-chat-sessions';
import ConversationList from './ConversationList';
import {useCallback,useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {PanelLeft,Plus,Send,Square,Copy,RotateCcw,GitBranch,Pencil,Sparkles} from 'lucide-react';
import {useApp} from './context';
import {rpc,peekRpc,message,type ChatMessage,type ChatThread,type Proposal,type Query} from './research-api';
function responseText(m:ChatMessage){
 // Older replies stored prose and structured queries separately. Keep copying
 // those replies useful, too, without duplicating code already in the prose.
 const missing=(m.result?.queries||[]).filter(q=>!m.text.includes(q.text));
 return m.text+missing.map(q=>`\n\n### ${q.name}\n\n\`\`\`pubmed\n${q.text}\n\`\`\``).join('');
}
export default function SearchChat({queries,onAdd}:{queries:Query[];onAdd:(q:Proposal)=>Promise<void>}){
 const {project,notify}=useApp();
 const [threadsOpen,setThreadsOpen]=useState(()=>window.innerWidth>900);
 useEffect(()=>{const onEscape=(event:KeyboardEvent)=>{if(event.key!=='Escape'||event.defaultPrevented||document.querySelector('dialog[open], [role="listbox"]'))return;if(threadsOpen&&window.matchMedia('(max-width:900px)').matches)setThreadsOpen(false);};window.addEventListener('keydown',onEscape);return()=>window.removeEventListener('keydown',onEscape);},[threadsOpen]);
 const [threads,setThreads]=useState<ChatThread[]>(()=>peekRpc<ChatThread[]>('chat.list',{project:project.id})||[]);const [current,setCurrent]=useState<ChatThread|null>(()=>peekRpc<ChatThread>('chat.get',{project:project.id,id:localStorage.getItem(`scholar-chat:${project.id}`)||''})||null);const [storedMessages,setMessages]=useState<ChatMessage[]>(current?.messages||[]);
 const modelChoice=useWorkspaceModel(`${project.id}:search`);const modelLabel=modelChoice.label;
 const [draft,setDraft]=usePageState(`${project.id}:search:draft`,'');const [pending,setPending]=useState(false);const [error,setError]=useState('');const [editing,setEditing]=useState<number|null>(null);const [editText,setEditText]=useState('');
 const alive=useRef(true);const scroll=useRef<HTMLDivElement>(null);const following=useRef(true);const input=useRef<HTMLTextAreaElement>(null);
 useSearchSessions();const session=searchSession(project.id,current?.id);const streaming=!!session?.active;
 const messages=session?.messages||storedMessages;const runningIds=runningSearchThreads(project.id);const activity=runningIds.join(',');
 const busy=pending||streaming;const shownError=error||session?.error;
 const onAddRef=useRef(onAdd);onAddRef.current=onAdd;
 const addingRef=useRef(new Set<string>());const [adding,setAdding]=useState(new Set<string>());
 const add=useCallback(async(q:Proposal)=>{const key=queryTextKey(q.text);if(addingRef.current.has(key))return;addingRef.current.add(key);setAdding(new Set(addingRef.current));setError('');
  try{await onAddRef.current(q);}catch(e){if(alive.current)setError(message(e));}finally{addingRef.current.delete(key);if(alive.current)setAdding(new Set(addingRef.current));}
 },[]);
 const copy=useCallback(async(text:string)=>{try{await navigator.clipboard.writeText(text);notify('已复制');}catch{setError('未能访问剪贴板，请选择文字后复制');}},[notify]);
 const added=useMemo(()=>new Set(queries.filter(q=>!q.archived).map(q=>queryTextKey(q.text))),[queries]);
 const proposalActions=useMemo(()=>({added,adding,add,copy}),[added,adding,add,copy]);
 useLayoutEffect(()=>{if(session)renderSearchTrace(session.streamId,session.sequence);},[session?.streamId,session?.sequence]);

 useEffect(()=>{void list().then(items=>{if(alive.current)setCurrent(c=>c?{...c,name:items.find(t=>t.id===c.id)?.name||c.name}:c);}).catch(()=>{});},[project.id,activity]);
 const list=async()=>{const items=await rpc<ChatThread[]>('chat.list',{project:project.id});if(alive.current)setThreads(items);return items;};
 async function choose(id:string){const t=await rpc<ChatThread>('chat.get',{project:project.id,id});if(!alive.current)return;setCurrent(t);setMessages(t.messages||[]);setEditing(null);setError('');following.current=pageMemory<{following:boolean}>(`${project.id}:search:scroll:${id}`)?.following??true;localStorage.setItem(`scholar-chat:${project.id}`,id);}
 async function action(fn:()=>Promise<void>){setPending(true);setError('');try{await fn();}catch(e){if(alive.current)setError(message(e));}finally{if(alive.current)setPending(false);}}
 async function create(){const t=await rpc<ChatThread>('chat.new',{project:project.id});await list();await choose(t.id);setDraft('');input.current?.focus();return t;}

 useEffect(()=>{alive.current=true;void action(async()=>{const items=await list();const saved=localStorage.getItem(`scholar-chat:${project.id}`);const id=items.find(t=>t.id===saved)?.id||items[0]?.id;if(id)await choose(id);else {setCurrent(null);setMessages([]);}});return()=>{alive.current=false;};},[project.id]);
 const restoredScroll=useRef('');const lastScrollTop=useRef(0);const pointerReading=useRef(false);
 useEffect(()=>{const release=()=>{pointerReading.current=false;};window.addEventListener('pointerup',release);window.addEventListener('pointercancel',release);return()=>{window.removeEventListener('pointerup',release);window.removeEventListener('pointercancel',release);};},[]);
 useLayoutEffect(()=>{const el=scroll.current;if(!el||!current)return;const key=`${project.id}:search:scroll:${current.id}`;
  if(restoredScroll.current!==key){restoredScroll.current=key;const saved=pageMemory<{top:number;following:boolean}>(key);el.scrollTop=saved?.top??el.scrollHeight;following.current=saved?.following??true;}
  else if(following.current&&!pointerReading.current)el.scrollTop=el.scrollHeight;
  lastScrollTop.current=el.scrollTop;
 },[current?.id,messages]);
 async function send(value=draft,target=current,base=messages){
  if(!value.trim()||pending||searchSession(project.id,target?.id)?.active)return;
  setError('');setEditing(null);setPending(true);following.current=true;
  try{
   let t=target;if(!t){t=await create();base=[];}
   if(!base.length&&t.name==='新对话'){await rpc('chat.rename',{project:project.id,id:t.id,name:value.trim().slice(0,28)});await list();}
   setDraft('');void startSearchSession(project.id,t.id,value,base,modelLabel,modelChoice.selection);
  }catch(e){if(alive.current)setError(message(e));}
  finally{if(alive.current)setPending(false);}
 }
 async function fork(keepCount:number,resend?:string){if(!current)return;const t=await rpc<ChatThread>('chat.fork',{project:project.id,id:current.id,keepCount});await list();await choose(t.id);if(resend!==undefined)await send(resend,t,t.messages||[]);else{setDraft('');notify('已创建分支，原对话完整保留');input.current?.focus();}}
 async function regenerate(index:number){let user=index-1;while(user>=0&&messages[user].role!=='user')user--;if(user>=0)await fork(user,messages[user].text);}
 async function changeConversation(fn:()=>Promise<void>){setPending(true);try{await fn();}finally{if(alive.current)setPending(false);}}
 async function renameConversation(id:string,name:string){await changeConversation(async()=>{await rpc('chat.rename',{project:project.id,id,name});await list();if(current?.id===id){setCurrent(c=>c?{...c,name}:c);}});}
 async function duplicateConversation(id:string){await changeConversation(async()=>{const t=await rpc<ChatThread>('chat.copy',{project:project.id,id});await list();await choose(t.id);setDraft('');notify('已复制对话，可在副本中独立继续');});}
 async function deleteConversations(ids:string[]){await changeConversation(async()=>{await rpc('chat.archive_many',{project:project.id,ids});forgetSearchSessions(project.id,ids);const items=await list();if(current&&ids.includes(current.id)){setCurrent(null);setMessages([]);setDraft('');if(items.length)await choose(items[0].id);else localStorage.removeItem(`scholar-chat:${project.id}`);}});}
 return <div className="search-chat-layout">
  {threadsOpen&&<button className="conversation-backdrop" aria-label="关闭检索对话侧栏" onClick={()=>setThreadsOpen(false)}/>}<aside className="chat-sidebar" hidden={!threadsOpen}><div className="chat-list-heading"><span>我的对话</span><button className="icon-button" aria-label="收起对话侧栏" onClick={()=>setThreadsOpen(false)}><PanelLeft size={15}/></button><button title="新建对话" aria-label="新建对话" disabled={pending} onClick={()=>void action(async()=>{await create();})}><Plus size={17}/></button></div><ConversationList items={threads} currentId={current?.id} className="chat-thread-list" label="文献检索对话" disabled={pending} runningIds={runningIds} onChoose={id=>void action(()=>choose(id))} onRename={renameConversation} onCopy={duplicateConversation} onDelete={deleteConversations}/></aside>
  <section className="wb-chat">
   <div className="wb-chat-heading">{!threadsOpen&&<button className="icon-button" aria-label="展开对话侧栏" onClick={()=>setThreadsOpen(true)}><PanelLeft size={16}/></button>}<Sparkles size={18}/><div className="chat-current-title"><h3>{current?.name||'检索助手'}</h3><p>讨论研究问题，设计 PubMed 检索式</p></div><ModelPicker label="检索模型" value={modelChoice.selection} onChange={modelChoice.choose} disabled={busy}/><TurnIndex key={current?.id} items={messages.flatMap((m,i)=>m.role==='user'?[{id:String(i),question:m.text,status:streaming&&i>=messages.length-2?'生成中':messages[i+1]?.error?'失败':undefined}]:[])} scroll={scroll} onNavigate={latest=>{following.current=latest;}}/></div>
   {shownError&&<div className="chat-error" role="alert">{shownError}<button aria-label="关闭聊天错误" onClick={()=>{setError('');if(current)dismissSearchError(project.id,current.id);}}>×</button></div>}
   <ProposalActions.Provider value={proposalActions}><div className="wb-conversation" ref={scroll} tabIndex={0} aria-label="检索对话内容" onWheel={e=>{if(e.deltaY<0)following.current=false;else if(e.deltaY>0&&e.currentTarget.scrollHeight-e.currentTarget.scrollTop-e.currentTarget.clientHeight<2)following.current=true;}} onPointerDown={()=>{pointerReading.current=true;following.current=false;}} onKeyDown={e=>{if(['ArrowUp','PageUp','Home'].includes(e.key))following.current=false;}} onScroll={()=>{const el=scroll.current;if(el){const delta=el.scrollTop-lastScrollTop.current;if(delta< -1)following.current=false;else if(delta>0&&el.scrollHeight-el.scrollTop-el.clientHeight<2)following.current=true;lastScrollTop.current=el.scrollTop;if(current)rememberPage(`${project.id}:search:scroll:${current.id}`,{top:el.scrollTop,following:following.current});}}}>
    {!messages.length&&<div className="wb-chat-intro"><span>从你的问题开始</span><h2>这一次，你想理解什么？</h2><p>描述研究主题、研究对象和你关注的问题，我们一起设计检索策略。</p><button disabled={busy} onClick={()=>{setDraft(`我想围绕“${project.name}”撰写综述。请设计一条基础检索和几个不同方向的补充检索。`);input.current?.focus();}}>为当前项目设计检索式 <Plus size={14}/></button></div>}
    {messages.map((m,i)=>{const live=streaming&&i===messages.length-1&&m.role==='assistant';return <article data-turn-id={m.role==='user'?String(i):undefined} tabIndex={-1} className={`chat-message ${m.role}`} key={`${current?.id||'new'}-${i}`}>
     <div className="chat-speaker">{m.role==='user'?'你':(m.modelLabel||m.result?.modelLabel||m.result?.model||modelLabel||'检索助手')}{live&&<span className="chat-live">正在回复<span> ···</span></span>}</div>
     <div className="chat-bubble">
      {editing===i?<div className="chat-edit"><textarea aria-label="编辑用户消息" autoFocus value={editText} onChange={e=>setEditText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)&&!e.nativeEvent.isComposing){e.preventDefault();if(editText.trim())void action(()=>fork(i,editText));}}}/><div><button className="button secondary compact" onClick={()=>setEditing(null)}>取消</button><button className="button primary compact" disabled={busy||!editText.trim()} onClick={()=>void action(()=>fork(i,editText))}>在新分支重发</button></div></div>:m.role==='user'?<p>{m.text}</p>:<SearchResponse message={m} live={live}/>}

     </div>
     {!live&&<div className="chat-message-actions">{m.role==='user'?<button disabled={busy} onClick={()=>{setEditing(i);setEditText(m.text);}}><Pencil size={13}/>编辑重发</button>:<><button disabled={!m.text} onClick={()=>void copy(responseText(m))}><Copy size={13}/>复制</button><button disabled={busy} onClick={()=>void action(()=>regenerate(i))}><RotateCcw size={13}/>重新生成</button></>}<button disabled={busy} onClick={()=>void action(()=>fork(i+1))}><GitBranch size={13}/>从这里开启新对话</button></div>}
    </article>;})}
   </div></ProposalActions.Provider>
   <form className="wb-composer" onSubmit={e=>{e.preventDefault();if(!busy)void send();}}><textarea ref={input} aria-label="研究需求" placeholder="描述你的研究问题，或继续调整检索方向…" value={draft} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)&&!e.nativeEvent.isComposing){e.preventDefault();if(!busy&&draft.trim())void send();}}} rows={2}/><div><span>Enter 换行 · {navigator.platform.includes('Mac')?'⌘':'Ctrl'} + Enter 发送</span>{streaming?<button type="button" className="button secondary compact" onClick={()=>{if(current)void stopSearchSession(project.id,current.id).catch(e=>setError(message(e)));}}><Square size={13}/>停止生成</button>:<button className="button primary compact" disabled={busy||!draft.trim()}><Send size={14}/>发送</button>}</div></form>
  </section>
 </div>;
}
