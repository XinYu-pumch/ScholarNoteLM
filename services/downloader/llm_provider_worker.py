"""Private NDJSON pipe for Rust's optional providers; no HTTP bridge/server.

Credentials arrive on stdin, never argv, environment or disk. stdout contains
only deltas/final status. The parent kills this process on cancellation.
"""
import asyncio,json,sys
import llm_provider,review_llm

def emit(value):
    print(json.dumps(value,ensure_ascii=False),flush=True)

async def run(data):
    profile=data['profile']
    if llm_provider.adapter(profile) is None:raise ValueError('此进程仅供已注册的可选供应商使用')
    profile={**profile,'endpoint':llm_provider.endpoint(profile,review_llm.endpoint)}
    profile=llm_provider.with_session(profile,'search',*data['session'])
    previous={'text':'','reasoning':''}
    def output(kind,value):
        delta=value[len(previous[kind]):];previous[kind]=value
        if delta:emit({'type':'delta',kind:delta})
    await review_llm.chat(profile,data['messages'],lambda:False,on_text=lambda v:output('text',v),on_reasoning=lambda v:output('reasoning',v))
    emit({'type':'done'})

if __name__=='__main__':
    try:asyncio.run(run(json.load(sys.stdin)))
    except BrokenPipeError:pass
    except Exception as exc:
        emit({'type':'error','error':str(exc) if isinstance(exc,ValueError) else '模型供应商进程失败，请检查服务与运行时'})
        sys.exit(1)
