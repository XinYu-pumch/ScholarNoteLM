export type Page = 'search' | 'overview' | 'library' | 'reader' | 'chat' | 'review' | 'tasks' | 'settings';
export type PaperStatus = 'pdf' | 'indexed' | 'abstract' | 'pending' | 'failed';
export type Paper = { researchManaged?: boolean; corpusSnapshot?: string; id: string; title: string; author: string; year: number; journal: string; tag: string; status: PaperStatus; starred: boolean; abstract: string };
export type Message = { id: string; role: 'user' | 'assistant'; text: string; sources: string[] };
export type Section = { id: string; title: string; content: string };
export type Task = { id: string; paperId: string; title: string; progress: number; state: 'running' | 'done' | 'cancelled' | 'failed' };
export type Project = { archivedPapers?: Paper[]; id: string; name: string; description: string; color: string; papers: Paper[]; messages: Message[]; sections: Section[]; notes: Record<string, string>; tasks: Task[] };
export type AppState = { version: 1; active: string; theme: 'light' | 'dark'; projects: Project[] };

export const statusLabels: Record<PaperStatus, string> = { pdf: '已有 PDF', indexed: '已索引', abstract: '仅摘要', pending: '待处理', failed: '处理失败' };
export const emptyState: AppState = { version: 1, active: '', theme: 'light', projects: [] };
