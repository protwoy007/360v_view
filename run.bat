@echo off
setlocal
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PY %PY% -c "import sys,venv" >nul 2>nul || set "PY="
if not defined PY (
  echo Python not found. Downloading Python 3.12, please wait...
  powershell -NoProfile -Command "Invoke-WebRequest https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe -OutFile $env:TEMP\py312.exe"
  "%TEMP%\py312.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
  if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo Could not install Python automatically. Install it from python.org, then run this again.
  pause
  exit /b 1
)
%PY% app\setup.py
if errorlevel 1 (
  echo Setup failed. See the message above.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app\server.py
pause
