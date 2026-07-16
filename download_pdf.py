import requests
session = requests.Session()
# Login
login_data = {"password": "Rent1"}
session.post("http://localhost:5000/rent/login", data=login_data)
# Download PDF
response = session.get("http://localhost:5000/rent/contracts/pdf/schedule_fillable/3")
with open("test_fillable.pdf", "wb") as f:
    f.write(response.content)
print(f"Downloaded {len(response.content)} bytes")
