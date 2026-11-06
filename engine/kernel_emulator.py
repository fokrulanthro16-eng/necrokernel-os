"""Kernel emulator: shared-memory heap, simulated faults, POSIX signal mapping, and crash dumps."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import signal
import struct
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

SHM_SIZE = 65536
HEADER_FORMAT = ">II"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_PAYLOAD_SIZE = SHM_SIZE - HEADER_SIZE


class FaultKind(str, Enum):
    NULL_DEREF = "NULL_DEREF"
    POISONED_OPERAND = "POISONED_OPERAND"
    SIGSEGV = "SIGSEGV"
    UNMAPPED_ACCESS = "UNMAPPED_ACCESS"
    ZERO_DIVISION = "ZERO_DIVISION"


class HardwareFault(Exception):
    """Raised when a checked memory access or arithmetic fault triggers a POSIX signal."""
    def __init__(self, kind: FaultKind, key: str, signal_name: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"[{signal_name}] {kind.value} on {key}: {message}")
        self.kind = kind
        self.key = key
        self.signal_name = signal_name
        self.details = details or {}


@dataclass
class CrashDump:
    kind: str
    signal: str
    faulting_key: str
    registers: Dict[str, Any]
    call_stack: List[Dict[str, Any]]
    execution_pointer: str
    heap_snapshot: Dict[str, Any]
    timestamp: float
    worker_pid: int
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "signal": self.signal,
            "faulting_key": self.faulting_key,
            "registers": self.registers,
            "call_stack": self.call_stack,
            "execution_pointer": self.execution_pointer,
            "heap_snapshot": self.heap_snapshot,
            "timestamp": self.timestamp,
            "worker_pid": self.worker_pid,
            "details": self.details,
        }


def canonical_json(obj: Any) -> bytes:
    """Format canonical compact JSON with sorted keys."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def heap_drift_bytes(state_before: Dict[str, Any], state_after: Dict[str, Any]) -> int:
    """Calculate heap drift |M_after - M_before| in canonical JSON byte length."""
    len_before = len(canonical_json(state_before))
    len_after = len(canonical_json(state_after))
    return abs(len_after - len_before)


class SharedHeap:
    """64 KiB Seqlock-framed shared memory heap simulation/wrapper."""
    def __init__(self, buffer: Optional[bytearray] = None):
        self._buf = buffer if buffer is not None else bytearray(SHM_SIZE)

    def write_payload(self, state: Dict[str, Any]) -> None:
        payload = canonical_json(state)
        if len(payload) > MAX_PAYLOAD_SIZE:
            raise ValueError(f"Payload size {len(payload)} exceeds max heap size {MAX_PAYLOAD_SIZE}")

        cur_gen, _ = struct.unpack_from(HEADER_FORMAT, self._buf, 0)
        # Seqlock: make generation odd during write
        odd_gen = cur_gen + 1 if (cur_gen % 2 == 0) else cur_gen
        struct.pack_into(HEADER_FORMAT, self._buf, 0, odd_gen, len(payload))

        self._buf[HEADER_SIZE : HEADER_SIZE + len(payload)] = payload

        # Seqlock: make generation even after write
        even_gen = odd_gen + 1
        struct.pack_into(HEADER_FORMAT, self._buf, 0, even_gen, len(payload))

    def read_payload(self, max_retries: int = 10) -> Dict[str, Any]:
        for _ in range(max_retries):
            gen1, length = struct.unpack_from(HEADER_FORMAT, self._buf, 0)
            if gen1 % 2 != 0:
                time.sleep(0.001)
                continue
            if length == 0:
                return {}
            if length > MAX_PAYLOAD_SIZE:
                continue

            raw = bytes(self._buf[HEADER_SIZE : HEADER_SIZE + length])
            gen2, _ = struct.unpack_from(HEADER_FORMAT, self._buf, 0)
            if gen1 == gen2:
                try:
                    return json.loads(raw.decode("utf-8"))
                except Exception:
                    pass
            time.sleep(0.001)
        return {}


