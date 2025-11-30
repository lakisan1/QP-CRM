@echo off
REM Run pricing_app and quotation_app from the Custom folder

set "BASE_DIR=%~dp0"

echo Starting pricing_app (port 5000)...
pushd "%BASE_DIR%pricing_app"
start "" python app.py
popd

echo Starting quotation_app (port 5001)...
pushd "%BASE_DIR%quotation_app"
start "" python app.py
popd

echo Both apps started.
exit
