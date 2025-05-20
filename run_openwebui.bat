@echo off
echo ===================================================
echo  Starting MiView with OpenWebUI
echo ===================================================

echo.
echo [1/2] Starting FastAPI backend (port 8080)...
start cmd /k "title MiView Backend && cd backend && uvicorn main:app --host 0.0.0.0 --port 8080 --log-level warning"

echo.
echo [2/2] Starting OpenWebUI frontend (port 8000)...
echo.
echo When finished, close all terminal windows.
echo.
echo ===================================================
python -m miview_openwebui 