"""Direct PubMed record paths, including Bookshelf chapters; never cited IDs."""

def records(root):
    for node in root:
        if node.tag=='PubmedArticle':
            citation=node.find('MedlineCitation')
            if citation is not None:yield node,citation,citation.find('Article'),node.find('PubmedData')
        elif node.tag=='PubmedBookArticle':
            citation=node.find('BookDocument')
            if citation is not None:yield node,citation,citation,node.find('PubmedBookData')

def ids(node,citation,data):
    # Metadata IDs take precedence, with a chapter-level fallback. No .// search:
    # ReferenceList and the parent Book contain unrelated document identifiers.
    values=list(data.findall('ArticleIdList/ArticleId')) if data is not None else []
    if node.tag=='PubmedBookArticle':values+=list(citation.findall('ArticleIdList/ArticleId'))
    return values

def doi_elements(node,citation,article,data):
    return ids(node,citation,data)+(list(article.findall('ELocationID')) if article is not None else [])
