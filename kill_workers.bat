@echo off
rem ─────────────────────────────────────────────────────────────
rem  kill_workers.bat
rem  Wipes every ComfyUI worker + the Fantasee server + their
rem  helper scripts so a clean "start.bat max" can be launched
rem  without ports-in-use errors.
rem
rem  Safe to run multiple times. Idempotent.
rem ─────────────────────────────────────────────────────────────
setlocal

set "ROOT=C:\dev\fantasee"

echo.
echo   ============================================================
echo      Killing Fantasee + ComfyUI workers
echo   ============================================================
echo.

rem 1. Kill any pythonw / python process whose command line
rem    references our project — that's every worker + the server
rem    we ever spawned from this workspace.
echo   - Killing python* processes launched from %ROOT% ...
for /f "tokens=*" %%P in ('wmic process where "name like 'python%%'" get processid^,commandline /format:list 2^>nul ^| findstr /c:"%ROOT%"') do (
    for /f "tokens=2 delims==" %%I in ("%%P") do (
        if not "%%I"=="" (
            echo     stopping PID %%I
            taskkill /F /PID %%I >nul 2>&1
        )
    )
)

rem 2. Fallback: kill anything still bound to the worker ports
rem    (8188-8195) or the server port (8765).
echo   - Freeing ports 8188-8195 + 8765 ...
for %%P in (8188 8189 8190 8191 8192 8193 8194 8195 8765) do (
    for /f "tokens=*" %%O in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        for /f "tokens=5" %%I in ("%%O") do (
            if not "%%I"=="" (
                echo     stopping PID %%I (port %%P)
                taskkill /F /PID %%I >nul 2>&1
            )
        )
    )
)

rem 3. Remove the helper .bat files the max launcher leaves in TEMP
if exist "%TEMP%\fantasee_launch" (
    echo   - Removing %TEMP%\fantasee_launch\ ...
    rmdir /S /Q "%TEMP%\fantasee_launch" >nul 2>&1
)

rem 4. Give the OS a moment to release the sockets
echo   - Waiting 2s for sockets to release ...
timeout /t 2 /nobreak >nul

echo.
echo   Done. You can now run "start.bat max" cleanly.
echo.
endlocal
