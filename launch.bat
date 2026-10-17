@echo off
cd /d "%~dp0"
title TrailWaver

:: Tuer toute instance precedente sur le port 5050
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5050 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: Ouvrir le navigateur apres 2s (en arriere-plan)
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5050"

:: Lancer Flask (foreground — Ctrl+C pour arreter)
python editor.py
