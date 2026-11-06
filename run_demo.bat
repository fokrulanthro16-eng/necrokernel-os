@echo off
setlocal enabledelayedexpansion

echo =========================================================================
echo         NecroKernel-OS : Autonomous Live Process Reanimation
echo =========================================================================
echo.

echo [1/3] Starting NecroKernel-OS Hypervisor Engine on http://127.0.0.1:8000...
start "NecroKernel Hypervisor Engine (:8000)" cmd /k "python -m engine.server"

echo [2/3] Waiting for Hypervisor Engine health endpoint...
:wait_engine
timeout /t 1 /nobreak >nul
curl -s http://127.0.0.1:8000/health >nul 2>&1
if errorlevel 1 (
    echo       Waiting for backend daemon...
    goto wait_engine
)
echo       Engine healthy and listening on port 8000.

echo [3/3] Starting Next.js Live Telemetry Dashboard on http://localhost:3000...
start "NecroKernel Next.js Dashboard (:3000)" cmd /k "cd dashboard && npm run dev"

echo.
echo =========================================================================
echo NecroKernel-OS local stack is running:
echo   - Frontend Dashboard:   http://localhost:3000
echo   - Hypervisor API:       http://127.0.0.1:8000
echo   - SSE Telemetry Feed:   http://127.0.0.1:8000/events
echo   - Metrics Endpoint:     http://127.0.0.1:8000/metrics
echo =========================================================================
echo.
echo Opening browser to http://localhost:3000...
start http://localhost:3000
pause
