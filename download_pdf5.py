import requests
import io
import pypdf

session = requests.Session()
res = session.post("http://localhost:5000/rent/login", data={"password": "Zakup1"}, allow_redirects=True)
if "Odjava" not in res.text:
    print("Login failed!")
    exit(1)

res = session.get("http://localhost:5000/rent/contracts/pdf/schedule_fillable/3")
print(f"Status: {res.status_code}")
if res.status_code == 200:
    with open("success.pdf", "wb") as f:
        f.write(res.content)
    print(f"Downloaded {len(res.content)} bytes.")
    try:
        reader = pypdf.PdfReader("success.pdf")
        fields = reader.get_fields()
        if fields:
            print(f"Success! Found {len(fields)} fields.")
        else:
            print("No fields found.")
    except Exception as e:
        print(f"PDF Error: {e}")
else:
    print(f"Failed. Status {res.status_code}, len {len(res.content)}")
    print(res.content.decode('utf-8')[:500])
