@echo off
rem Bumao GeoOps console launcher.
rem Starts the API + console on port 8790 when it is not already listening,
rem then opens the console in the default browser.
rem
rem Set GEOOPS_PYTHON to a Python 3.12+ interpreter when `python` is not on PATH.
setlocal
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"
cd /d "%~dp0"
set "PY=%GEOOPS_PYTHON%"
if not defined PY set "PY=python"
where "%PY%" >nul 2>nul
if errorlevel 1 (
  echo Python 3.12+ was not found. Set GEOOPS_PYTHON to the interpreter path.
  exit /b 1
)
set "PORT=8790"
set "TOKENS="
if exist "var\console-tokens.json" set "TOKENS=--tokens var\console-tokens.json"

netstat -an | findstr /C:":8790 " | findstr LISTENING >nul
if %errorlevel%==0 goto open

start "GeoOps Console" /min "%PY%" -m geoops.api --demo --port %PORT% %TOKENS%
timeout /t 2 /nobreak >nul

:open
if "%GEOOPS_NO_BROWSER%"=="1" exit /b 0
start "" "http://127.0.0.1:%PORT%/ui/"
