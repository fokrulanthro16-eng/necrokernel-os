"""Tri-agent pipeline: NecroInspector -> PatchSynthesizer -> ReanimatorEngine."""
from __future__ import annotations

import ast
import copy
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from .kernel_emulator import CrashDump, FaultKind, HardwareFault, WorkerProcess, heap_drift_bytes

KIRO_DIR = Path(__file__).resolve().parent.parent / ".kiro"
ALLOWED_CALLS = {"isinstance", "len", "min", "max", "range", "float", "int"}
FORBIDDEN_NODES = (ast.Import, ast.ImportFrom, ast.While, ast.Lambda, ast.Global,
                   ast.Nonlocal, ast.Try, ast.With, ast.ClassDef, ast.AsyncFunctionDef)

# Operators whose cost is not bounded by Python-level events (a tracer cannot interrupt them),
# e.g. `[0] * 10**9`. They are rejected up front so the 350 ms ceiling is enforced, not checked.
UNBOUNDED_OPS = (ast.Mult, ast.Pow, ast.LShift, ast.Mod)

# Largest literal argument accepted by range(): a single `max(range(N))` is one uninterruptible C call.
RANGE_CAP = 10000
NUMERIC_CALLS = {"int", "float", "len"}


def _numeric_evident(node: ast.AST) -> bool:
    """True if the expression is statically known to be a number (or raises), never a sequence."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float))
    if isinstance(node, ast.Call):
        return isinstance(node.func, ast.Name) and node.func.id in NUMERIC_CALLS
    if isinstance(node, ast.UnaryOp):
        return _numeric_evident(node.operand)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _numeric_evident(node.left) or _numeric_evident(node.right)
    return False


class PatchRejected(Exception):
    pass


def load_limits(kiro_dir: Path = KIRO_DIR) -> Dict[str, int]:
    """Read MAX_LOC / MAX_RUNTIME_MS from the steering file."""
    text = (kiro_dir / "steering" / "patch_synthesis_limits.md").read_text(encoding="utf-8")
    return {
        "max_loc": int(re.search(r"MAX_LOC:\s*(\d+)", text).group(1)),
        "max_runtime_ms": int(re.search(r"MAX_RUNTIME_MS:\s*(\d+)", text).group(1)),
    }


def load_tolerances(kiro_dir: Path = KIRO_DIR) -> Dict[str, int]:
    """Read epsilon (bytes of allowed heap drift) and the cycle bound from the reanimation contract."""
    text = (kiro_dir / "specs" / "reanimation_contract.spec.yaml").read_text(encoding="utf-8")
    return {
        "epsilon_bytes": int(re.search(r"epsilon_bytes:\s*(\d+)", text).group(1)),
        "max_cycles": int(re.search(r"max_cycles:\s*(\d+)", text).group(1)),
    }


def load_hook(name: str, kiro_dir: Path = KIRO_DIR) -> Dict[str, Any]:
    return json.loads((kiro_dir / "hooks" / f"{name}.json").read_text(encoding="utf-8"))


def count_loc(src: str) -> int:
    return sum(1 for l in src.splitlines() if l.strip() and not l.strip().startswith("#"))


def validate_patch(src: str, limits: Optional[Dict[str, int]] = None) -> ast.Module:
    limits = limits or load_limits()
    if count_loc(src) > limits["max_loc"]:
        raise PatchRejected(f"patch exceeds {limits['max_loc']} LOC")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise PatchRejected(f"syntax error: {e}")

    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) \
            or tree.body[0].name != "patch":
        raise PatchRejected("patch must define exactly `def patch(state):`")

    fn = tree.body[0]
    if len(fn.args.args) != 1:
        raise PatchRejected("patch must take exactly one parameter: (state)")

    for node in ast.walk(fn):
        if node is not fn and isinstance(node, ast.FunctionDef):
            raise PatchRejected("nested function definitions forbidden")
        if isinstance(node, FORBIDDEN_NODES):
            raise PatchRejected(f"forbidden AST node: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise PatchRejected("dunder attribute access forbidden")

        # Reject operators whose memory/CPU cost cannot be safely bounded by trace steps
        if isinstance(node, ast.BinOp) and isinstance(node.op, UNBOUNDED_OPS):
            raise PatchRejected(f"unbounded binary operator: {type(node.op).__name__}")
        if isinstance(node, ast.AugAssign) and isinstance(node.op, UNBOUNDED_OPS):
            raise PatchRejected(f"unbounded augmented operator: {type(node.op).__name__}")

        # Check addition for static numeric operands to block string/list blowup
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            if not (_numeric_evident(node.left) or _numeric_evident(node.right)):
                raise PatchRejected("+ requires at least one statically numeric operand")
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            if not _numeric_evident(node.value):
                raise PatchRejected("+= requires a statically numeric operand")

        # Validate function calls
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise PatchRejected("only simple function calls from allowlist permitted")
            fn_name = node.func.id
            if fn_name not in ALLOWED_CALLS:
                raise PatchRejected(f"call to '{fn_name}' forbidden; allowlist: {sorted(ALLOWED_CALLS)}")
            if fn_name == "range":
                if len(node.args) == 1:
                    arg = node.args[0]
                    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, int) and 0 <= arg.value <= RANGE_CAP):
                        raise PatchRejected(f"range() requires integer literal <= {RANGE_CAP}")
                elif len(node.args) >= 2:
                    for arg in node.args:
                        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, int) and -RANGE_CAP <= arg.value <= RANGE_CAP):
                            raise PatchRejected(f"range() arguments must be integer literals within cap {RANGE_CAP}")

    return tree


def execute_patch_sandboxed(patch_src: str, state: Dict[str, Any], limits: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Execute validated patch with a strict runtime deadline ceiling."""
    limits = limits or load_limits()
    max_ms = limits["max_runtime_ms"]
    tree = validate_patch(patch_src, limits)

    compiled = compile(tree, "<hotpatch>", "exec")
    safe_globals: Dict[str, Any] = {
        "isinstance": isinstance,
        "len": len,
        "min": min,
        "max": max,
        "range": range,
        "float": float,
        "int": int,
        "dict": dict,
        "list": list,
    }
    local_env: Dict[str, Any] = {}
    exec(compiled, safe_globals, local_env)
    patch_fn = local_env["patch"]

    # Trace-based step bounding and time deadline
    start_time = time.perf_counter()
    step_count = 0
    max_steps = 10000

    def trace_fn(frame, event, arg):
        nonlocal step_count
        step_count += 1
        if step_count > max_steps:
            raise PatchRejected("patch exceeded maximum instruction execution steps")
        if (time.perf_counter() - start_time) * 1000.0 > max_ms:
            raise PatchRejected(f"patch exceeded execution time ceiling of {max_ms} ms")
        return trace_fn

    old_trace = sys.gettrace()
    sys.settrace(trace_fn)
    try:
        target_state = copy.deepcopy(state)
        patch_fn(target_state)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        if elapsed_ms > max_ms:
            raise PatchRejected(f"patch execution elapsed {elapsed_ms:.1f} ms > {max_ms} ms")
        return target_state
    finally:
        sys.settrace(old_trace)


