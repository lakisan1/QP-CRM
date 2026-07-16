import fitz # PyMuPDF
import sys

doc = fitz.open("success.pdf")
page = doc[0]

# Find the text "0.1" (the first row number)
text_instances = page.search_for("0.1")
if text_instances:
    print(f"Row 0.1 rect: {text_instances[0]}")
    y_from_top = text_instances[0].y0
    print(f"y_from_top: {y_from_top}")
else:
    print("Row 0.1 not found")

# Find the column headers to measure X positions
iznos = page.search_for("Uplaćen")
if iznos:
    print(f"Uplacen iznos rect: {iznos[0]}")
datum = page.search_for("Datum")
if datum:
    print(f"Datum rect: {datum[0]}")
    
# Find the next row "0.2" to measure row height
text2 = page.search_for("0.2")
if text2:
    print(f"Row 0.2 rect: {text2[0]}")
    print(f"Row height: {text2[0].y0 - text_instances[0].y0}")
