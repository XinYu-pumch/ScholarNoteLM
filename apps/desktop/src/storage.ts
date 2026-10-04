import { emptyState, type AppState } from './data';
import {rpc} from './research-api';

let loading:Promise<AppState>|undefined;
export function readState(): Promise<AppState> {
  return loading ??= loadState().catch(e=>{loading=undefined;throw e;});
}
async function loadState(): Promise<AppState> {
  await rpc('storage.initialize');
  // A fresh install starts without projects; the app shows the create-project screen.
  const state=await rpc<AppState|null>('storage.state.read')??structuredClone(emptyState);
  if (state.version !== 1 || !Array.isArray(state.projects) || (state.projects.length ? !state.projects.some(p => p.id === state.active) : state.active !== '')) throw new Error('保存的项目数据格式不兼容');
  return state;
}
export async function writeState(state: AppState): Promise<void> {
  await rpc('storage.state.write',{state});
}
