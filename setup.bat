@echo off
setlocal
cd /d "%~dp0"

set CODEX_PY=C:\Users\Rejec\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
if exist "%CODEX_PY%" (
  set PYTHON_EXE=%CODEX_PY%
) else (
  set PYTHON_EXE=python
)

echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" -m pip install --upgrade pip
"%PYTHON_EXE%" -m pip install -e .
if errorlevel 1 (
  echo.
  echo Setup failed. If you are using Python 3.14, install Python 3.12 and rerun setup.
  pause
  exit /b 1
)

if not exist templates mkdir templates
echo.
echo Setup complete.
pause
