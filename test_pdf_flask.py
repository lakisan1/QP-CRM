import io
import pypdf
from main import app

with app.test_client() as client:
    # Use session transaction to bypass login
    with client.session_transaction() as sess:
        sess['rent_authenticated'] = True

    response = client.get('/rent/contracts/pdf/schedule_fillable/3')
    
    if response.status_code == 200:
        with open("test_fillable_output.pdf", "wb") as f:
            f.write(response.data)
        print("Success! File saved.")
        
        # Verify if it has form fields
        reader = pypdf.PdfReader("test_fillable_output.pdf")
        fields = reader.get_fields()
        if fields:
            print(f"Found {len(fields)} fields.")
        else:
            print("No fields found.")
    else:
        print(f"Failed with status: {response.status_code}")
        print(response.data.decode('utf-8')[:200])
