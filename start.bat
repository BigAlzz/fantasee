@echo off
setlocal EnableDelayedExpansion
rem chcp 65001 disabled - was causing 'm is not recognized' errors with cmd /c invocation
rem chcp 65001 >nul 2>&1

rem ============================================================
rem  Fantasee launcher
rem  Starts the server or a ComfyUI instance, with port checks
rem  and unique ASCII art per app so you can tell them apart in
rem  multiple PowerShell windows.
rem
rem  Usage:
rem    start.bat                   - Default: start the server
rem    start.bat server            - Start Fantasee story viewer
rem    start.bat gpu1              - Start ComfyUI instance #1 (DirectML)
rem    start.bat gpu2              - Start ComfyUI instance #2 (DirectML)
rem    start.bat cpu [PORT]        - Start ComfyUI instance in CPU mode
rem                                   (default port 8189; e.g. cpu 8190)
rem    start.bat max [N]           - Spawn N CPU ComfyUI workers + the
rem                                   Fantasee server in N+1 windows.
rem                                   N defaults to 3. Pre-configures
rem                                   COMFYUI_URLS so image jobs fan out
rem                                   across every worker.
rem    start.bat all               - Open gpu1 + gpu2 + server in 3 windows
rem    start.bat validate          - Pre-flight check story manifests
rem    start.bat migrate [--apply] - Backfill missing scene fields
rem    start.bat help
rem
rem  Add --force as the last arg to auto-kill stale processes on
rem  the port (non-interactive, useful in scripts).
rem ============================================================

