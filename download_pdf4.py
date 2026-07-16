import requests
import io
import pypdf

session = requests.Session()
session.post("http://localhost:5000/rent/login", data={"password": "Rent1"}, allow_redirects=True)
res = session.get("http://localhost:5000/rent/contracts/pdf/schedule_fillable/3")

with open("test.pdf", "wb") as f:
    f.write(res.content)
print(f"File size: {len(res.content)}")

try:
    reader = pypdf.PdfReader("test.pdf")
    print(f"Pages: {len(reader.pages)}")
    fields = reader.get_fields()
    print(f"Fields: {len(fields) if fields else 0}")
except Exception as e:
    print(f"PDF Error: {e}")

