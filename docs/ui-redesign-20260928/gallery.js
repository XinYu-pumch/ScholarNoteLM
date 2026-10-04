const pages = [{"id":"01-overview","title":"项目概览","note":"去掉宣传横幅与轨道装饰，用紧凑指标和研究内容建立首页层级。","before":"current/01-overview.png","after":"previews/01-overview.png"},{"id":"02-search","title":"检索式管理","note":"浅色表头、双行策略、对齐的结果统计；完整检索式按需展开。","before":"current/02-search.png","after":"previews/02-search.png"},{"id":"03-search-assistant","title":"检索助手","note":"会话目录与回答分开，检索式采用等宽字体，输入区固定在对话底部。","before":"current/03-search-assistant.png","after":"previews/03-search-assistant.png"},{"id":"04-search-results","title":"合并结果","note":"文献标题优先，作者与来源适度收敛；纳入状态和期刊分区分别呈现。","before":"current/04-search-results.png","after":"previews/04-search-results.png"},{"id":"05-library","title":"文献库","note":"四张大流程卡片压缩成状态带，把文献列表还给首屏。","before":"current/05-library.png","after":"previews/05-library.png"},{"id":"06-review-outline","title":"综述大纲","note":"树形大纲成为主体；标题属性进入右侧面板，删除收进更多菜单。","before":"current/06-review-outline.png","after":"previews/06-review-outline.png"},{"id":"07-review-writing","title":"综述正文","note":"目录、正文与证据三栏；生成参数收进工具栏，保留过期与待更新提示。","before":"current/07-review-writing.png","after":"previews/07-review-writing.png"},{"id":"08-qa","title":"文献问答","note":"去掉深色气泡，拉开问题、检索过程、答案与引用的层级。","before":"current/08-qa.png","after":"previews/08-qa.png"},{"id":"09-reader","title":"阅读与笔记","note":"衬线标题与摘要排版；作者折叠，笔记保持清晰的独立工作面。","before":"current/09-reader.png","after":"previews/09-reader.png"},{"id":"10-tasks","title":"任务中心","note":"下载、转换、索引使用相同的行结构；进度、统计和日志位置统一。","before":"current/10-tasks.png","after":"previews/10-tasks.png"},{"id":"11-settings","title":"模型设置","note":"分组表单与模型能力表；保存、验证和配置切换有稳定的位置。","before":"current/11-settings.png","after":"previews/11-settings.png"},{"id":"12-embedding","title":"Embedding 设置","note":"按连接、请求限制、测试分组，移除多层容器与重复标题。","before":"current/12-embedding.png","after":"previews/12-embedding.png"}];

