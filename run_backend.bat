@echo off
echo Starting FastAPI backend...
cd backend
uvicorn main:app --host 0.0.0.0 --port 8080 --reload-delay 2 --log-level info 