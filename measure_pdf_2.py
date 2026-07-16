import fitz

doc = fitz.open("success.pdf")
page = doc[0]

text_instances = page.search_for("Uplaćen")
for inst in text_instances:
    print(f"Uplacen: {inst}")

text_instances = page.search_for("iznos")
for inst in text_instances:
    print(f"iznos: {inst}")

text_instances = page.search_for("Datum uplate")
for inst in text_instances:
    print(f"Datum uplate: {inst}")
    
text_instances = page.search_for("uplate")
for inst in text_instances:
    print(f"uplate: {inst}")
