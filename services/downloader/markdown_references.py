"""Structural bibliography filter, promoted from the frozen corpus experiment.
No model calls or document-specific rules. The optional article-citation fallback
reuses the existing complete-entry validator only after an explicit local label.

Markdown syntax is parsed by markdown-it-py. Bibliographic features only support
document-local heading/number-sequence evidence; they never delete globally.
Source spans use 0-based, end-exclusive Unicode offsets and line positions.
"""
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
import unicodedata
from markdown_it import MarkdownIt

VERSION = 'structural-references-v1'
MD = MarkdownIt('commonmark', {'html': True}).enable('table')
LABELS = {'references', 'reference', 'bibliography', 'referencias', '参考文献', 'literaturecited', 'referencesandnotes'}

class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]
    def handle_data(self, data): self.parts.append(data)
    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'p', 'li'): self.parts.append(' ')
    def handle_endtag(self, tag):
        if tag in ('p', 'li'): self.parts.append(' ')

def visible(markdown):
    p=Visible(); p.feed(MD.renderInline(markdown)); return ' '.join(''.join(p.parts).split())

def label(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text).casefold() if c.isalpha())

def prefix(text):
    """Read a leading bibliography ordinal; do not search numbers in prose."""
    s=text.lstrip()
    while s.startswith(('- ', '* ', '+ ', '#', '>')): s=s[1:].lstrip()
    s=visible(s)
    if s.startswith('['): s=s[1:]
    n=0
    while n<len(s) and s[n].isascii() and s[n].isdigit(): n+=1
    if not n or n>3 or n==len(s) or s[n] not in ' .)]': return None,s
    num=int(s[:n]); tail=s[n:].lstrip(' .)]')
    return (num if num else None),tail

def digit_runs(text):
    runs=[]; start=None
    for i,c in enumerate(text+' '):
        if c.isascii() and c.isdigit():
            if start is None:start=i
        elif start is not None:
            runs.append((start,i,text[start:i]));start=None
    return runs

def features(text):
    """Small, interpretable supporting signals, not journal-specific templates."""
    runs=digit_runs(text)
    year=any(len(s)==4 and 1800<=int(s)<=2099 for _,_,s in runs)
    numeric_locator=any(text[a[1]:b[0]].strip(' ()[]') in (':','-','–','−') for a,b in zip(runs,runs[1:]))
    locator=('doi.org/' in text.casefold() or 'doi:' in text.casefold() or numeric_locator)
    words=text.replace(',', ' ').replace(';',' ').split()
    first=words[:5]
    initials=sum(bool(w.strip('.-')) and len(w.strip('.-'))<=4 and
                 all(c.isupper() or c in '.-' for c in w) for w in first)
    prose_start={'the','this','we','our','in','for','these','a','an','copyright','received','downloaded','how','published','table','figure','fig','citation'}
    author=initials>=1 and bool(first) and first[0][0].isupper() and first[0].casefold().strip(':') not in prose_start and ':' not in first[0]
    short_locator=(len(text)<300 and numeric_locator and bool(text.rstrip(' .;)')) and text.rstrip(' .;)')[-1].isdigit())
    prose_lead=bool(first) and first[0].casefold().strip(':') in prose_start
    protected_lead=bool(first) and first[0].casefold().strip(':') in {'copyright','received','downloaded','how','published','table','figure','fig','citation'}
    return {'year':year,'locator':locator,'shortLocator':short_locator,'author':author,'initials':initials,'proseLead':prose_lead,'protectedLead':protected_lead,
            'bibliographic':year and (author or locator),
            'strong':year and author and locator}

@dataclass
class Block:
    start:int
    end:int
    kind:str
    text:str
    ordinal:int|None
    body:str
    facts:dict
    list_item:bool=False