class WorkerProcess:
    """Worker process runtime maintaining state, checked heap accessors, signal handlers, and execution."""
    def __init__(self, worker_name: str = "session-worker", initial_state: Optional[Dict[str, Any]] = None, pid: Optional[int] = 6908):
        self.name = worker_name
        self.pid = pid if pid is not None else 6908
        self.heap = SharedHeap()
        self.state: Dict[str, Any] = {
            "session_id": "sess-live-0x4a1f",
            "crypto_context": {"cipher": "AES-256-GCM", "epoch": 42},
            "counters": {"requests": 100, "tokens": 5420},
            "worker_token": hashlib.sha256(f"{self.pid}-{time.time()}".encode()).hexdigest()[:16],
            "active_tasks": ["stream_metrics", "kv_lease"],
            "metrics": {"latency_ms": 1.2, "errors": 0},
        }
        if initial_state:
            self.state.update(initial_state)

        self.heap.write_payload(self.state)
        self.latest_crash_dump: Optional[CrashDump] = None
        self.quarantined = False
        self.fault_count = 0
        self.reanimation_count = 0
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Register signal handlers for SIGSEGV, SIGBUS, SIGFPE."""
        def _handler(signum, frame):
            sig_map = {
                signal.SIGSEGV: "SIGSEGV",
                signal.SIGFPE: "SIGFPE",
            }
            if hasattr(signal, "SIGBUS"):
                sig_map[signal.SIGBUS] = "SIGBUS"
            name = sig_map.get(signum, f"SIG_{signum}")
            # Real signal was caught in this process
            pass

        try:
            signal.signal(signal.SIGSEGV, _handler)
            signal.signal(signal.SIGFPE, _handler)
            if hasattr(signal, "SIGBUS"):
                signal.signal(signal.SIGBUS, _handler)
        except (ValueError, AttributeError):
            pass

    def read_key(self, key: str) -> Any:
        """Checked accessor detecting null pointers, poison values, or unmapped keys."""
        if self.quarantined:
            raise RuntimeError(f"Worker {self.name} is quarantined")

        if key not in self.state:
            self._trigger_fault(FaultKind.UNMAPPED_ACCESS, key, signal.SIGBUS if hasattr(signal, "SIGBUS") else signal.SIGSEGV, f"Key '{key}' unmapped in heap")

        val = self.state[key]
        if val is None:
            self._trigger_fault(FaultKind.NULL_DEREF, key, signal.SIGSEGV, f"Null pointer dereference on key '{key}'")

        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            self._trigger_fault(FaultKind.POISONED_OPERAND, key, signal.SIGFPE, f"Poisoned operand (NaN/Inf) on key '{key}'")

        if isinstance(val, dict):
            for sub_k, sub_v in val.items():
                if isinstance(sub_v, float) and (math.isnan(sub_v) or math.isinf(sub_v)):
                    self._trigger_fault(FaultKind.POISONED_OPERAND, key, signal.SIGFPE, f"Poisoned operand ({sub_k}=NaN/Inf) in dict '{key}'", {"field": sub_k})

        return val

    def check_index(self, key: str, index: int) -> Any:
        """Checked sequence accessor detecting SIGSEGV out-of-range index."""
        seq = self.read_key(key)
        if not isinstance(seq, (list, tuple)):
            self._trigger_fault(FaultKind.SIGSEGV, key, signal.SIGSEGV, f"Key '{key}' is not indexable")

        if index < 0 or index >= len(seq):
            self._trigger_fault(FaultKind.SIGSEGV, key, signal.SIGSEGV, f"Index {index} out of bounds for key '{key}' (len {len(seq)})", {"index": index, "len": len(seq)})

        return seq[index]

    def check_division(self, key: str, divisor: float) -> float:
        """Checked arithmetic accessor detecting ZeroDivisionError / SIGFPE."""
        num = self.read_key(key)
        if divisor == 0 or divisor == 0.0:
            self._trigger_fault(FaultKind.ZERO_DIVISION, key, signal.SIGFPE, "Division by zero trap", {"divisor": 0})
        return num / divisor

    def _trigger_fault(self, kind: FaultKind, key: str, sig_num: int, msg: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Records dump, sends real signal to own PID, and raises HardwareFault."""
        self.fault_count += 1
        sig_name = "SIGSEGV" if sig_num == signal.SIGSEGV else ("SIGBUS" if hasattr(signal, "SIGBUS") and sig_num == signal.SIGBUS else "SIGFPE")
        if kind == FaultKind.ZERO_DIVISION:
            sig_name = "SIGFPE"

        # Registers derived from execution context
        regs = {
            "rax": hex(id(self.state.get(key, 0))),
            "rbx": hex(len(self.state)),
            "rcx": hex(self.fault_count),
            "rdx": hex(int(time.time() * 1000) & 0xFFFFFFFF),
            "rsi": hex(0xDEADBEEF if kind in (FaultKind.NULL_DEREF, FaultKind.UNMAPPED_ACCESS) else 0),
            "rdi": hex(id(key)),
            "rsp": hex(id(self)),
            "rbp": hex(id(self.heap)),
            "rip": hex(0x7FFF0000 + (self.fault_count * 0x100)),
        }
        stack = [
            {"frame": 0, "fn": "checked_accessor", "file": __file__, "line": 150},
            {"frame": 1, "fn": "execute_task", "file": __file__, "line": 210},
        ]

        self.latest_crash_dump = CrashDump(
            kind=kind.value,
            signal=sig_name,
            faulting_key=key,
            registers=regs,
            call_stack=stack,
            execution_pointer=regs["rip"],
            heap_snapshot=copy.deepcopy(self.state),
            timestamp=time.time(),
            worker_pid=self.pid,
            details=details or {},
        )

        # Real signal to own PID only on POSIX systems (on Windows, os.kill on SEGV terminates immediately)
        if os.name != "nt":
            try:
                os.kill(os.getpid(), sig_num)
            except (AttributeError, OSError):
                pass

        raise HardwareFault(kind, key, sig_name, msg, details)

    def inject_fault(self, kind_name: Optional[str] = None, trap: bool = True) -> None:
        """Helper to inject one of the 5 canonical fault kinds into the heap."""
        k = (kind_name or "null").lower()
        try:
            if k in ("null", "null_deref"):
                self.state["active_tasks"] = None
                self.heap.write_payload(self.state)
                self.read_key("active_tasks")
            elif k in ("nan", "poison", "poisoned_operand"):
                self.state["metrics"] = {"latency_ms": float("nan"), "errors": 0}
                self.heap.write_payload(self.state)
                self.read_key("metrics")
            elif k in ("segv", "sigsegv"):
                self.state["active_tasks"] = ["task_alpha", "task_beta"]
                self.heap.write_payload(self.state)
                self.check_index("active_tasks", 99)
            elif k in ("sigbus", "unmapped"):
                self.state.pop("unmap", None)
                self.heap.write_payload(self.state)
                self.read_key("unmap")
            elif k in ("div0", "zero_division"):
                self.state["metrics"] = {"latency_ms": 1.0, "errors": 0}
                self.heap.write_payload(self.state)
                self.check_division("metrics", 0.0)
            else:
                self.state["active_tasks"] = None
                self.heap.write_payload(self.state)
                self.read_key("active_tasks")
        except HardwareFault:
            if not trap:
                raise

    def execute_task(self, task_func: Callable[[Dict[str, Any]], Any]) -> Any:
        """Executes a task against worker state. Traps faults."""
        if self.quarantined:
            raise RuntimeError("Cannot execute on quarantined worker")
        try:
            res = task_func(self.state)
            self.heap.write_payload(self.state)
            return res
        except HardwareFault:
            raise
        except ZeroDivisionError as e:
            self._trigger_fault(FaultKind.ZERO_DIVISION, "divisor", signal.SIGFPE, str(e))

    def reset(self, new_state: Optional[Dict[str, Any]] = None) -> None:
        """Audited reset of worker state and quarantine status. PID is strictly preserved."""
        self.quarantined = False
        self.latest_crash_dump = None
        if new_state:
            self.state = copy.deepcopy(new_state)
        else:
            self.state = {
                "session_id": "sess-live-0x4a1f",
                "crypto_context": {"cipher": "AES-256-GCM", "epoch": 42},
                "counters": {"requests": 100, "tokens": 5420},
                "worker_token": hashlib.sha256(f"{self.pid}".encode()).hexdigest()[:16],
                "active_tasks": ["stream_metrics", "kv_lease"],
                "metrics": {"latency_ms": 1.2, "errors": 0},
            }
        self.heap.write_payload(self.state)