set "ROOT=C:\dev\fantasee"
set "COMFYUI_DIR=C:\Users\alist\Documents\comfy\ComfyUI"
set "COMFYUI_PY=C:\Users\alist\Documents\comfy\venv\Scripts\python.exe"
rem Per-worker ComfyUI SQLite database. ComfyUI's built-in DB at
rem user\comfyui.db is locked by whichever worker started first, so
rem the 2nd/3rd/Nth workers all bail at startup with
rem "Could not acquire lock on database". --database-url gives each
rem worker its own file so they can run side by side. ComfyUI uses
rem SQLAlchemy under the hood, so the value must be a URL
rem (sqlite:///<path>) not a raw filesystem path. Forward slashes
rem required even on Windows.
set "COMFYUI_USER_DIR=%COMFYUI_DIR%\user"
rem ComfyUI's --database-url wants a SQLAlchemy URL, not a filesystem
rem path. Convert backslashes to forward slashes and prepend sqlite:///.
rem Substring substitution: %VAR:\=/% replaces every \ with /.
set "DB_URL_BASE=sqlite:///%COMFYUI_USER_DIR:\=/%"
rem Force UTF-8 for Python's stdout/stderr so the rgthree-comfy custom
rem node's party emoji doesn't crash ComfyUI on Windows cp1252 consoles.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "CMD=%~1"
set "ARG2=%~2"
set "ARG3=%~3"
set "ARG4=%~4"
if "%CMD%"=="" set "CMD=server"
set "FORCE_KILL="
if /i "%ARG2%"=="--force" set "FORCE_KILL=--force"
if /i "%ARG3%"=="--force" set "FORCE_KILL=--force"
if /i "%ARG4%"=="--force" set "FORCE_KILL=--force"

if /i "%CMD%"=="server"   goto :do_server
if /i "%CMD%"=="gpu1"     goto :do_gpu1
if /i "%CMD%"=="gpu2"     goto :do_gpu2
if /i "%CMD%"=="cpu"      goto :do_cpu
if /i "%CMD%"=="max"      goto :do_max
if /i "%CMD%"=="all"      goto :do_all
if /i "%CMD%"=="validate" goto :do_validate
if /i "%CMD%"=="migrate"  goto :do_migrate
if /i "%CMD%"=="help"     goto :do_help
if /i "%CMD%"=="/?"       goto :do_help
goto :do_help

rem ------------------------------------------------------------
:do_server
    set "PORT=8765"
    set "TITLE=Fantasee Server [:%PORT%]"
    call :show_banner_server
    call :check_port
    title %TITLE%
    cd /d "%ROOT%"
    python server.py
    goto :end

rem ------------------------------------------------------------
:do_gpu1
    set "PORT=8188"
    set "TITLE=ComfyUI GPU#1 [:%PORT%]"
    call :show_banner_gpu1
    call :check_port_quick
    title %TITLE%
    cd /d "%COMFYUI_DIR%"
    "%COMFYUI_PY%" main.py --directml --listen 127.0.0.1 --port %PORT% --database-url "%DB_URL_BASE%/comfyui_%PORT%.db"
    goto :end

rem ------------------------------------------------------------
:do_gpu2
    set "PORT=8189"
    set "TITLE=ComfyUI GPU#2 [:%PORT%]"
    call :show_banner_gpu2
    call :check_port_quick
    title %TITLE%
    cd /d "%COMFYUI_DIR%"
    "%COMFYUI_PY%" main.py --directml --listen 127.0.0.1 --port %PORT% --database-url "%DB_URL_BASE%/comfyui_%PORT%.db"
    goto :end

rem ------------------------------------------------------------
rem  :do_cpu [PORT]
rem  Starts a CPU-only ComfyUI instance on PORT. Defaults to 8189
rem  (matching the auto-spawned fallback in comfyui_utils.py so the
rem  worker list is consistent whether you start the worker by hand
rem  or let the server spawn it). Pass an explicit port (e.g.
rem  "start.bat cpu 8191") to run multiple CPU workers side by side
rem  for the max-parallel mode (see "start.bat max" below).
rem
rem  Same port-check + --force kill semantics as the server.
rem ------------------------------------------------------------
:do_cpu
    set "PORT=%~2"
    if "%PORT%"=="" set "PORT=8189"
    set "TITLE=ComfyUI CPU [:%PORT%]"
    call :show_banner_cpu
    call :check_port
    title %TITLE%
    cd /d "%COMFYUI_DIR%"
    rem Run the CPU worker at BELOW_NORMAL priority so it yields to the
    rest of the desktop. /BELOWNORMAL is a Windows `start` flag, so this
    opens the worker in a new console (the .bat exits once `start`
    returns). The new console inherits the title we set above.
    start /BELOWNORMAL /D "%COMFYUI_DIR%" "%TITLE%" "%COMFYUI_PY%" main.py --cpu --listen 127.0.0.1 --port %PORT% --disable-auto-launch --database-url "%DB_URL_BASE%/comfyui_%PORT%.db"
    goto :end

rem ------------------------------------------------------------
rem  :do_max [N]
rem  Open N+1 separate PowerShell windows: N CPU ComfyUI workers
rem  (ports 8189..8188+N) plus the Fantasee server (8765).
rem  Pre-configures COMFYUI_URLS in the server's environment so all
rem  workers are picked up automatically, and disables the
rem  comfyui_utils auto-spawn fallback so the server doesn't add an
rem  extra worker we don't want.
rem
rem  N defaults to 3 (3 CPU workers + 1 server = 4 windows). Pass
rem  a different N to scale up or down, e.g. "start.bat max 2" for
rem  2 CPU workers, or "start.bat max 4" for 4. Bumping N past the
rem  number of physical CPU cores stops helping - the workers will
rem  start to thrash each other.
rem
rem  Each window has its own unique title + ASCII banner. The
rem  launching window can be closed immediately; the workers keep
rem  running. Same --force flag works for stale-process cleanup.
rem ------------------------------------------------------------
:do_max
    set "N=%~2"
    if "%N%"=="" set "N=3"
    if %N% LSS 1 set "N=1"
    if %N% GTR 6 set "N=6"

    rem Base port for CPU workers is 8189 so we never collide with
    rem the default GPU ComfyUI on 8188. With N=3 you get 8189, 8190, 8191.
    set "BASE_PORT=8189"
    set "FIRST_PORT=%BASE_PORT%"
    set "LAST_PORT="
    set "URLS="

    set /a "IDX=0"
    :do_max_build_urls
        if !IDX! GEQ %N% goto :do_max_urls_done
        set /a "PORT=%BASE_PORT%+!IDX!"
        if !IDX! EQU 0 (
            set "URLS=http://127.0.0.1:!PORT!"
        ) else (
            set "URLS=!URLS!,http://127.0.0.1:!PORT!"
        )
        set "LAST_PORT=!PORT!"
        set /a "IDX=!IDX!+1"
        goto :do_max_build_urls
    :do_max_urls_done

    echo.
    echo   ============================================================
    echo      Launching Fantasee MAX POWER stack
    echo   ============================================================
    echo.
    echo      %N% x ComfyUI CPU workers on ports %FIRST_PORT%..%LAST_PORT%
    echo      1 x FantaSee Server    on port  8765
    echo.
    echo      COMFYUI_URLS=%URLS%
    echo      FANTASEE_AUTO_SPAWN_CPU=0 (the server won't add a 4th worker)
    echo.
    echo      Each runs in its own PowerShell window with a unique
    echo      title. Close this launcher any time - the %N%+1 workers
    echo      keep running independently.
    echo   ============================================================
    echo.

    if not exist "%ROOT%\start.bat" goto :do_max_no_bat

    set "TMPDIR=%TEMP%\fantasee_launch"
    if not exist "%TMPDIR%" mkdir "%TMPDIR%" >nul 2>&1

    rem --- One CPU worker helper per slot ---
    set /a "IDX=0"
    :do_max_spawn_loop
        if !IDX! GEQ %N% goto :do_max_spawn_done
        set /a "PORT=%BASE_PORT%+!IDX!"
        set "WORKER_LABEL=ComfyUI CPU#!IDX!"
        set "WORKER_HELPER=%TMPDIR%\cpu_!IDX!.bat"
        >  "%WORKER_HELPER%" echo @echo off
        >> "%WORKER_HELPER%" echo title %WORKER_LABEL% [:!PORT!]
        >> "%WORKER_HELPER%" echo cd /d "%ROOT%"
        if /i "%FORCE_KILL%"=="--force" (
            >> "%WORKER_HELPER%" echo call "%ROOT%\start.bat" cpu !PORT! --force
        ) else (
            >> "%WORKER_HELPER%" echo call "%ROOT%\start.bat" cpu !PORT!
        )
        rem /BELOWNORMAL so the worker yields to other desktop tasks.
        start /BELOWNORMAL "%WORKER_LABEL% [:!PORT!]" "%WORKER_HELPER%"
        set /a "IDX=!IDX!+1"
        goto :do_max_spawn_loop
    :do_max_spawn_done

    rem --- Server helper with COMFYUI_URLS + auto-spawn disabled ---
    set "SERVER_HELPER=%TMPDIR%\server_max.bat"
    >  "%SERVER_HELPER%" echo @echo off
    >> "%SERVER_HELPER%" echo title Fantasee Server (MAX) [:8765]
    >> "%SERVER_HELPER%" echo cd /d "%ROOT%"
    >> "%SERVER_HELPER%" echo set "COMFYUI_URLS=%URLS%"
    >> "%SERVER_HELPER%" echo set "FANTASEE_AUTO_SPAWN_CPU=0"
    >> "%SERVER_HELPER%" echo call "%ROOT%\start.bat" server
    start "Fantasee Server (MAX) [:8765]" "%SERVER_HELPER%"

    echo   All %N%+1 windows are open. Check your taskbar.
    echo   Closing this launcher in 8 seconds...
    echo.
    timeout /t 8 /nobreak >nul
    set "TMPDIR="
    set "URLS="
    set "FIRST_PORT="
    set "LAST_PORT="
    set "BASE_PORT="
    set "N="
    set "IDX="
    set "PORT="
    set "WORKER_LABEL="
    set "WORKER_HELPER="
    set "SERVER_HELPER="
    goto :end

:do_max_no_bat
    echo   ERROR: cannot find %ROOT%\start.bat
    pause
    goto :end

rem ------------------------------------------------------------
rem  Open 3 separate PowerShell windows: gpu1 + gpu2 + server.
rem  Each window has its own unique title so you can switch
rem  between them in the taskbar. The launching window can be
rem  closed immediately; the 3 workers keep running.
:do_all
    echo.
    echo   ============================================================
    echo      Launching FantaSee stack: 3 separate windows
    echo   ============================================================
    echo.
    echo      1) ComfyUI GPU #1   (port 8188)
    echo      2) ComfyUI GPU #2   (port 8189)  - optional 2nd GPU
    echo      3) FantaSee Server  (port 8765)
    echo.
    echo      Each runs in its own PowerShell window with a unique
    echo      title. Close this window any time - the 3 workers
    echo      keep running independently.
    echo   ============================================================
    echo.

    if not exist "%ROOT%\start.bat" goto :do_all_no_bat

    rem Use a tiny helper script per launch. Each helper sets the
    rem window title and runs the requested command. This avoids
    rem nested-quote hell with the `start` command, and the helper
    rem lives in %TEMP% so it doesn't pollute the project dir.
    set "TMPDIR=%TEMP%\fantasee_launch"
    if not exist "%TMPDIR%" mkdir "%TMPDIR%" >nul 2>&1

    rem --- gpu1 helper ---
    set "G1=%TMPDIR%\gpu1.bat"
    > "%G1%"  echo @echo off
    >>"%G1%" echo title ComfyUI GPU#1 [:8188]
    >>"%G1%" echo cd /d "%ROOT%"
    if /i "%FORCE_KILL%"=="--force" (
        >>"%G1%" echo call "%ROOT%\start.bat" gpu1 --force
    ) else (
        >>"%G1%" echo call "%ROOT%\start.bat" gpu1
    )
    start "ComfyUI GPU#1 [:8188]" "%G1%"

    rem --- gpu2 helper ---
    set "G2=%TMPDIR%\gpu2.bat"
    > "%G2%"  echo @echo off
    >>"%G2%" echo title ComfyUI GPU#2 [:8189]
    >>"%G2%" echo cd /d "%ROOT%"
    if /i "%FORCE_KILL%"=="--force" (
        >>"%G2%" echo call "%ROOT%\start.bat" gpu2 --force
    ) else (
        >>"%G2%" echo call "%ROOT%\start.bat" gpu2
    )
    start "ComfyUI GPU#2 [:8189]" "%G2%"

    rem --- server helper ---
    set "GS=%TMPDIR%\server.bat"
    > "%GS%"  echo @echo off
    >>"%GS%" echo title Fantasee Server [:8765]
    >>"%GS%" echo cd /d "%ROOT%"
    >>"%GS%" echo set "COMFYUI_URLS=http://127.0.0.1:8188,http://127.0.0.1:8189"
    >>"%GS%" echo set "FANTASEE_AUTO_SPAWN_CPU=0"
    if /i "%FORCE_KILL%"=="--force" (
        >>"%GS%" echo call "%ROOT%\start.bat" server --force
    ) else (
        >>"%GS%" echo call "%ROOT%\start.bat" server
    )
    start "Fantasee Server [:8765]" "%GS%"

    echo   All 3 windows are open. Check your taskbar.
    echo   Closing this launcher in 6 seconds...
    echo.
    timeout /t 6 /nobreak >nul
    set "TMPDIR="
    set "G1="
    set "G2="
    set "GS="
    goto :end

