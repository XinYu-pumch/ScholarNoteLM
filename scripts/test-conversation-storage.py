"""Exercise real Rust conversation RPC, in a disposable project without models."""
import fcntl,json,os,sqlite3,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='conversations-',dir=ROOT/'tmp') as tmp:
 def rpc(action,**args):
  result=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':action,'args':{'project':'fixture',**args}}),capture_output=True,text=True,env={**os.environ,'SCHOLARNOTELM_ROOT':tmp})
  value=json.loads(result.stdout)
  if not value['ok']:raise ValueError(value['error'])
  return value['data']
 def rejected(action,**args):
  try:rpc(action,**args)
  except ValueError:return
  raise AssertionError('Expected rejection: '+action)
 first=rpc('chat.new',name='Original');second=rpc('chat.new',name='Untouched')
 db=next(Path(tmp).rglob('research.sqlite3'))
 history=[{'role':'user','text':'Question','created':1},{'role':'assistant','text':'Answer','created':2,'result':{'queries':[{'id':'q','text':'test[Title/Abstract]'}]}}]
 with sqlite3.connect(db) as c:c.execute('UPDATE chat_threads SET data=? WHERE id=?',(json.dumps(history),first['id']))
 copied=rpc('chat.copy',id=first['id']);assert copied['messages']==history and copied['id']!=first['id']
 rpc('chat.rename',id=copied['id'],name='Independent copy');assert rpc('chat.get',id=first['id'])['name']=='Original'
 rejected('chat.copy',project='another-project',id=first['id'])
 rejected('chat.archive_many',ids=[first['id'],'missing'])
 rejected('chat.archive_many',ids=[])
 assert len(rpc('chat.list'))==3
 with (Path(tmp)/'data/research'/f"chat-{first['id']}.lock").open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  rejected('chat.copy',id=first['id'])
  rejected('chat.archive',id=first['id'])
  rejected('chat.archive_many',ids=[second['id'],first['id']])
  assert len(rpc('chat.list'))==3
 rpc('chat.archive_many',ids=[first['id'],first['id'],second['id']])
 assert [t['id'] for t in rpc('chat.list')]==[copied['id']]
 assert rpc('chat.get',id=copied['id'])['messages']==history
 rejected('chat.get',id=first['id'])
 print('PASS: copy content, independent rename, project scope, bulk prevalidation, active stream lock, duplicate IDs, preserved copy after deletion')