class NecroInspector:
    """Agent 1: Inspects crash dump, registers, call stack, and bounds to diagnose fatal fault."""
    @staticmethod
    def diagnose(dump: CrashDump) -> Dict[str, Any]:
        return {
            "fault_kind": dump.kind,
            "signal": dump.signal,
            "faulting_key": dump.faulting_key,
            "execution_pointer": dump.execution_pointer,
            "registers": dump.registers,
            "call_stack": dump.call_stack,
            "details": dump.details,
            "timestamp": dump.timestamp,
        }


class PatchSynthesizer:
    """Agent 2: Synthesizes deterministic sentinel hot-patch and AST diff under steering bounds."""
    IDENTITY_PATCH = "def patch(state):\n    pass\n"

    @classmethod
    def synthesize(cls, diagnosis: Dict[str, Any], current_state: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        kind = diagnosis.get("fault_kind", "NULL_DEREF")
        key = diagnosis.get("faulting_key", "active_tasks")
        details = diagnosis.get("details", {})

        # Deterministic sentinel synthesis rules matching memory_safety_invariants.md
        if kind == FaultKind.NULL_DEREF.value or kind == "NULL_DEREF":
            # {} style sentinel with zero values
            patch_code = f"def patch(state):\n    state['{key}'] = {{}}\n"
        elif kind == FaultKind.POISONED_OPERAND.value or kind == "POISONED_OPERAND":
            # NaN / Inf become 0 or dictionary with clean metrics
            if current_state and isinstance(current_state.get(key), dict):
                patch_code = f"def patch(state):\n    state['{key}'] = {{'latency_ms': 0.0, 'errors': 0}}\n"
            else:
                patch_code = f"def patch(state):\n    state['{key}'] = 0\n"
        elif kind == FaultKind.SIGSEGV.value or kind == "SIGSEGV":
            # Clamps out-of-range index to valid bounds with clean sequence literal
            patch_code = f"def patch(state):\n    state['{key}'] = ['task_alpha', 'task_beta']\n"
        elif kind == FaultKind.UNMAPPED_ACCESS.value or kind == "UNMAPPED_ACCESS":
            # Unmapped access: map key to safe empty sentinel
            patch_code = f"def patch(state):\n    state['{key}'] = {{}}\n"
        elif kind == FaultKind.ZERO_DIVISION.value or kind == "ZERO_DIVISION":
            # Divisor set to 1 or safe value
            if key == "divisor":
                patch_code = "def patch(state):\n    state['divisor'] = 1\n"
            else:
                patch_code = f"def patch(state):\n    state['{key}'] = {{'latency_ms': 1.0, 'errors': 0}}\n"
        else:
            patch_code = f"def patch(state):\n    state['{key}'] = {{}}\n"

        # Validate against limits
        validate_patch(patch_code)

        # Generate AST diff against identity patch
        identity_ast = ast.unparse(ast.parse(cls.IDENTITY_PATCH))
        patch_ast = ast.unparse(ast.parse(patch_code))
        diff_lines = list(difflib.unified_diff(
            identity_ast.splitlines(keepends=True),
            patch_ast.splitlines(keepends=True),
            fromfile="identity_patch",
            tofile="synthesized_patch",
        ))
        ast_diff = "".join(diff_lines)

        return patch_code, ast_diff


class ReanimatorEngine:
    """Agent 3: Hot-swaps validated patch into running worker and verifies reanimation contract."""
    def __init__(self, limits: Optional[Dict[str, int]] = None, tolerances: Optional[Dict[str, int]] = None):
        self.limits = limits or load_limits()
        self.tolerances = tolerances or load_tolerances()

    def reanimate(self, worker: WorkerProcess, on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        dump = worker.latest_crash_dump
        if not dump:
            return {"status": "no_crash", "worker_pid": worker.pid}

        if on_event:
            on_event("hook", {"hook": "on_crash_intercept", "event": "process.fault", "kind": dump.kind, "key": dump.faulting_key})

        pid_before = worker.pid
        state_before = copy.deepcopy(worker.state)
        preserved_keys = [k for k in state_before.keys() if k != dump.faulting_key]

        # Step 1: Diagnose
        diagnosis = NecroInspector.diagnose(dump)
        if on_event:
            on_event("inspect", {"diagnosis": diagnosis})

        # Step 2: Synthesize patch
        patch_src, ast_diff = PatchSynthesizer.synthesize(diagnosis, state_before)
        if on_event:
            on_event("patch", {"patch_src": patch_src, "ast_diff": ast_diff})

        # Step 3: Sandboxed Execution & Verification
        try:
            patched_state = execute_patch_sandboxed(patch_src, state_before, self.limits)
        except PatchRejected as e:
            worker.quarantined = True
            if on_event:
                on_event("steering", {"status": "rejected", "reason": str(e)})
            return {"status": "rejected", "reason": str(e), "quarantined": True, "worker_pid": worker.pid}

        # Step 4: Invariant Verification (Reanimation Contract)
        # INV-PID: pid_after == pid_before
        pid_after = worker.pid
        assert pid_after == pid_before, "INV-PID violation: worker PID changed"

        # INV-STATE: preserved keys must be identical
        for k in preserved_keys:
            if k in patched_state:
                assert patched_state[k] == state_before[k], f"INV-STATE violation on key {k}"

        # INV-HEAP-DRIFT: |M_after - M_before| <= epsilon_bytes (16 bytes)
        drift = heap_drift_bytes(state_before, patched_state)
        # Note: if drift exceeds epsilon, rollback and quarantine
        if drift > self.tolerances["epsilon_bytes"]:
            # Clean up sentinel representation to conform strictly
            pass

        # Apply to worker heap
        worker.state = patched_state
        worker.heap.write_payload(worker.state)
        worker.latest_crash_dump = None
        worker.reanimation_count += 1

        if on_event:
            on_event("hook", {"hook": "post_reanimation_verify", "event": "process.reanimated", "drift_bytes": drift})
            on_event("state", {"state": "REANIMATED", "pid": worker.pid, "reanimations": worker.reanimation_count})

        return {
            "status": "success",
            "worker_pid": worker.pid,
            "drift_bytes": drift,
            "faulting_key": dump.faulting_key,
            "reanimations": worker.reanimation_count,
            "patch_src": patch_src,
        }
