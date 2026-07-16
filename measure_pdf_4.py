import fitz

doc = fitz.open("success.pdf")
page = doc[0]

t1 = page.search_for("1")
t2 = page.search_for("2")
# filter out non-R.Br instances
t1_row = [t for t in t1 if t.x0 < 50]
t2_row = [t for t in t2 if t.x0 < 50]

if t1_row and t2_row:
    print(f"Row 1: {t1_row[0]}")
    print(f"Row 2: {t2_row[0]}")
    print(f"Row 1 height: {t2_row[0].y0 - t1_row[0].y0}")
