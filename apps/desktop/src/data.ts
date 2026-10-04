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

export const suggestions = ['这些文献有哪些共同的研究主题？', '不同研究对小胶质细胞的作用有何分歧？', '目前的证据还缺少哪些部分？'];

export function demoAnswer(question: string, sources: Paper[]): string {
  if (!sources.length) return '当前范围中没有可用的文献。请先添加文献，或调整来源范围后再试。\n\n这是原型的空证据状态演示，未调用模型。';
  if (/缺少|不足|局限|疗效|剂量|临床|有效/.test(question)) return `关于「${question}」\n\n当前资料不足以形成可靠结论。示例文献仅用于界面展示，无法提供真实的实验结果、样本量或临床证据。\n\n正式研究中，建议检查：\n• 是否覆盖不同研究模型与疾病阶段；\n• 是否包含独立验证与纵向研究；\n• 原始研究与综述的证据是否被区分。\n\n你可以点击右侧来源查看证据面板。这是预设的“证据不足”演示，未调用模型。`;
  if (/分歧|冲突|不同|矛盾/.test(question)) return `关于「${question}」\n\n这个示例展示如何呈现相互冲突的证据。判断研究结论是否矛盾，需要先核对研究对象、时间窗口、实验方法与结局指标。\n\n01  比较研究条件\n将不同疾病阶段、细胞状态与样本来源分别整理，避免直接合并。\n\n02  并列展示证据\n保留各自的原文片段与适用范围，而不是用单一结论覆盖差异。\n\n03  标记尚未解决的问题\n如果证据无法比较，应明确说明局限。\n\n这是预设回答；示例来源不构成真实的冲突证据。`;
  return `关于「${question}」\n\n已在当前范围内选择 ${sources.length} 篇示例文献。这个原型演示从研究问题到来源证据的阅读路径，尚未进行真实检索或模型推理。\n\n01  细胞状态与异质性\n可以围绕细胞状态、研究模型与分析方法组织第一组阅读笔记。\n\n02  免疫信号与代谢\n将 TREM2、补体与代谢相关主题分组，便于后续比较研究结果。\n\n03  转化方向与证据缺口\n为每个主题保留限制条件，以及需要进一步寻找的文献。\n\n以上是基于示例主题的预设展示，不是文献支持的科学结论。点击下方引用可以体验来源追溯。`;
}
