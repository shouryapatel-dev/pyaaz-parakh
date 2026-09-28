@echo off
REM Starts the Pyaaz Parakh server. Open the printed http://<your-ip>:8000 on your phone (same Wi-Fi).
cd /d "%~dp0"
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo Phone link: http:%%a:8000 | findstr /v "169.254"
.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
