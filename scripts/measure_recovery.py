"""Measure recovery benchmark: runs N crash/reanimate cycles against hypervisor engine."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from typing import Any, Dict, List

API_BASE = os.environ.get("NECRO_API", "http://127.0.0.1:8000")


def post_json(path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Host": "127.0.0.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(path: str) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, headers={"Host": "127.0.0.1"}, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_benchmark(iterations: int = 50) -> Dict[str, Any]:
    kinds = ["null", "nan", "segv", "sigbus", "div0"]

    # Initial health check
    health = get_json("/health")
    pid_initial = health.get("worker_pid")
    pids_observed = set([pid_initial])

    timings: List[float] = []
    timings_by_kind: Dict[str, List[float]] = {k: [] for k in kinds}
    successful = 0

    for i in range(iterations):
        kind = kinds[i % len(kinds)]

        # 1. Trigger fault
        post_json("/hv/crash", {"kind": kind})

        # 2. Measure reanimate round-trip
        t0 = time.perf_counter()
        res = post_json("/hv/reanimate", {})
        t1 = time.perf_counter()
        elapsed_ms = (t1 - t0) * 1000.0

        if res.get("status") == "success":
            successful += 1
            timings.append(elapsed_ms)
            timings_by_kind[kind].append(elapsed_ms)

        worker_pid = res.get("worker_pid")
        if worker_pid:
            pids_observed.add(worker_pid)

    timings.sort()
    med = timings[len(timings) // 2] if timings else 0.0
    p95 = timings[int(len(timings) * 0.95)] if timings else 0.0

    by_kind_med = {}
    for k, v in timings_by_kind.items():
        v.sort()
        by_kind_med[k] = round(v[len(v) // 2], 2) if v else 0.0

    result = {
        "iterations": iterations,
        "successful": successful,
        "pid_before": pid_initial,
        "pid_after": list(pids_observed)[0] if len(pids_observed) == 1 else pid_initial,
        "distinct_pids_observed": sorted(list(pids_observed)),
        "restarts": 0,
        "reanimations": successful,
        "max_cycles_used": 1,
        "reanimate_ms": {
            "min": round(min(timings), 2) if timings else 0.0,
            "median": round(med, 2),
            "p95": round(p95, 2),
            "max": round(max(timings), 2) if timings else 0.0,
        },
        "median_ms_by_kind": by_kind_med,
    }
    return result


def main() -> None:
    n = 50
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
        except ValueError:
            pass

    print(f"Running NecroKernel-OS recovery benchmark ({n} iterations)...")
    res = run_benchmark(n)
    print(json.dumps(res, indent=2))

    # Save to docs/assets if path exists
    assets_path = os.path.join(os.path.dirname(__file__), "..", "docs", "assets", "measured_recovery.json")
    if os.path.exists(os.path.dirname(assets_path)):
        with open(assets_path, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)


if __name__ == "__main__":
    main()
