"""Visible Markdown text and source-only links; never change stored evidence."""
import re
from functools import lru_cache

@lru_cache(maxsize=8192)
def visible_text(text):
    from markdown_it import MarkdownIt
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(MarkdownIt('commonmark',{'html':True}).render(text),'html.parser')
    for tag in soup(['script','style']):tag.decompose()
    return re.sub(r'\s+',' ',soup.get_text()).strip()

SOURCE_LINK=re.compile(r'(?<!!)\[((?:\\.|[^\[\]\\]|\[(?:\\.|[^\]\\])*\])*)\]\(\s*<?#page-[^\s)>]+>?(?:\s+[\"\'][^\n]*?[\"\'])?\s*\)',re.I)

def strip_source_links(text):
    """Keep the label, not a jump to an anchor belonging to the source PDF."""
    return SOURCE_LINK.sub(lambda m:m[1],text)
