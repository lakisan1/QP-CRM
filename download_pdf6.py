import requests
session = requests.Session()
session.post("http://localhost:5000/rent/login", data={"password": "Zakup1"}, allow_redirects=True)
res = session.get("http://localhost:5000/rent/contracts/pdf/schedule_fillable/3")
print("Headers:")
for k, v in res.headers.items():
    if k.lower() == 'content-disposition':
        print(f"{k}: {repr(v)}")
