"""Original paragraph positions and complete article-citation recognition."""
import html
import re

PARAGRAPH_VERSION = 'original-spans-fenced-code-v1'

def normalize(text):
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    for _ in range(2):
        text = re.sub(r'\[([^\[\]]*)\]\((?:[^()\n]|\([^()\n]*\))*\)', r'\1', text)
    text = re.sub(r'[*_`\\]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\s+([),.;])', r'\1', text)
    return re.sub(r'([(])\s+', r'\1', text)

AUTHOR = r"(?:[A-ZÀ-ÖØ-Þ][A-Za-zÀ-öø-ÿ’'\-]+,?\s+(?:(?:[A-Z]\.){1,4}|[A-Z]{1,4}(?:-[A-Z]{1,3})?\.?)|(?:[A-Z]\.\s*){1,3}[A-Z][a-z’'\-]+)(?=\s*[,;&]|\s+and\b|\s*\((?:19|20)\d{2}|\s+(?:19|20)\d{2}|\.\s|$)"
START_AUTHOR = re.compile(r'^(?:\[?\d{1,4}\]?[.)]?\s*)?' + AUTHOR)
YEAR = re.compile(r'\b(?:19|20)\d{2}[a-z]?\b')
# Require an actual bibliographic ending. A DOI mentioned in running prose is insufficient.
END_LOCATOR = re.compile(r'(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)?10\.\d{4,9}/[^\s]+[.]?$|\b\d{1,4}(?:\s*\(\d{1,3}\))?\s*[:,]\s*[eE]?\d+(?:\s*[–−-]\s*\d+)?(?:\s*\((?:19|20)\d{2}\))?\.?$|\b\d{1,4}\s*,\s*\d+\s*[–−-]\s*\d+\s*\((?:19|20)\d{2}\)\.?$', re.I)
# These catch mixed paragraphs / annotated bibliographies; ordinary scientific words in titles are allowed.
MIXED = re.compile(r'\b(?:we (?:found|show|demonstrat|observ|used|measured)|our (?:results|study|data)|this (?:study|work|paper) (?:show|demonstrat|reveal|report)|a landmark study|these (?:results|findings)|figure\s*\d|fig\.\s*\d|table\s*\d|(?:p|n)\s*[=<])', re.I)

def classify(raw, section_path=(), source_kind='fulltext'):
    """None means KEEP, including uncertainty. Rules inspect the entire parent paragraph."""
    if source_kind != 'fulltext':
        return None
    t = normalize(raw)
    if not t or raw.lstrip().startswith(('#', '```', '~~~')):
        return None
    # Do not strip a heading/figure/code/math out of a mixed paragraph to make it match.
    if re.search(r'(^|\n)\s*#{1,6}\s|!\[|```|~~~|\$\$|\\(?:begin|frac)\b', raw):
        return None
    if raw.lstrip().startswith('|') or '<table' in raw.lower():return None
    if MIXED.search(t):
        return None
    if 80 <= len(t) <= 1600 and START_AUTHOR.match(t) and len(re.findall(AUTHOR, t)) >= 2 and YEAR.search(t):
        end = END_LOCATOR.search(t)
        if end and end.start() > 40 and not re.search(r'\b(?:Abstract|Methods|Results|Conclusion|Supplementary)\s*:', t, re.I):
            return 'C01_complete_bibliographic_entry'
    return None

def code_spans(text):
    """Protect whole fenced blocks, including blank lines and unclosed fences.

    A shorter fence or a fence of the other kind cannot close the block.
    Accept indentation/blockquote prefixes conservatively (overprotection is OK).
    """
    spans=[];opened=None;offset=0
    for line in text.splitlines(keepends=True):
        match=re.match(r'^[ \t]*(?:>[ \t]*)*(`{3,}|~{3,})([^\r\n]*)',line)
        if match:
            fence,tail=match.groups()
            if opened is None:opened=(offset,fence[0],len(fence))
            elif fence[0]==opened[1] and len(fence)>=opened[2] and not tail.strip():
                spans.append((opened[0],offset+len(line)));opened=None
        offset+=len(line)
    if opened is not None:spans.append((opened[0],len(text)))
    return spans


def paragraphs(text):
    """Original, unsplit paragraphs and original heading context.

    Offsets are Python Unicode character offsets, end exclusive; lines are
    one-based. No normalization or deletion is used to derive these positions.
    """
    import bisect
    code=code_spans(text);code_ends=[end for _,end in code]
    newlines=[m.start() for m in re.finditer('\n',text)]
    spans=[];start=0;section=[];index=0
    for match in re.finditer(r'\n\s*\n',text):
        spans.append((start,match.start()));start=match.end()
    spans.append((start,len(text)))
    for start,end in spans:
        raw=text[start:end]
        if not raw.strip():continue
        index+=1;ci=bisect.bisect_right(code_ends,start)
        fenced=ci<len(code) and code[ci][0]<end
        if not fenced:
            heading=re.match(r'^(#{1,6})\s+(.+)',raw.strip())
            if heading:
                level=len(heading[1]);section=[s for s in section if s[0]<level]+[(level,heading[2].strip())]
        yield {'text':raw,'charStart':start,'charEnd':end,
               'lineStart':bisect.bisect_left(newlines,start)+1,
               'lineEnd':bisect.bisect_left(newlines,max(start,end-1))+1,
               'paragraphIndex':index,'sectionPath':[s[1] for s in section],
               'codeProtected':fenced}


