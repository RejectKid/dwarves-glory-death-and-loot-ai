@echo off
setlocal
cd /d "%~dp0"

set PYTHON_EXE=%CD%\.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
  echo Missing .venv. Run setup.bat first.
  pause
  exit /b 1
)

"%PYTHON_EXE%" -m dwarves_autoplayer.capture_template
pause
