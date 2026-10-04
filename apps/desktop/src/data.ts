export type Page = 'search' | 'overview' | 'library' | 'reader' | 'chat' | 'review' | 'tasks' | 'settings';
export type PaperStatus = 'pdf' | 'indexed' | 'abstract' | 'pending' | 'failed';
export type Paper = { researchManaged?: boolean; corpusSnapshot?: string; id: string; title: string; author: string; year: number; journal: string; tag: string; status: PaperStatus; starred: boolean; abstract: string };
export type Message = { id: string; role: 'user' | 'assistant'; text: string; sources: string[] };
export type Section = { id: string; title: string; content: string };
export type Task = { id: string; paperId: string; title: string; progress: number; state: 'running' | 'done' | 'cancelled' | 'failed' };
export type Project = { archivedPapers?: Paper[]; id: string; name: string; description: string; color: string; papers: Paper[]; messages: Message[]; sections: Section[]; notes: Record<string, string>; tasks: Task[] };
export type AppState = { version: 1; active: string; theme: 'light' | 'dark'; projects: Project[] };

export const statusLabels: Record<PaperStatus, string> = { pdf: '已有 PDF', indexed: '已索引', abstract: '仅摘要', pending: '待处理', failed: '处理失败' };
const summary = '这是一条用于界面演示的合成文献记录，不对应真实发表的论文。示例围绕小胶质细胞、神经炎症与阿尔茨海默病之间的联系组织，用于展示摘要阅读、证据引用与综述工作流。所有作者、期刊归属和研究内容均为占位信息，不能作为学术依据。';
const titles = [
  ['Microglial states and the evolving landscape of Alzheimer’s disease', 'Chen L., Wang Y. et al.', 'Nature Reviews Neuroscience', '小胶质细胞', 'indexed', true, 2025],
  ['TREM2-dependent microglial responses in neurodegeneration', 'Anderson R., Liu M. et al.', 'Cell', 'TREM2', 'indexed', false, 2024],
  ['Single-cell perspectives on neuroinflammation and cognitive decline', 'Zhang H., Miller J. et al.', 'Nature Neuroscience', '单细胞测序', 'indexed', true, 2025],
  ['The complement cascade at the interface of immunity and synaptic loss', 'Williams K., Park S. et al.', 'Science', '突触修剪', 'indexed', false, 2024],
  ['Disease-associated microglia: from molecular signatures to therapeutic targets', 'Li X., Thompson A. et al.', 'Immunity', '小胶质细胞', 'abstract', false, 2023],
  ['Mapping the spatial architecture of the aging human brain', 'Garcia M., Wu J. et al.', 'Nature Aging', '空间转录组', 'indexed', false, 2025],
  ['Lipid metabolism shapes microglial function in the aging brain', 'Kim S., Patel R. et al.', 'Cell Metabolism', '脂质代谢', 'pending', false, 2024],
  ['Neuroimmune interactions across the Alzheimer’s disease continuum', 'Wilson E., Zhao Q. et al.', 'The Lancet Neurology', '神经炎症', 'abstract', false, 2025],
  ['A longitudinal view of inflammatory biomarkers and disease progression', 'Brown D., Sun L. et al.', 'Brain', '生物标志物', 'failed', false, 2023],
  ['Protective and detrimental roles of microglia in amyloid pathology', 'Davis N., Huang Y. et al.', 'Glia', '小胶质细胞', 'indexed', false, 2024],
  ['Beyond amyloid: emerging strategies for targeting neuroinflammation', 'Taylor J., Xu Z. et al.', 'Trends in Neurosciences', '治疗策略', 'indexed', true, 2025],
  ['Integrating multi-omics to understand microglial heterogeneity', 'Martin P., Lin C. et al.', 'Molecular Neurodegeneration', '单细胞测序', 'pending', false, 2024],
] as const;
export const demoPapers: Paper[] = titles.map((p, i) => ({ id: `DEMO-${String(i + 1).padStart(3, '0')}`, title: p[0], author: p[1], journal: p[2], tag: p[3], status: p[4], starred: p[5], year: p[6], abstract: summary }));
export const starterSections: Section[] = [
  { id: 'intro', title: '引言', content: '【演示草稿 · 非学术结论】\n\n理解神经退行性疾病，需要将神经元变化与脑内免疫环境放在同一研究框架中。本节计划从研究背景、现有争议和综述目标三个方面展开。\n\n本文将围绕小胶质细胞的状态变化、相关信号通路与证据局限组织材料。正式写作时，每项事实判断均需关联经过核验的原文片段。\n\n本草稿仅用于体验编辑、保存和导出。示例引用 [DEMO-001] 不对应真实文献。' },
  { id: 'states', title: '小胶质细胞的状态与异质性', content: '' },
  { id: 'trem2', title: 'TREM2 与免疫代谢', content: '' },
  { id: 'synapses', title: '补体通路与突触变化', content: '' },
  { id: 'therapy', title: '治疗策略与转化挑战', content: '' },
  { id: 'outlook', title: '局限性与未来方向', content: '' },
];
export const seedState: AppState = {
  version: 1, active: 'neuro', theme: 'light', projects: [
    { id: 'neuro', name: '小胶质细胞与阿尔茨海默病', description: '探索神经炎症的机制、细胞异质性与潜在治疗方向。', color: 'green', papers: demoPapers, messages: [], sections: starterSections, notes: {}, tasks: [] },
    { id: 'gut', name: '肠道菌群与免疫调节', description: '从文献开始，连接新的研究线索。', color: 'purple', papers: [], messages: [], sections: [{ id: 'intro', title: '引言', content: '' }], notes: {}, tasks: [] },
  ],
};