const $ = s => document.querySelector(s);
let thumbMode = new URLSearchParams(location.search).get('view') === 'originals' ? 'before' : 'after';
if (new URLSearchParams(location.search).has('contact')) document.body.classList.add('contact-mode');
let index=0, mode='after', zoom=false;
const viewer=$('#viewer');
function renderGrid(){
 $('#grid').replaceChildren(...pages.map((p,i)=>{
  const tile=document.createElement('article');tile.className='tile';
  const button=document.createElement('button');button.setAttribute('aria-label','查看'+p.title+'前后对照');
  const img=document.createElement('img');img.src=p[thumbMode];img.alt=p.title+(thumbMode==='after'?'改版预览':'当前截图');img.loading='eager';
  const badge=document.createElement('span');badge.className='badge';badge.textContent=thumbMode==='after'?'预览':'原图';
  button.append(img,badge);button.addEventListener('click',()=>{index=i;mode=thumbMode;zoom=false;renderViewer();viewer.showModal()});
  const title=document.createElement('h3');const num=document.createElement('span');num.className='num';num.textContent=String(i+1).padStart(2,'0');title.append(num,p.title);
  const note=document.createElement('p');note.textContent=p.note;tile.append(button,title,note);return tile;
 }));
 $('#show-after').setAttribute('aria-pressed',thumbMode==='after');$('#show-before').setAttribute('aria-pressed',thumbMode==='before');
}
$('#show-after').onclick=()=>{thumbMode='after';renderGrid()};$('#show-before').onclick=()=>{thumbMode='before';renderGrid()};
function renderViewer(){
 const p=pages[index];$('#viewer-title').textContent=p.title;$('#viewer-note').textContent=p.note;$('#counter').textContent=(index+1)+' / '+pages.length;
 $('#prev').disabled=index===0;$('#next').disabled=index===pages.length-1;
 document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.mode===mode));
 $('#zoom').setAttribute('aria-pressed',zoom);$('#zoom').textContent=zoom?'适应窗口':'放大细看';
 const compare=$('#compare');compare.className='compare'+(mode==='both'?' both':'')+(zoom?' zoom':'');
 compare.replaceChildren(...(mode==='both'?['before','after']:[mode]).map(m=>{
  const fig=document.createElement('figure'),caption=document.createElement('figcaption'),img=document.createElement('img');
  caption.textContent=m==='before'?'当前 App · 实际截图':'改版方案 · 生成预览';img.src=p[m];img.alt=p.title+' '+caption.textContent;fig.append(caption,img);return fig;
 }));
 $('#open-before').href=p.before;$('#open-after').href=p.after;
}
$('#prev').onclick=()=>{if(index>0){index--;renderViewer()}};
$('#next').onclick=()=>{if(index<pages.length-1){index++;renderViewer()}};
$('#close-viewer').onclick=()=>viewer.close();
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;renderViewer()});
$('#zoom').onclick=()=>{zoom=!zoom;renderViewer()};
viewer.addEventListener('keydown',e=>{if(e.key==='ArrowRight'&&index<pages.length-1){index++;renderViewer()}if(e.key==='ArrowLeft'&&index>0){index--;renderViewer()}});
const demo=$('#demo'),inspector=$('#inspector');
function toggleInspector(open){
 inspector.dataset.open=open;inspector.inert=!open;$('#inspector-toggle').setAttribute('aria-expanded',open);
 if(open)$('#close-inspector').focus({preventScroll:true});else $('#inspector-toggle').focus({preventScroll:true});
}
$('#inspector-toggle').onclick=()=>toggleInspector(inspector.dataset.open!=='true');
$('#close-inspector').onclick=()=>toggleInspector(false);
demo.addEventListener('keydown',e=>{if(e.key==='Escape'&&inspector.dataset.open==='true')toggleInspector(false)});
$('#reduce').onchange=e=>{demo.dataset.reduced=e.target.checked;$('#sample-dialog').style.animation=e.target.checked?'none':''};
$('#dark').onchange=e=>{demo.dataset.dark=e.target.checked};
let timer;
$('#feedback').onclick=()=>{
 clearTimeout(timer);const b=$('#feedback');b.disabled=true;b.textContent='正在演示…';$('#demo-status').textContent='按钮保持位置，使用文字状态反馈。';
 timer=setTimeout(()=>{b.disabled=false;b.textContent='体验按钮反馈';$('#demo-status').textContent='✓ 演示完成 · 没有修改任何项目数据。'},700);
};
$('#reset-demo').onclick=()=>{clearTimeout(timer);toggleInspector(false);$('#reduce').checked=false;$('#dark').checked=false;demo.dataset.dark=false;demo.dataset.reduced=false;$('#sample-dialog').style.animation='';$('#feedback').disabled=false;$('#feedback').textContent='体验按钮反馈';$('#demo-status').textContent='点击按钮，或用 Tab 查看键盘焦点。'};
$('#open-sample').onclick=()=>$('#sample-dialog').showModal();
$('#sample-cancel').onclick=()=>$('#sample-dialog').close();
$('#sample-done').onclick=()=>{$('#sample-dialog').close();$('#demo-status').textContent='✓ 对话框演示完成。'};
renderGrid();

