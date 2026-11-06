"""Hypervisor: supervisor process, bounded EventBus, process monitoring, and agent mesh lifecycle."""
from __future__ import annotations

import collections
import copy
import multiprocessing
import os
import queue
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional

from .agent_mesh import NecroInspector, PatchSynthesizer, ReanimatorEngine
from .kernel_emulator import CrashDump, FaultKind, WorkerProcess, heap_drift_bytes
from .mcp_gateway import register_worker


class EventBus:
    """Bounded, thread-safe EventBus for real-time telemetry and SSE subscribers."""
    def __init__(self, capacity: int = 500):
        self.capacity = capacity
        self._lock = threading.Lock()
        self._events: Deque[Dict[str, Any]] = collections.deque(maxlen=capacity)
        self._subscribers: List[queue.Queue] = []
        self._next_id = 1

    def emit(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            ev = {
                "id": self._next_id,
                "ts": int(time.time() * 1000),
                "type": event_type,
                **data,
            }
            self._next_id += 1
            self._events.append(ev)

            # Push to active subscribers
            dead_subs = []
            for q in self._subscribers:
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    dead_subs.append(q)
            for d in dead_subs:
                self._subscribers.remove(d)

            return ev

    def subscribe(self) -> queue.Queue:
        with self._lock:
            q = queue.Queue(maxsize=100)
            self._subscribers.append(q)
            return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def get_history(self, limit: int = 100, after_id: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            matching = [e for e in self._events if e["id"] > after_id]
            return matching[-limit:]


class Hypervisor:
    """Hypervisor supervisor managing worker telemetry, faults, reanimations, and event bus."""
    def __init__(self, in_process: bool = True):
        self.bus = EventBus()
        self.state = "HEALTHY"
        self.in_process = in_process
        self.worker = WorkerProcess(worker_name="session-worker")
        register_worker("session-worker", self.worker)

        self.reanimator = ReanimatorEngine()
        self.cycles_count = 0
        self._running = True
        self._lock = threading.Lock()

        # Start health pulse thread
        self._pulse_thread = threading.Thread(target=self._pulse_loop, daemon=True)
        self._pulse_thread.start()

        self.bus.emit("state", {"state": self.state, "pid": self.worker.pid})

    @property
    def worker_pid(self) -> int:
        return self.worker.pid

    def _pulse_loop(self) -> None:
        while self._running:
            time.sleep(2.0)
            with self._lock:
                if self.state != "DEAD":
                    self.bus.emit("pulse", {
                        "pid": self.worker.pid,
                        "state": self.state,
                        "quarantined": self.worker.quarantined,
                    })

    def crash(self, kind: Optional[str] = None) -> Dict[str, Any]:
        """Trigger fault on worker; record dump and emit fault events."""
        with self._lock:
            if self.worker.quarantined:
                return {"status": "quarantined", "error": "Worker is currently quarantined", "code": 409}
            if self.state == "DEAD":
                return {"status": "dead", "error": "Worker is dead", "code": 503}

            try:
                self.worker.inject_fault(kind)
            except Exception:
                pass

            dump = self.worker.latest_crash_dump
            if dump:
                self.state = "POISONED"
                self.bus.emit("state", {"state": "POISONED", "pid": self.worker.pid})
                self.bus.emit("fault", {
                    "kind": dump.kind,
                    "signal": dump.signal,
                    "key": dump.faulting_key,
                    "rip": dump.execution_pointer,
                })
                self.bus.emit("hook", {
                    "hook": "on_crash_intercept",
                    "event": "process.fault",
                    "kind": dump.kind,
                    "key": dump.faulting_key,
                })
                return {"status": "crashed", "dump": dump.to_dict(), "pid": self.worker.pid}

            return {"status": "ok", "pid": self.worker.pid}

    def reanimate(self, delay: float = 0.0) -> Dict[str, Any]:
        """Execute tri-agent reanimation cycle (NecroInspector -> PatchSynthesizer -> ReanimatorEngine)."""
        with self._lock:
            if self.worker.quarantined:
                return {"status": "quarantined", "error": "Worker is quarantined", "code": 409}
            if self.state == "DEAD":
                return {"status": "dead", "error": "Worker is dead", "code": 503}

            dump = self.worker.latest_crash_dump
            if not dump:
                return {"status": "healthy", "message": "No active crash to reanimate", "pid": self.worker.pid}

            self.state = "PATCH_SYNTHESIS"
            self.bus.emit("state", {"state": "PATCH_SYNTHESIS", "pid": self.worker.pid})

            def on_event(ev_type: str, data: Dict[str, Any]):
                self.bus.emit(ev_type, data)

            if delay > 0:
                from .agent_mesh import NecroInspector, PatchSynthesizer
                diagnosis = NecroInspector.diagnose(dump)
                on_event("inspect", {"diagnosis": diagnosis})
                patch_src, ast_diff = PatchSynthesizer.synthesize(diagnosis, self.worker.state)
                on_event("patch", {"patch_src": patch_src, "ast_diff": ast_diff})
                time.sleep(delay)

            res = self.reanimator.reanimate(self.worker, on_event=on_event)

            if res.get("status") == "success":
                self.state = "REANIMATED"
                self.bus.emit("state", {"state": "REANIMATED", "pid": self.worker.pid, "drift_bytes": res.get("drift_bytes")})
            elif res.get("quarantined"):
                self.state = "QUARANTINED"
                self.bus.emit("state", {"state": "QUARANTINED", "pid": self.worker.pid, "reason": res.get("reason")})

            return res

    def reset(self) -> Dict[str, Any]:
        """Audited un-quarantine and reset. PID is strictly preserved."""
        with self._lock:
            pid_before = self.worker.pid
            self.worker.reset()
            self.state = "HEALTHY"
            self.bus.emit("state", {"state": "HEALTHY", "pid": self.worker.pid})
            return {"status": "reset_success", "pid": self.worker.pid, "pid_preserved": (self.worker.pid == pid_before)}

    def stop(self) -> None:
        self._running = False
