"""MCP gateway: tool dispatcher for necro_telemetry tools (JSON-RPC and programmatic)."""
from __future__ import annotations

import copy
import json
import sys
from typing import Any, Dict, List, Optional

from .agent_mesh import execute_patch_sandboxed, load_limits, load_tolerances, validate_patch
from .kernel_emulator import CrashDump, WorkerProcess, heap_drift_bytes

# Global registry of active workers for MCP tools
_WORKERS: Dict[str, WorkerProcess] = {}


def get_or_create_worker(name: str = "session-worker") -> WorkerProcess:
    if name not in _WORKERS:
        _WORKERS[name] = WorkerProcess(worker_name=name)
    return _WORKERS[name]


def register_worker(name: str, worker: WorkerProcess) -> None:
    _WORKERS[name] = worker


MCP_TOOLS_SPEC = [
    {
        "name": "read_crash_dump",
        "description": "Return registers, call stack, execution pointer and fault metadata for a crashed worker.",
        "inputSchema": {
            "type": "object",
            "properties": {"worker": {"type": "string"}},
            "required": ["worker"],
        },
    },
    {
        "name": "inject_hotpatch",
        "description": "Validate and apply a bounded hot-patch to a crashed worker's faulting key only, then run post_reanimation_verify.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "worker": {"type": "string"},
                "patch_source": {"type": "string"},
            },
            "required": ["worker", "patch_source"],
        },
    },
    {
        "name": "verify_process_health",
        "description": "Check PID continuity and heap consistency of a worker.",
        "inputSchema": {
            "type": "object",
            "properties": {"worker": {"type": "string"}},
            "required": ["worker"],
        },
    },
    {
        "name": "inspect_memory_registers",
        "description": "Return the register file, execution pointer, call-stack offsets and shared-memory heap frame of the worker's latest crash (or current heap frame).",
        "inputSchema": {
            "type": "object",
            "properties": {"worker": {"type": "string"}},
            "required": ["worker"],
        },
    },
]


def tool_read_crash_dump(worker_name: str) -> Dict[str, Any]:
    w = get_or_create_worker(worker_name)
    dump = w.latest_crash_dump
    if not dump:
        return {"status": "no_crash", "worker": worker_name, "pid": w.pid}
    return dump.to_dict()


def tool_inspect_memory_registers(worker_name: str) -> Dict[str, Any]:
    w = get_or_create_worker(worker_name)
    dump = w.latest_crash_dump
    if dump:
        return {
            "worker": worker_name,
            "pid": w.pid,
            "registers": dump.registers,
            "execution_pointer": dump.execution_pointer,
            "call_stack": dump.call_stack,
            "heap_snapshot": dump.heap_snapshot,
            "quarantined": w.quarantined,
        }
    return {
        "worker": worker_name,
        "pid": w.pid,
        "registers": {"rip": hex(0x7FFF0000), "rsp": hex(id(w))},
        "execution_pointer": hex(0x7FFF0000),
        "call_stack": [],
        "heap_snapshot": copy.deepcopy(w.state),
        "quarantined": w.quarantined,
    }


def tool_inject_hotpatch(worker_name: str, patch_source: str) -> Dict[str, Any]:
    w = get_or_create_worker(worker_name)
    dump = w.latest_crash_dump
    if not dump:
        raise ValueError(f"Worker {worker_name} has no prior crash dump to hotpatch")

    faulting_key = dump.faulting_key
    state_before = copy.deepcopy(w.state)
    pid_before = w.pid

    # Step 1: Sandbox validation and execution
    limits = load_limits()
    validate_patch(patch_source, limits)
    patched_state = execute_patch_sandboxed(patch_source, state_before, limits)

    # Step 2: Ensure only faulting key is modified
    for k, v in state_before.items():
        if k != faulting_key:
            if k not in patched_state or patched_state[k] != v:
                raise ValueError(f"Hotpatch modified unpermitted non-faulting key '{k}'")

    # Step 3: Run post_reanimation_verify invariants
    drift = heap_drift_bytes(state_before, patched_state)
    tolerances = load_tolerances()
    if drift > tolerances["epsilon_bytes"]:
        w.quarantined = True
        return {
            "status": "failed_verification",
            "reason": f"Heap drift {drift} bytes exceeds epsilon {tolerances['epsilon_bytes']}",
            "quarantined": True,
        }

    # Apply in-process
    w.state = patched_state
    w.heap.write_payload(w.state)
    w.latest_crash_dump = None
    w.reanimation_count += 1

    return {
        "status": "success",
        "worker": worker_name,
        "pid": w.pid,
        "pid_preserved": (w.pid == pid_before),
        "drift_bytes": drift,
        "patched_key": faulting_key,
        "reanimations": w.reanimation_count,
    }


def tool_verify_process_health(worker_name: str) -> Dict[str, Any]:
    w = get_or_create_worker(worker_name)
    heap_valid = False
    try:
        read_back = w.heap.read_payload()
        heap_valid = (read_back == w.state)
    except Exception:
        heap_valid = False

    return {
        "worker": worker_name,
        "pid": w.pid,
        "alive": True,
        "quarantined": w.quarantined,
        "heap_consistent": heap_valid,
        "faults": w.fault_count,
        "reanimations": w.reanimation_count,
        "has_crash_dump": (w.latest_crash_dump is not None),
    }


def dispatch_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Any:
    worker = arguments.get("worker", "session-worker")
    if tool_name == "read_crash_dump":
        return tool_read_crash_dump(worker)
    elif tool_name == "inspect_memory_registers":
        return tool_inspect_memory_registers(worker)
    elif tool_name == "inject_hotpatch":
        patch_src = arguments.get("patch_source", "")
        return tool_inject_hotpatch(worker, patch_src)
    elif tool_name == "verify_process_health":
        return tool_verify_process_health(worker)
    else:
        raise ValueError(f"Unknown MCP tool: {tool_name}")


def handle_json_rpc(request: Dict[str, Any]) -> Dict[str, Any]:
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS_SPEC}}
    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            res = dispatch_tool_call(tool_name, arguments)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(res)}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}
    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method {method} not found"}}


def main() -> None:
    """CLI loop reading newline-delimited JSON-RPC from stdin."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_json_rpc(req)
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
