@echo off
setlocal
cd /d "%~dp0"

set VENV_PY=%CD%\.venv\Scripts\python.exe

if not exist "%VENV_PY%" (
  echo Creating local virtual environment in .venv
  py -3.13 -m venv .venv
  if errorlevel 1 (
    echo Python 3.13 was not available through the py launcher. Trying default python.
    python -m venv .venv
  )
)

if not exist "%VENV_PY%" (
  echo.
  echo Setup failed: could not create .venv.
  echo Install Python 3.13 or 3.12, then rerun setup.
  pause
  exit /b 1
)

echo Using Python: %VENV_PY%
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -e .
if errorlevel 1 (
  echo.
  echo Setup failed while installing dependencies.
  echo Try deleting .venv and rerunning setup, or install Python 3.13/3.12.
  pause
  exit /b 1
)

if not exist templates mkdir templates
echo.
echo Setup complete.
pause