def parse(text):
    lines=text.splitlines(keepends=True); tokens=MD.parse(text); blocks=[]
    protected=[]; table_until=-1; stack=[]
    for i,t in enumerate(tokens):
        if t.type=='table_open':
            protected.append(tuple(t.map));table_until=t.map[1]
        if t.type in ('fence','code_block','html_block') and t.map:
            protected.append(tuple(t.map))
        if t.nesting==-1:
            if stack:stack.pop()
            continue
        if t.type in ('paragraph_open','heading_open') and t.map and t.map[0]>=table_until:
            inline=tokens[i+1]
            raw=''.join(lines[t.map[0]:t.map[1]])
            plain=visible(inline.content)
            ordinal,body=prefix(raw.splitlines()[0])
            # Analyze the whole inline content after removing its leading ordinal.
            _,body=prefix(raw)
            kind='heading' if t.type=='heading_open' else 'paragraph'
            if any(c.type=='image' for c in inline.children or []):kind='image'
            blocks.append(Block(t.map[0],t.map[1],kind,plain,ordinal,body,features(body),
                                any(s.type=='list_item_open' for s in stack)))
        if t.nesting==1:stack.append(t)
    return lines,blocks,protected

def analyze(text,*,article_citations=False):
    lines,blocks,protected=parse(text)
    headings=[i for i,b in enumerate(blocks) if label(b.text) in LABELS and len(b.text)<60]
    selected={};warnings=[]
    # Numbered bibliography runs: a heading is helpful but not mandatory.
    numbered=[i for i,b in enumerate(blocks) if b.ordinal is not None and b.kind not in ('image',)]
    runs=[]; run=[]
    for i in numbered:
        b=blocks[i]
        if run:
            prev=blocks[run[-1]]
            gap=b.start-prev.end
            if not (0<b.ordinal-prev.ordinal<=6 and gap<=45):
                runs.append(run);run=[]
        run.append(i)
    if run:runs.append(run)
    for run in runs:
        first=blocks[run[0]]
        anchors=[h for h in headings if 0<=first.start-blocks[h].end<=12]
        count=sum(blocks[i].facts['bibliographic'] for i in run)
        strong=sum(blocks[i].facts['strong'] for i in run)
        valid=(len(run)>=2 and count>=2 and count/len(run)>=.3 and bool(anchors)) or (
            len(run)>=4 and count/len(run)>=.7 and strong>=2 and first.start>=len(lines)*.35)
        if valid:
            for i in run:
                b=blocks[i]
                # Numbering plus a validated run can include undated URLs/incomplete entries.
                if b.kind=='heading' and not b.facts['bibliographic']:
                    warnings.append({'line':b.start+1,'reason':'numbered_heading_in_run'});continue
                selected[i]='numbered_sequence'
            for h in anchors:selected[h]='reference_heading'
    # Unnumbered bibliographies: heading + author/year signals across nearby blocks.
    for h in headings:
        end=len(blocks)
        region=[j for j in range(h+1,end) if blocks[j].kind=='paragraph']
        candidates=[j for j in region if blocks[j].facts['bibliographic'] and blocks[j].facts['author']]
        if len(candidates)>=2:
            selected[h]='reference_heading'
            for j in candidates:selected.setdefault(j,'heading_and_bibliography')
        if h not in selected:warnings.append({'line':blocks[h].start+1,'reason':'unresolved_reference_heading'})
    # Continue only bibliographic-looking fragments near an established bibliography.
    # Normal headings, tables, images and substantive unnumbered prose are not swept up.
    for _ in range(len(blocks)):
        additions={}
        for i,b in enumerate(blocks):
            if i in selected or b.kind=='image':continue
            if b.kind=='heading' and not (b.text[:1].isdigit() and not any(c.isalpha() for c in b.text)):continue
            if b.facts['proseLead']:continue
            preceding=[j for j in selected if selected[j]!='reference_heading' and 0<=b.start-blocks[j].end<=12]
            following=[j for j in selected if selected[j]!='reference_heading' and 0<=blocks[j].start-b.end<=4]
            near=preceding or following
            if not near:continue
            # A citation ending carries both a publication year and a locator.
            if b.kind=='paragraph' and b.facts['year'] and b.facts['locator'] and (
                b.body[:1].islower() or b.list_item or
                (i-1 in selected and i+1 in selected)):
                additions[i]='bibliographic_continuation';continue
            # Split authors or journal/volume/page fragments require immediate neighbours.
            left=i-1 in selected and selected[i-1]!='reference_heading'
            right=i+1 in selected and selected[i+1]!='reference_heading'
            incomplete=left and not blocks[i-1].text.endswith(('.',')'))
            if (left or right) and (b.facts['shortLocator'] and len(b.text)<300 or
                                   b.facts['author'] and len(b.text)<350 and b.text.endswith(',')):
                additions[i]='adjacent_citation_fragment';continue
            if incomplete and right and len(b.text)<160 and b.body[:1].islower():
                additions[i]='split_citation_bridge'
            if left and right and b.list_item and b.facts['author']:
                additions[i]='split_author_list'
            if (left or right) and b.facts['year'] and b.facts['locator'] and not b.facts['proseLead'] and len(b.text)<1200:
                additions[i]='adjacent_bibliography'
        if not additions:break
        selected.update(additions)
    # A dense contiguous list is a structural object, even when the PDF converter
    # has made each wrapped citation line a separate list item.
    groups=[];group=[]
    for i,b in enumerate(blocks):
        if not b.list_item or b.kind!='paragraph' or (group and b.start-blocks[group[-1]].end>2):
            if group:groups.append(group);group=[]
        if b.list_item and b.kind=='paragraph':group.append(i)
    if group:groups.append(group)
    for group in groups:
        if len(group)>=4 and sum(i in selected for i in group)/len(group)>=.7:
            for i in group:
                if not blocks[i].facts['protectedLead']:selected.setdefault(i,'dense_bibliography_list')
    if article_citations:
        # Preserve the previously validated own-article citation fallback, without
        # invoking any metadata, footer, length or other non-reference filters.
        from markdown_cleaning import paragraphs,classify
        offsets=[0]
        for line in lines:offsets.append(offsets[-1]+len(line))
        entries=[p for p in paragraphs(text) if not p['codeProtected'] and classify(p['text'],p['sectionPath'])=='C01_complete_bibliographic_entry']
        for i,b in enumerate(blocks[:-1]):
            if label(b.text) not in {'citation','howtocitethisarticle','citethisarticle','tocitethisarticle'}:continue
            nxt=blocks[i+1]
            if nxt.start-b.end<=3 and any(offsets[nxt.start]<=p['charStart']<p['charEnd']<=offsets[nxt.end] for p in entries):
                selected.setdefault(i,'explicit_article_citation_label')
                selected.setdefault(i+1,'complete_article_citation')
    # Isolated continuation fragments are proposed for review, never assumed deleted.
    for i,b in enumerate(blocks):
        if i in selected or b.kind=='image':continue
        near=any(0<=abs(b.start-blocks[j].end)<=4 for j in selected if selected[j]!='reference_heading')
        if near and (b.facts['bibliographic'] or (len(b.text)<240 and any(c.isdigit() for c in b.text))):
            warnings.append({'line':b.start+1,'reason':'possible_continuation','text':b.text[:180]})
    spans=[]
    offsets=[0]
    for line in lines:offsets.append(offsets[-1]+len(line))
    for i,reason in sorted(selected.items()):
        b=blocks[i]
        if any(b.start<end and start<b.end for start,end in protected):
            warnings.append({'line':b.start+1,'reason':'protected_overlap'});continue
        spans.append({'lineStart':b.start+1,'lineEnd':b.end,'charStart':offsets[b.start],
                      'charEnd':offsets[b.end],'reason':reason,'ordinal':b.ordinal})
    # Non-overlapping source slices; retained bytes/characters are never regenerated.
    cursor=0;out=[]
    for s in spans:
        assert s['charStart']>=cursor
        out.append(text[cursor:s['charStart']]);cursor=s['charEnd']
    out.append(text[cursor:])
    return ''.join(out),{'version':VERSION+('+article-citation-v1' if article_citations else ''),'removed':spans,'warnings':warnings,
                        'blocks':[asdict(b) for b in blocks], 'protected':protected}
