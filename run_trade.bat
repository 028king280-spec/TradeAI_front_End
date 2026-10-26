@echo off
echo Starting AIvolve Trading AI Backend and Frontend...

start "AIvolve Trade - Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

start "AIvolve Trade - Frontend" cmd /k "cd /d %~dp0 && npm.cmd run dev"

echo Services started!
echo Frontend: http://localhost:3000
echo Backend API: http://localhost:8000/docs
