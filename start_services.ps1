# PowerShell script to start both MiView-Lite services

# Define port numbers for each service
$CHAINLIT_PORT = 8000
$FASTAPI_PORT = 8080

Write-Host "Starting MiView-Lite services..." -ForegroundColor Cyan

# Start FastAPI in a new PowerShell window
Write-Host "Starting FastAPI on port $FASTAPI_PORT..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend'; uvicorn main:app --reload --port $FASTAPI_PORT"

# Wait a moment
Start-Sleep -Seconds 2

# Start Chainlit in the current window
Write-Host "Starting Chainlit on port $CHAINLIT_PORT..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop Chainlit" -ForegroundColor Yellow
cd $PSScriptRoot
chainlit run app.py --port $CHAINLIT_PORT

Write-Host "Services stopped." -ForegroundColor Red 