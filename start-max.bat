@echo off
setlocal
rem chcp 65001 disabled - was causing 'm is not recognized' errors
rem chcp 65001 >nul 2>&1
rem Force UTF-8 for ComfyUI so emoji in custom node logs don't crash
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

title Start Fantasee MAX POWER
echo.
echo   ============================================================
echo      Quick launcher: Fantasee MAX POWER
echo      (delegates to start.bat max)
echo   ============================================================
echo.
echo   Spawns N CPU-only ComfyUI workers in parallel + the Fantasee
echo   server, in N+1 separate PowerShell windows. Pre-configures
echo   COMFYUI_URLS so every image job fans out across all workers.
echo.
echo   Defaults: N=3  (3 CPU workers on ports 8189, 8190, 8191
echo                     + server on 8765 = 4 windows total)
echo.
echo   Override the worker count by passing it through, e.g.:
echo     start-max.bat            3 workers (default)
echo     start-max.bat 2          2 workers
echo     start-max.bat 4          4 workers
echo     start-max.bat 2 --force  2 workers, kill any stale processes
echo.
echo   Don't go past your physical CPU core count - the workers
echo   will start thrashing each other past that point.
echo.

cd /d "%~dp0"
call start.bat max %*

endlocal
