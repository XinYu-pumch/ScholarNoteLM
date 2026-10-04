"""Small deterministic PDFs with an actual text layer, no external tooling."""
import io
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

def pdf(text='10.1/example', *, blank=False):
    writer=PdfWriter();page=writer.add_blank_page(width=100,height=100)
    if not blank:
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        text=text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
        content=DecodedStreamObject();content.set_data(('BT /F1 12 Tf 10 50 Td ('+text+') Tj ET').encode('ascii','replace'))
        page[NameObject('/Contents')]=writer._add_object(content)
    out=io.BytesIO();writer.write(out);return out.getvalue()
