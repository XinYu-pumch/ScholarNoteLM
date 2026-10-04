import { seedState, type AppState } from './data';
import {rpc} from './research-api';

let loading:Promise<AppState>|undefined;
export function readState(): Promise<AppState> {
  return loading ??= loadState().catch(e=>{loading=undefined;throw e;});
}
async function loadState(): Promise<AppState> {
  await rpc('storage.initialize');
  let state=await rpc<AppState|null>('storage.state.read');
  if(!state){
    state=structuredClone(seedState);
    for(const project of state.projects) await rpc('storage.register',{project:project.id,folder:project.id.replace(/[^A-Za-z0-9]/g,''),data:project});
  }
  if (state.version !== 1 || !Array.isArray(state.projects) || (state.projects.length ? !state.projects.some(p => p.id === state.active) : state.active !== '')) throw new Error('保存的项目数据格式不兼容');
  return state;
}
export async function writeState(state: AppState): Promise<void> {
  await rpc('storage.state.write',{state});
}
