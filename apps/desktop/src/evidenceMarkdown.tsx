import type {Components} from 'react-markdown';

// Source PDF anchors do not exist in app previews. Preserve their labels.
export const evidenceMarkdownComponents:Components={
 img:()=>null,
 a:({href,children,title})=>href?.toLowerCase().startsWith('#page-')
  ?<>{children}</>
  :<a href={href} title={title}>{children}</a>,
};
