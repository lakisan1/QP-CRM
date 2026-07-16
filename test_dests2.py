from weasyprint import HTML
import io
import pypdf

html = '<html><body><h1 id="row_0">Hello</h1><div style="height: 1000px"></div><p id="row_1">Para</p></body></html>'
pdf_bytes = HTML(string=html).write_pdf()

reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
dests = reader.named_destinations

for key, dest in dests.items():
    page_ref = dest['/Page']
    page_idx = reader.pages.index(page_ref)
    print(f"Key: {key}, Page: {page_idx}, Top: {dest['/Top']}")