:do_all_no_bat
    echo   ERROR: cannot find %ROOT%\start.bat
    pause
    goto :end

rem ------------------------------------------------------------
:do_validate
    set "TITLE=Fantasee Validate"
    title %TITLE%
    cd /d "%ROOT%"
    python critic.py --validate
    echo.
    echo Exit code: %errorlevel%
    pause
    goto :end

rem ------------------------------------------------------------
:do_migrate
    set "TITLE=Fantasee Migrate"
    title %TITLE%
    cd /d "%ROOT%"
    python migrate_backfill_scene_field.py %ARG2% %ARG3%
    echo.
    echo Exit code: %errorlevel%
    pause
    goto :end

rem ------------------------------------------------------------
:do_help
    echo.
    echo Fantasee launcher
    echo.
    echo Usage: start.bat COMMAND [options]
    echo.
    echo Commands:
    echo   server             Start Fantasee story viewer  (port 8765)
    echo   gpu1               Start ComfyUI instance #1    (port 8188, DirectML)
    echo   gpu2               Start ComfyUI instance #2    (port 8189, DirectML)
    echo   cpu [PORT]         Start a CPU-only ComfyUI     (default port 8189)
    echo   max [N]            Spawn N CPU workers + server in N+1 windows
    echo                       (N defaults to 3; pre-configures COMFYUI_URLS)
    echo   all                Open gpu1 + gpu2 + server in 3 separate windows
    echo   validate           Pre-flight check on story manifests
    echo   migrate --apply    Backfill missing scene fields
    echo   help               Show this help
    echo.
    echo Options:
    echo   --force            Auto-kill stale processes on the target port
    echo.
    echo Examples:
    echo   start.bat                  (default: starts server)
    echo   start.bat all              (opens 3 separate windows, GPU mode)
    echo   start.bat server           (just the story viewer)
    echo   start.bat gpu1             (just ComfyUI #1)
    echo   start.bat gpu2 --force     (just ComfyUI #2, kill any stale)
    echo   start.bat cpu 8190         (CPU ComfyUI on port 8190)
    echo   start.bat max 4            (4 CPU workers + server, in 5 windows)
    echo   start.bat max 2 --force    (2 CPU workers + server, kill any stale)
    echo   start.bat validate
    echo   start.bat migrate --apply
    echo.
    echo Parallel tip: set COMFYUI_URLS=http://127.0.0.1:8188,http://127.0.0.1:8189
    echo in the environment where you run server.py, then it will fan out
    echo image jobs across BOTH GPU instances automatically. The "max"
    echo command does this for you when running CPU-only.
    echo.
    echo CPU-only mode: use "start-max.bat" (or "start.bat max") to spin up
    echo several CPU workers in parallel. CPU is ~5-10x slower per image
    echo than a GPU, so 3-4 workers gives a meaningful speedup vs. 1.
    echo.
    pause
    goto :end

rem ============================================================
rem  Banners - each one visually distinct so you can tell
rem  multiple PowerShell windows apart at a glance.
rem  ASCII art uses only safe characters: letters, numbers,
rem  dots, slashes, underscores, spaces. No pipes or backslashes.
rem ============================================================

:show_banner_server
    title %TITLE%
    echo.
    echo   ============================================================
    echo.
    echo        F A N T A S E E
    echo.
    echo   ============================================================
    echo        SERVER  /  http://127.0.0.1:%PORT%/
    echo   ============================================================
    echo.
    goto :eof

:show_banner_gpu1
    title %TITLE%
    echo.
    echo   ============================================================
    echo.
    echo        C O M F Y  U I
    echo.
    echo   ============================================================
    echo        GPU #1  /  http://127.0.0.1:%PORT%/
    echo   ============================================================
    echo.
    goto :eof

:show_banner_gpu2
    title %TITLE%
    echo.
    echo   ============================================================
    echo.
    echo        C O M F Y  U I
    echo.
    echo   ============================================================
    echo        GPU #2  /  http://127.0.0.1:%PORT%/
    echo   ============================================================
    echo.
    echo   Parallel tip: set COMFYUI_URLS=http://127.0.0.1:8188,http://127.0.0.1:8189
    echo   in the environment where you run server.py, then it will fan
    echo   out image jobs across BOTH GPU instances automatically.
    echo.
    goto :eof

:show_banner_cpu
    title %TITLE%
    echo.
    echo   ============================================================
    echo.
    echo        C O M F Y  U I
    echo.
    echo   ============================================================
    echo        CPU  /  http://127.0.0.1:%PORT%/
    echo   ============================================================
    echo.
    echo   CPU-only instance (no GPU acceleration). Spawn multiple of
    echo   these on different ports to parallelize image generation:
    echo.
    echo     start.bat cpu 8189
    echo     start.bat cpu 8190
    echo     start.bat cpu 8191
    echo.
    echo   ...then start the server with COMFYUI_URLS pointing at all
    echo   of them, or just use "start.bat max" / "start-max.bat" to
    echo   do it automatically.
    echo.
    goto :eof

rem ============================================================
rem  Port check - find processes listening on the target port
rem  and offer to kill them.
rem ============================================================

:check_port
    set "STALE_PIDS="
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING 2^>nul') do (
        if not "%%P"=="0" set "STALE_PIDS=!STALE_PIDS! %%P"
    )
    if "%STALE_PIDS%"=="" goto :port_free
    echo   [WARN] Port %PORT% is in use by PID(s):%STALE_PIDS%
    if /i "%FORCE_KILL%"=="--force" goto :port_kill_force
    set /p KILL="   Kill them and continue? [y/N] "
    if /i "%KILL%"=="y" goto :port_kill_confirmed
    echo   [WARN] Continuing without killing. The new process may fail to bind.
    echo.
    exit /b 0

:port_free
    echo   [OK] Port %PORT% is free.
    echo.
    exit /b 0

:port_kill_force
    echo   [WARN] --force set: killing stale process(es)...
    goto :port_kill

:port_kill_confirmed
    goto :port_kill

:port_kill
    for %%P in (%STALE_PIDS%) do taskkill /PID %%P /F >nul 2>&1
    timeout /t 2 /nobreak >nul
    echo   [OK] Stale process(es) killed.
    echo.
    exit /b 0

rem ------------------------------------------------------------
rem  Quick port check (used by gpu1/gpu2) - just reports whether
rem  the port is busy; doesn't try to kill anything. The full
rem  :check_port with kill logic is for the server, where stale
rem  instances are common; for ComfyUI instances, a port conflict
rem  is rare and best handled by the user.
:check_port_quick
    set "QUICK_PID="
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do set "QUICK_PID=%%P"
    if not "%QUICK_PID%"=="" goto :quick_busy
    echo   [OK] Port %PORT% is free.
    echo.
    exit /b 0
:quick_busy
    if /i "%FORCE_KILL%"=="--force" goto :quick_kill_force
    echo   [WARN] Port %PORT% is busy (PID %QUICK_PID%). ComfyUI may fail to bind.
    echo          Run with --force to auto-kill, or use start.bat gpu1 --force.
    echo.
    exit /b 0

:quick_kill_force
    echo   [WARN] --force set: killing process on port %PORT% (PID %QUICK_PID%)...
    taskkill /PID %QUICK_PID% /F >nul 2>&1
    timeout /t 2 /nobreak >nul
    echo   [OK] Port %PORT% cleared.
    echo.
    exit /b 0

rem ------------------------------------------------------------
:end
    endlocal
