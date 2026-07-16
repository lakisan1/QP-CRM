import fitz

doc = fitz.open("success.pdf")
if len(doc) > 1:
    page2 = doc[1]
    
    # search for "25", the first row on page 2 (as seen in the screenshot)
    text25 = page2.search_for("25")
    if text25:
        print(f"Row 25 rect: {text25[0]}")
    else:
        print("Row 25 not found")
        # try 24 or 26
        for i in range(20, 30):
            t = page2.search_for(str(i))
            if t:
                print(f"Row {i} rect: {t[0]}")
                break
