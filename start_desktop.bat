@echo off
REM =====================================================================
REM  AI Serial Bridge - Desktop launcher (Windows)
REM
REM  Uses the project's .venv interpreter explicitly, so a different
REM  Python earlier on PATH cannot be picked up by mistake.
REM
REM  NOTE: keep this file pure ASCII. cmd.exe parses .bat files using the
REM  OEM code page (GBK on zh-CN Windows), so UTF-8 Chinese text here
REM  would be mangled and may be executed as commands.
REM =====================================================================
setlocal

set "PROJECT_DIR=%~dp0"
set "VENV_PY=%PROJECT_DIR%.venv\Scripts\python.exe"
set "VENV_PYW=%PROJECT_DIR%.venv\Scripts\pythonw.exe"
set "DESKTOP_PY=%PROJECT_DIR%desktop.py"
set "FRONTEND_INDEX=%PROJECT_DIR%frontend\dist\index.html"

if not exist "%VENV_PY%" goto no_venv
if not exist "%FRONTEND_INDEX%" goto no_dist

REM Verify the venv actually has the runtime dependencies.
"%VENV_PY%" -c "import uvicorn, webview, fastapi" >nul 2>&1
if errorlevel 1 goto bad_deps

REM Launch with pythonw.exe so no console window stays open.
start "AI Serial Bridge" "%VENV_PYW%" "%DESKTOP_PY%"
exit /b 0

:no_venv
echo [ERROR] Virtual environment not found: %VENV_PY%
echo         Create it first:
echo           py -3.13 -m venv .venv
echo           .venv\Scripts\python.exe -m pip install -r backend\requirements-desktop.txt
exit /b 1

:no_dist
echo [ERROR] Frontend build not found: %FRONTEND_INDEX%
echo         Build it first:
echo           cd frontend
echo           npm ci
echo           npm run build
exit /b 1

:bad_deps
echo [ERROR] The .venv is missing uvicorn / webview / fastapi.
echo         Install them with:
echo           .venv\Scripts\python.exe -m pip install -r backend\requirements-desktop.txt
exit /b 1
