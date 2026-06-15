@echo off
setlocal
cd /d "%~dp0"

set CODEX_PY=C:\Users\Rejec\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
if exist "%CODEX_PY%" (
  set PYTHON_EXE=%CODEX_PY%
) else (
  set PYTHON_EXE=python
)

"%PYTHON_EXE%" -m dwarves_autoplayer.bot
pause
