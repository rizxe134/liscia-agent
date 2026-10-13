@echo off
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
where pythonw >nul 2>nul && (start "" pythonw agent.py %*) || (python agent.py %* & pause)
