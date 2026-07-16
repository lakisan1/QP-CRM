import fitz
import re

doc = fitz.open("success.pdf")
page = doc[0]

rows = []
for block in page.get_text("dict")["blocks"]:
    if "lines" in block:
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if re.match(r"^(0\.\d+|\d+)$", text) and span["bbox"][0] < 50:
                    rows.append((text, span["bbox"][1])) # y0

rows.sort(key=lambda x: x[1])
for r in rows:
    print(r)

print("Page 2:")
page2 = doc[1]
rows2 = []
for block in page2.get_text("dict")["blocks"]:
    if "lines" in block:
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if re.match(r"^(0\.\d+|\d+)$", text) and span["bbox"][0] < 50:
                    rows2.append((text, span["bbox"][1]))

rows2.sort(key=lambda x: x[1])
for r in rows2[:5]:
    print(r)
