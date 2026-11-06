#!/usr/bin/env bash
set -e

echo "========================================================================="
echo "        NecroKernel-OS : Autonomous Live Process Reanimation             "
echo "========================================================================="
echo ""

ENGINE_PID=""
DASHBOARD_PID=""

cleanup() {
    echo ""
    echo "Stopping NecroKernel-OS services..."
    if [ -n "$ENGINE_PID" ] && kill -0 "$ENGINE_PID" 2>/dev/null; then
        kill "$ENGINE_PID" 2>/dev/null || true
    fi
    if [ -n "$DASHBOARD_PID" ] && kill -0 "$DASHBOARD_PID" 2>/dev/null; then
        kill "$DASHBOARD_PID" 2>/dev/null || true
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

echo "[1/3] Starting NecroKernel-OS Hypervisor Engine on http://127.0.0.1:8000..."
python3 -m engine.server &
ENGINE_PID=$!

echo "[2/3] Waiting for Hypervisor Engine health endpoint..."
until curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; do
    sleep 0.5
done
echo "      Engine healthy and listening on port 8000."

echo "[3/3] Starting Next.js Live Telemetry Dashboard on http://localhost:3000..."
(cd dashboard && npm run dev) &
DASHBOARD_PID=$!

echo ""
echo "========================================================================="
echo "NecroKernel-OS local stack is running:"
echo "  - Frontend Dashboard:   http://localhost:3000"
echo "  - Hypervisor API:       http://127.0.0.1:8000"
echo "  - SSE Telemetry Feed:   http://127.0.0.1:8000/events"
echo "  - Metrics Endpoint:     http://127.0.0.1:8000/metrics"
echo "========================================================================="
echo ""
echo "Press Ctrl+C to terminate all services."

wait
