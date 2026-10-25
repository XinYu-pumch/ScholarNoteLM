"""Opt-in Go adapter for existing offline workflow fixtures, never live data.

TEST_LLM_PROVIDER=opencode_go copies code into the fixture root and changes only
that copy's manifest to the local mock endpoint and fixture model IDs.
"""
import json,os,re,shutil

ENABLED=os.environ.get('TEST_LLM_PROVIDER')=='opencode_go'
THINKING=os.environ.get('TEST_THINKING_PRESET','')
requests=[]

def setup(app,root,base,models):
    if not ENABLED:return
    assert app.resolve().is_relative_to((root/'tmp').resolve())
    services=app/'services'
    assert services.is_symlink()
    services.unlink();services.mkdir()
    for source in (root/'services').iterdir():
        target=services/source.name
        if source.name in ('downloader','llm_providers'):
            shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__'))
        else:target.symlink_to(source,target_is_directory=source.is_dir())
    path=services/'llm_providers/opencode_go/manifest.json'
    manifest=json.loads(path.read_text());manifest.update(baseUrl=base,models={m:{'protocol':'chat','reasoning':{'options':{'max':{'reasoning_effort':'max'}}}} for m in models})
    path.write_text(json.dumps(manifest))
    import llm_provider
    llm_provider.DIRECTORY=services/'llm_providers';llm_provider._load.cache_clear()

def profile(value):
    if THINKING:
        assert THINKING in ('deepseek_openai','generic_thinking_toggle','qwen_openai','glm_openai')
        level='medium' if THINKING=='qwen_openai' else 'disabled' if THINKING=='generic_thinking_toggle' else 'high'
        output={'output':'summary'} if os.environ.get('TEST_THINKING_OUTPUT')=='summary' else {}
        return {**value,'thinkingByModel':{model:{'preset':THINKING,'level':level,**output} for model in value.get('models',[value['model']])}}
    return {**value,'provider':'opencode_go','reasoningByModel':{model:'max' for model in value.get('models',[value['model']])}} if ENABLED else value

def capture(headers,body):
    requests.append((body,headers.get('x-opencode-session'),headers.get('User-Agent')))

def sessions():return [session for body,session,_ in requests if 'messages' in body]

def verify():
    for body,session,agent in requests:
        if THINKING and 'messages' in body:
            if THINKING=='generic_thinking_toggle':
                assert body.get('thinking')=={'type':'disabled'} and 'reasoning_effort' not in body
            else:
                assert body.get('reasoning_effort')==('medium' if THINKING=='qwen_openai' else 'high'),'Workflow lost its thinking preset'
            if THINKING=='qwen_openai':assert body.get('enable_thinking') is True and 'extra_body' not in body
            if THINKING=='deepseek_openai':
                assert body.get('thinking')=={'type':'enabled'}
                assert 'temperature' not in body
        if ENABLED and 'messages' in body:
            assert re.fullmatch('snlm-[a-f0-9]{64}',session or ''),'Missing Go conversation identity'
            assert agent=='ScholarNoteLM/0.6.0'
            assert body.get('reasoning_effort')=='max','Workflow lost the selected effort'
        else:assert session is None,'Go headers leaked to ordinary LLM/embedding'
