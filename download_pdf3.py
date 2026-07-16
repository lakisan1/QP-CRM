import requests
import io

session = requests.Session()
res = session.post("http://localhost:5000/rent/login", data={"password": "Rent1"}, allow_redirects=True)
print(f"Login URL ended up at: {res.url}")
res = session.get("http://localhost:5000/rent/contracts/pdf/schedule_fillable/3", allow_redirects=True)
print(f"PDF URL ended up at: {res.url}")
print(f"Content-Type: {res.headers.get('Content-Type')}")
print(f"Length: {len(res.content)}")
