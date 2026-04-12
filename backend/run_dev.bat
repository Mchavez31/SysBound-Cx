@echo off
cd /d "%~dp0"
echo Starting API at http://127.0.0.1:8020  (Ctrl+C to stop)
echo If you see "address already in use", run: netstat -ano ^| findstr :8020
REM Omit --reload to avoid Windows issue: connection opens but HTTP never responds.
python -m uvicorn main:app --host 127.0.0.1 --port 8020
pause
