@echo off
REM Start offers app (port 5001)

start "" "http://127.0.0.1:5001/offers"
python app.py

pause