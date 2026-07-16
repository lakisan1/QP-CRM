from weasyprint import HTML
import io
import pypdf

html = '<html><body><h1 id="myheader">Hello</h1><div style="height: 500px"></div><p id="mypara">Para</p></body></html>'
pdf_bytes = HTML(string=html).write_pdf()

reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
print(reader.named_destinations)
