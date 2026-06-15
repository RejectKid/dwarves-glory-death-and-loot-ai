@echo off
setlocal
cd /d "%~dp0"

set PYTHON_EXE=%CD%\.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
  echo Missing .venv. Run setup.bat first.
  pause
  exit /b 1
)

if not exist "%CD%\knowledge\baseline.yaml" (
  echo Missing baseline knowledge. Bootstrapping from public wiki/guide sources first.
  "%PYTHON_EXE%" -m dwarves_autoplayer.bootstrap_knowledge
)

"%PYTHON_EXE%" -m dwarves_autoplayer.bot --auto-start
pause
