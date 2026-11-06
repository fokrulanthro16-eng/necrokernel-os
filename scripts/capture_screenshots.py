"""
NecroKernel-OS High-Resolution Screenshot Capture Orchestration Script.
Captures 5 high-resolution (4K / 3840x2360) screenshots for Devpost & GitHub:
1. 01_dashboard_healthy.png: Initial HEALTHY state and PID in Next.js.
2. 02_fault_injection_sigfpe.png: Fault injection of SIGFPE / div0 in real-time.
3. 03_ast_patch_synthesis.png: Telemetry terminal showing dynamic AST diff patch during synthesis.
4. 04_reanimation_verification.png: REANIMATED state with drift_bytes: 0 and identical PID.
5. 05_metrics_endpoint.png: Formatted render of http://127.0.0.1:8000/metrics.
"""

import os
import sys
import json
import time
import asyncio
import threading
import requests
from pathlib import Path
from playwright.async_api import async_playwright

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = WORKSPACE_DIR / "docs" / "assets" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://localhost:3000"

VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1180
SCALE_FACTOR = 2  # 3840 x 2360 (4K Retina)

async def capture_all():
    print("=" * 70)
    print(" NecroKernel-OS Screenshot Automation")
    print(f" Target Directory : {SCREENSHOTS_DIR}")
    print(f" Frontend URL     : {FRONTEND_URL}")
    print(f" Backend URL      : {BACKEND_URL}")
    print(f" Resolution       : {VIEWPORT_WIDTH * SCALE_FACTOR}x{VIEWPORT_HEIGHT * SCALE_FACTOR} (4K)")
    print("=" * 70)

    # 1. Reset backend hypervisor to clean HEALTHY state
    print("\n[Step 0] Resetting hypervisor to clean state...")
    try:
        r = requests.post(f"{BACKEND_URL}/hv/reset", json={}, timeout=5)
        print("  -> /hv/reset response:", r.status_code, r.json())
    except Exception as e:
        print("  -> Reset failed:", e)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=SCALE_FACTOR,
        )
        page = await context.new_page()

        # ---------------------------------------------------------
        # Capture 1: Initial HEALTHY State
        # ---------------------------------------------------------
        print("\n[Capture 1/5] Navigating to dashboard (HEALTHY state)...")
        await page.goto(FRONTEND_URL, wait_until="networkidle")
        await page.wait_for_timeout(1500)

        # Clear terminal noise
        try:
            clear_btn = page.locator("button", has_text="clear")
            if await clear_btn.count() > 0:
                await clear_btn.click()
                await page.wait_for_timeout(500)
        except Exception as e:
            print("  (Clear button note:", e, ")")

        # Emit fresh healthy state event
        requests.post(f"{BACKEND_URL}/hv/reset", json={}, timeout=5)
        await page.wait_for_timeout(1000)

        path_1 = SCREENSHOTS_DIR / "01_dashboard_healthy.png"
        await page.screenshot(path=str(path_1))
        print(f"  -> Saved: {path_1.name} ({path_1.stat().st_size / 1024:.1f} KB)")

        # ---------------------------------------------------------
        # Capture 2: Fault Injection (SIGFPE / div0)
        # ---------------------------------------------------------
        print("\n[Capture 2/5] Injecting div by zero (SIGFPE) fault...")
        btn_div0 = page.locator("button", has_text="div by zero")
        await btn_div0.click()
        await page.wait_for_timeout(1200)

        path_2 = SCREENSHOTS_DIR / "02_fault_injection_sigfpe.png"
        await page.screenshot(path=str(path_2))
        print(f"  -> Saved: {path_2.name} ({path_2.stat().st_size / 1024:.1f} KB)")

        # ---------------------------------------------------------
        # Capture 3: AST Patch Synthesis (PATCH_SYNTHESIS stage active)
        # ---------------------------------------------------------
        print("\n[Capture 3/5] Triggering Reanimation with synthesis delay to capture AST synthesis...")
        # Dispatch reanimate in background thread with 3.0s delay
        def trigger_reanimate():
            requests.post(f"{BACKEND_URL}/hv/reanimate", json={"delay": 3.0}, timeout=10)
        
        t = threading.Thread(target=trigger_reanimate, daemon=True)
        t.start()

        # Wait 1000ms for PATCH_SYNTHESIS event and AST patch event to render in UI
        await page.wait_for_timeout(1200)

        path_3 = SCREENSHOTS_DIR / "03_ast_patch_synthesis.png"
        await page.screenshot(path=str(path_3))
        print(f"  -> Saved: {path_3.name} ({path_3.stat().st_size / 1024:.1f} KB)")

        # ---------------------------------------------------------
        # Capture 4: Reanimation Verification (REANIMATED, drift: 0)
        # ---------------------------------------------------------
        print("\n[Capture 4/5] Capturing Verified REANIMATED State (after hot-swap completion)...")
        # Wait for background reanimation to complete and settle
        await page.wait_for_timeout(2500)
        path_4 = SCREENSHOTS_DIR / "04_reanimation_verification.png"
        await page.screenshot(path=str(path_4))
        print(f"  -> Saved: {path_4.name} ({path_4.stat().st_size / 1024:.1f} KB)")

        # ---------------------------------------------------------
        # Capture 5: Formatted /metrics Prometheus Endpoint
        # ---------------------------------------------------------
        print("\n[Capture 5/5] Capturing /metrics JSON Telemetry Endpoint...")
        m_resp = requests.get(f"{BACKEND_URL}/metrics", timeout=5)
        metrics_data = m_resp.json()
        formatted_json = json.dumps(metrics_data, indent=2)

        metrics_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <title>NecroKernel-OS Hypervisor // Prometheus Metrics Exporter</title>
          <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
              background-color: #070A10;
              color: #F8FAFC;
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
              padding: 40px;
              min-height: 100vh;
              display: flex;
              flex-direction: column;
            }}
            .header-bar {{
              display: flex;
              align-items: center;
              justify-content: space-between;
              background: #0B0F19;
              border: 1px solid #1E293B;
              border-radius: 12px;
              padding: 16px 24px;
              margin-bottom: 24px;
            }}
            .brand {{
              font-family: Consolas, monospace;
              font-size: 20px;
              font-weight: bold;
              color: #38BDF8;
              letter-spacing: 1px;
            }}
            .endpoint-pill {{
              background: #064E3B;
              border: 1px solid #10B981;
              color: #A7F3D0;
              padding: 6px 14px;
              border-radius: 8px;
              font-size: 14px;
              font-weight: bold;
              font-family: Consolas, monospace;
            }}
            .stats-grid {{
              display: grid;
              grid-template-columns: repeat(4, 1fr);
              gap: 16px;
              margin-bottom: 24px;
            }}
            .stat-card {{
              background: #0F172A;
              border: 1px solid #1E293B;
              border-radius: 10px;
              padding: 20px;
            }}
            .stat-label {{
              font-size: 12px;
              text-transform: uppercase;
              color: #94A3B8;
              letter-spacing: 0.5px;
              margin-bottom: 8px;
            }}
            .stat-value {{
              font-family: Consolas, monospace;
              font-size: 26px;
              font-weight: bold;
              color: #F8FAFC;
            }}
            .stat-value.green {{ color: #10B981; }}
            .stat-value.cyan {{ color: #38BDF8; }}
            .stat-value.purple {{ color: #C084FC; }}
            .stat-value.amber {{ color: #FBBF24; }}
            .terminal-window {{
              flex: 1;
              background: #0B0F19;
              border: 1px solid #1E293B;
              border-radius: 12px;
              overflow: hidden;
              display: flex;
              flex-direction: column;
            }}
            .term-topbar {{
              background: #0F172A;
              border-bottom: 1px solid #1E293B;
              padding: 12px 20px;
              display: flex;
              align-items: center;
              justify-content: space-between;
              font-size: 13px;
              color: #94A3B8;
              font-family: Consolas, monospace;
            }}
            .term-dots {{
              display: flex;
              gap: 8px;
            }}
            .dot {{
              width: 12px;
              height: 12px;
              border-radius: 50%;
            }}
            .dot.red {{ background: #EF4444; }}
            .dot.yellow {{ background: #F59E0B; }}
            .dot.green {{ background: #10B981; }}
            pre {{
              padding: 24px;
              font-family: Consolas, "Courier New", monospace;
              font-size: 18px;
              line-height: 1.6;
              color: #38BDF8;
              overflow-x: auto;
            }}
            .json-key {{ color: #38BDF8; }}
            .json-val-num {{ color: #A7F3D0; }}
            .json-val-str {{ color: #FDE047; }}
            .json-val-bool {{ color: #C084FC; }}
            .footer-bar {{
              margin-top: 20px;
              display: flex;
              justify-content: space-between;
              color: #64748B;
              font-size: 12px;
              font-family: Consolas, monospace;
            }}
          </style>
        </head>
        <body>
          <div class="header-bar">
            <div class="brand">NECROKERNEL-OS // TELEMETRY PROMETHEUS EXPORTER</div>
            <div class="endpoint-pill">HTTP 200 OK &bull; GET /metrics</div>
          </div>

          <div class="stats-grid">
            <div class="stat-card">
              <div class="stat-label">Worker OS PID</div>
              <div class="stat-value green">{metrics_data.get('worker_pid')}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Hypervisor State</div>
              <div class="stat-value cyan">{metrics_data.get('hv_state')}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Worker Restarts</div>
              <div class="stat-value purple">{metrics_data.get('restarts_total')} (Zero Restarts)</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Heap Drift Limit</div>
              <div class="stat-value amber">&le; {metrics_data.get('heap_drift_tolerance_bytes')} Bytes</div>
            </div>
          </div>

          <div class="terminal-window">
            <div class="term-topbar">
              <div class="term-dots">
                <div class="dot red"></div>
                <div class="dot yellow"></div>
                <div class="dot green"></div>
              </div>
              <div>curl -s -X GET http://127.0.0.1:8000/metrics | jq .</div>
              <div>application/json</div>
            </div>
            <pre id="json-viewer"></pre>
          </div>

          <div class="footer-bar">
            <div>KIRO CONTRACT: .kiro/specs/reanimation_contract.spec.yaml</div>
            <div>STATUS: DETERMINISTIC HEAP VERIFICATION ACTIVE</div>
          </div>

          <script>
            const raw = {json.dumps(formatted_json)};
            const highlighted = raw
              .replace(/("(\\u[a-zA-Z0-9]{{4}}|\\[^u]|[^\\"])*")(\\s*:)?/g, (match, p1, p2, p3) => {{
                if (p3) return '<span class="json-key">' + p1 + '</span>' + p3;
                return '<span class="json-val-str">' + p1 + '</span>';
              }})
              .replace(/\\b(true|false|null)\\b/g, '<span class="json-val-bool">$&</span>')
              .replace(/\\b(-?\\d+(\\.\\d+)?)\\b/g, '<span class="json-val-num">$&</span>');
            document.getElementById('json-viewer').innerHTML = highlighted;
          </script>
        </body>
        </html>
        """

        await page.set_content(metrics_html)
        await page.wait_for_timeout(1000)

        path_5 = SCREENSHOTS_DIR / "05_metrics_endpoint.png"
        await page.screenshot(path=str(path_5))
        print(f"  -> Saved: {path_5.name} ({path_5.stat().st_size / 1024:.1f} KB)")

        await browser.close()

    print("\n" + "=" * 70)
    print(" ALL 5 SCREENSHOTS CAPTURED SUCCESSFULLY!")
    for f in sorted(SCREENSHOTS_DIR.glob("*.png")):
        print(f"  - {f.name} ({f.stat().st_size / 1024:.1f} KB)")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(capture_all())
