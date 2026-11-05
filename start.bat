@echo off
setlocal
cd /d "%~dp0"
if exist ".packages\flask\__init__.py" (
  set "PYTHONPATH=%~dp0.packages"
  set CAMPUS_DEMO=1
  echo Campus textbook exchange: http://127.0.0.1:5000
  echo Press Ctrl+C to stop.
  python app.py
  if errorlevel 1 goto :failed
  exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto :failed
)
if not exist ".venv\ready.txt" (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
  echo ready> .venv\ready.txt
)
set CAMPUS_DEMO=1
echo Campus textbook exchange: http://127.0.0.1:5000
echo Press Ctrl+C to stop.
.venv\Scripts\python.exe app.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo Startup failed. Please check Python 3.12+ and network access.
pause
exit /b 1
