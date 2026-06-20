@echo off
setlocal
rem chcp 65001 disabled - was causing 'm is not recognized' errors
rem chcp 65001 >nul 2>&1
rem Force UTF-8 for ComfyUI so emoji in custom node logs don't crash
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

title Start ComfyUI GPU #1
echo.
echo   ============================================================
echo      Quick launcher: ComfyUI GPU #1
echo      (delegates to start.bat gpu1)
echo   ============================================================
echo.
echo   Starting ComfyUI on port 8188...
echo   Set COMFYUI_URLS=http://127.0.0.1:8188,http://127.0.0.1:8189
echo   in your server.py environment to enable parallel images.
echo.

cd /d "%~dp0"
call start.bat gpu1 %*

endlocal
