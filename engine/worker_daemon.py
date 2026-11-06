"""Worker daemon: separate OS process supervising its own heap and signal traps."""
from __future__ import annotations

import copy
import multiprocessing
import multiprocessing.connection
import os
import signal
import sys
import time
from typing import Any, Dict, Optional

from .kernel_emulator import CrashDump, FaultKind, HardwareFault, SharedHeap, WorkerProcess


def run_worker_loop(pipe: multiprocessing.connection.Connection, shm_buffer: Optional[bytearray] = None) -> None:
    """Main loop of the worker daemon running in its own OS process."""
    worker = WorkerProcess(worker_name="session-worker")
    if shm_buffer is not None:
        worker.heap = SharedHeap(shm_buffer)
        worker.heap.write_payload(worker.state)

    # Inform supervisor of PID
    pipe.send({"op": "ready", "pid": os.getpid()})

    while True:
        try:
            if not pipe.poll(0.1):
                continue
            msg = pipe.recv()
        except (EOFError, KeyboardInterrupt):
            break

        op = msg.get("op")
        if op == "ping":
            pipe.send({"op": "pong", "pid": os.getpid(), "alive": True})
        elif op == "get_pid":
            pipe.send({"op": "pid", "pid": os.getpid()})
        elif op == "crash":
            kind = msg.get("kind", "null")
            try:
                worker.inject_fault(kind)
                pipe.send({"op": "crash_result", "fault": False})
            except HardwareFault as e:
                dump = worker.latest_crash_dump
                pipe.send({
                    "op": "crash_result",
                    "fault": True,
                    "kind": e.kind.value,
                    "signal": e.signal_name,
                    "key": e.key,
                    "dump": dump.to_dict() if dump else None,
                    "pid": os.getpid(),
                })
        elif op == "get_dump":
            dump = worker.latest_crash_dump
            pipe.send({"op": "dump", "dump": dump.to_dict() if dump else None, "pid": os.getpid()})
        elif op == "apply_patch":
            patch_src = msg.get("patch_src")
            try:
                from .agent_mesh import execute_patch_sandboxed, validate_patch
                validate_patch(patch_src)
                worker.state = execute_patch_sandboxed(patch_src, worker.state)
                worker.heap.write_payload(worker.state)
                worker.latest_crash_dump = None
                worker.reanimation_count += 1
                pipe.send({"op": "patch_applied", "success": True, "pid": os.getpid(), "state": worker.state})
            except Exception as e:
                worker.quarantined = True
                pipe.send({"op": "patch_applied", "success": False, "error": str(e), "pid": os.getpid()})
        elif op == "reset":
            worker.reset()
            pipe.send({"op": "reset_done", "pid": os.getpid(), "quarantined": False})
        elif op == "stop":
            break


def spawn_worker_process() -> Tuple[multiprocessing.Process, multiprocessing.connection.Connection]:
    """Spawn worker OS process using spawn context."""
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe()
    proc = ctx.Process(target=run_worker_loop, args=(child_conn,), daemon=True)
    proc.start()
    return proc, parent_conn
