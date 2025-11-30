@echo off
REM Start offers app (port 5000)

start "" "http://127.0.0.1:5000/products"
python app.py

pause
