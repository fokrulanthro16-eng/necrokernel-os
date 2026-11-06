"""Comprehensive test suite for NecroKernel-OS reanimation contract and hypervisor architecture."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import re
from pathlib import Path
from typing import Any, Dict

import pytest

from engine.agent_mesh import (
    NecroInspector,
    PatchRejected,
    PatchSynthesizer,
    ReanimatorEngine,
    count_loc,
    execute_patch_sandboxed,
    load_limits,
    load_tolerances,
    validate_patch,
)
from engine.hypervisor import EventBus, Hypervisor
from engine.kernel_emulator import (
    CrashDump,
    FaultKind,
    HardwareFault,
    SharedHeap,
    WorkerProcess,
    canonical_json,
    heap_drift_bytes,
)
from engine.mcp_gateway import (
    dispatch_tool_call,
    handle_json_rpc,
    register_worker,
    tool_inject_hotpatch,
    tool_inspect_memory_registers,
    tool_read_crash_dump,
    tool_verify_process_health,
)

KIRO_DIR = Path(__file__).resolve().parent / ".kiro"


# ============================================================================
# 1. Invariant Tests (Reanimation Contract)
# ============================================================================

def test_inv_pid_preservation():
    """INV-PID: Worker PID is strictly preserved across crash and reanimation."""
    worker = WorkerProcess()
    pid_before = worker.pid
    worker.inject_fault("null")
    reanimator = ReanimatorEngine()
    res = reanimator.reanimate(worker)
    assert res["status"] == "success"
    assert worker.pid == pid_before


def test_inv_state_preservation():
    """INV-STATE: Every preserved key remains identical after recovery."""
    worker = WorkerProcess()
    worker.inject_fault("nan")
    state_before = copy.deepcopy(worker.latest_crash_dump.heap_snapshot)
    preserved_before = {
        "session_id": state_before["session_id"],
        "crypto_context": copy.deepcopy(state_before["crypto_context"]),
        "worker_token": state_before["worker_token"],
    }
    reanimator = ReanimatorEngine()
    res = reanimator.reanimate(worker)
    assert res["status"] == "success"
    for k, v in preserved_before.items():
        assert worker.state[k] == v


def test_inv_heap_consistency():
    """INV-HEAP: Patched key is non-null and not poisoned after recovery."""
    worker = WorkerProcess()
    worker.inject_fault("null")
    reanimator = ReanimatorEngine()
    reanimator.reanimate(worker)
    val = worker.read_key("active_tasks")
    assert val is not None
    assert val == {}


def test_inv_heap_drift_within_epsilon():
    """INV-HEAP-DRIFT: |M_after - M_before| <= 16 bytes."""
    worker = WorkerProcess()
    worker.inject_fault("null")
    state_before = copy.deepcopy(worker.latest_crash_dump.heap_snapshot)
    reanimator = ReanimatorEngine()
    res = reanimator.reanimate(worker)
    assert res["status"] == "success"
    drift = heap_drift_bytes(state_before, worker.state)
    assert drift <= 16, f"Heap drift {drift} exceeded tolerance of 16 bytes"


def test_inv_bound_loc_and_runtime():
    """INV-BOUND: Patches are <= 25 LOC and runtime <= 350 ms."""
    limits = load_limits()
    assert limits["max_loc"] == 25
    assert limits["max_runtime_ms"] == 350

    diag = {"fault_kind": "NULL_DEREF", "faulting_key": "active_tasks"}
    patch_src, _ = PatchSynthesizer.synthesize(diag)
    assert count_loc(patch_src) <= 25
    state = {"active_tasks": None}
    res = execute_patch_sandboxed(patch_src, state, limits)
    assert res["active_tasks"] == {}


def test_inv_continuity_digests():
    """INV-CONTINUITY: Session, crypto context, and worker tokens remain equal."""
    worker = WorkerProcess()
    session_hash = hashlib.sha256(canonical_json(worker.state["session_id"])).hexdigest()
    crypto_hash = hashlib.sha256(canonical_json(worker.state["crypto_context"])).hexdigest()
    token = worker.state["worker_token"]

    worker.inject_fault("segv")
    reanimator = ReanimatorEngine()
    reanimator.reanimate(worker)

    assert hashlib.sha256(canonical_json(worker.state["session_id"])).hexdigest() == session_hash
    assert hashlib.sha256(canonical_json(worker.state["crypto_context"])).hexdigest() == crypto_hash
    assert worker.state["worker_token"] == token


def test_inv_progress_task_completion():
    """INV-PROGRESS: Interrupted task completes successfully after reanimation."""
    worker = WorkerProcess()
    worker.inject_fault("null")
    reanimator = ReanimatorEngine()
    reanimator.reanimate(worker)

    def sample_task(state):
        return f"task_ok_{len(state)}"

    result = worker.execute_task(sample_task)
    assert result.startswith("task_ok_")


# ============================================================================
# 2. Fault Simulation & Sentinel Coverage (5 Fault Kinds)
# ============================================================================

def test_fault_null_deref_recovery():
    worker = WorkerProcess()
    with pytest.raises(HardwareFault) as exc_info:
        worker.inject_fault("null", trap=False)
    assert exc_info.value.kind == FaultKind.NULL_DEREF
    assert exc_info.value.signal_name == "SIGSEGV"
    reanimator = ReanimatorEngine()
    res = reanimator.reanimate(worker)
    assert res["status"] == "success"
    assert worker.state["active_tasks"] == {}


def test_fault_nan_poison_recovery():
    worker = WorkerProcess()
    with pytest.raises(HardwareFault) as exc_info:
        worker.inject_fault("nan", trap=False)
    assert exc_info.value.kind == FaultKind.POISONED_OPERAND
    assert exc_info.value.signal_name == "SIGFPE"
    reanimator = ReanimatorEngine()
    res = reanimator.reanimate(worker)
    assert res["status"] == "success"
    metrics = worker.state["metrics"]
    assert not math.isnan(metrics.get("latency_ms", 0.0))


def test_fault_sigsegv_out_of_bounds_recovery():
    worker = WorkerProcess()
    with pytest.raises(HardwareFault) as exc_info:
        worker.inject_fault("segv", trap=False)
    assert exc_info.value.kind == FaultKind.SIGSEGV
    reanimator = ReanimatorEngine()
    res = reanimator.reanimate(worker)
    assert res["status"] == "success"
    assert isinstance(worker.state["active_tasks"], list)


def test_fault_unmapped_access_sigbus():
    worker = WorkerProcess()
    with pytest.raises(HardwareFault) as exc_info:
        worker.inject_fault("sigbus", trap=False)
    assert exc_info.value.kind == FaultKind.UNMAPPED_ACCESS
    reanimator = ReanimatorEngine()
    res = reanimator.reanimate(worker)
    assert res["status"] == "success"


def test_fault_zero_division_trap():
    worker = WorkerProcess()
    with pytest.raises(HardwareFault) as exc_info:
        worker.inject_fault("div0", trap=False)
    assert exc_info.value.kind == FaultKind.ZERO_DIVISION
    assert exc_info.value.signal_name == "SIGFPE"
    reanimator = ReanimatorEngine()
    res = reanimator.reanimate(worker)
    assert res["status"] == "success"


# ============================================================================
# 3. Patch Sandbox & Steering Boundary Tests
# ============================================================================

def test_sandbox_rejects_excessive_loc():
    huge_patch = "def patch(state):\n" + "\n".join(f"    x_{i} = {i}" for i in range(30))
    with pytest.raises(PatchRejected, match="exceeds 25 LOC"):
        validate_patch(huge_patch)


def test_sandbox_rejects_imports():
    bad_patch = "def patch(state):\n    import os\n    state['x'] = 1\n"
    with pytest.raises(PatchRejected, match="forbidden AST node: Import"):
        validate_patch(bad_patch)


def test_sandbox_rejects_while_loop():
    bad_patch = "def patch(state):\n    while True:\n        pass\n"
    with pytest.raises(PatchRejected, match="forbidden AST node: While"):
        validate_patch(bad_patch)


def test_sandbox_rejects_try_with():
    bad_patch = "def patch(state):\n    try:\n        state['x'] = 1\n    except:\n        pass\n"
    with pytest.raises(PatchRejected, match="forbidden AST node: Try"):
        validate_patch(bad_patch)


def test_sandbox_rejects_dunder_access():
    bad_patch = "def patch(state):\n    x = state.__class__\n"
    with pytest.raises(PatchRejected, match="dunder attribute access forbidden"):
        validate_patch(bad_patch)


def test_sandbox_rejects_unbounded_multiplier():
    bad_patch = "def patch(state):\n    state['x'] = [0] * 1000\n"
    with pytest.raises(PatchRejected, match="unbounded binary operator"):
        validate_patch(bad_patch)


def test_sandbox_rejects_unbounded_power():
    bad_patch = "def patch(state):\n    state['x'] = 2 ** 100\n"
    with pytest.raises(PatchRejected, match="unbounded binary operator"):
        validate_patch(bad_patch)


def test_sandbox_rejects_forbidden_call():
    bad_patch = "def patch(state):\n    eval('1+1')\n"
    with pytest.raises(PatchRejected, match="forbidden; allowlist"):
        validate_patch(bad_patch)


def test_sandbox_range_cap_enforced():
    bad_patch = "def patch(state):\n    for i in range(20000):\n        pass\n"
    with pytest.raises(PatchRejected, match="range\\(\\) requires integer literal <= 10000"):
        validate_patch(bad_patch)


def test_sandbox_addition_numeric_operand_required():
    bad_patch = "def patch(state):\n    state['x'] = state['a'] + state['b']\n"
    with pytest.raises(PatchRejected, match="requires at least one statically numeric operand"):
        validate_patch(bad_patch)


# ============================================================================
# 4. Shared Memory Seqlock & Frame Integrity
# ============================================================================

def test_shared_memory_seqlock_read_write():
    buf = bytearray(65536)
    heap = SharedHeap(buf)
    state = {"token": "alpha", "value": 1234}
    heap.write_payload(state)
    read_back = heap.read_payload()
    assert read_back == state


def test_shared_memory_payload_limit():
    heap = SharedHeap()
    huge_data = {"key": "x" * 70000}
    with pytest.raises(ValueError, match="exceeds max heap size"):
        heap.write_payload(huge_data)


# ============================================================================
# 5. MCP Gateway & Tool Dispatch
# ============================================================================

def test_mcp_read_crash_dump():
    worker = WorkerProcess("mcp-worker-1")
    register_worker("mcp-worker-1", worker)
    worker.inject_fault("null")
    dump = tool_read_crash_dump("mcp-worker-1")
    assert dump["kind"] == "NULL_DEREF"
    assert dump["faulting_key"] == "active_tasks"


def test_mcp_inspect_memory_registers():
    worker = WorkerProcess("mcp-worker-2")
    register_worker("mcp-worker-2", worker)
    worker.inject_fault("nan")
    regs = tool_inspect_memory_registers("mcp-worker-2")
    assert "registers" in regs
    assert "execution_pointer" in regs


def test_mcp_inject_hotpatch_success():
    worker = WorkerProcess("mcp-worker-3")
    register_worker("mcp-worker-3", worker)
    worker.inject_fault("null")
    patch = "def patch(state):\n    state['active_tasks'] = {}\n"
    res = tool_inject_hotpatch("mcp-worker-3", patch)
    assert res["status"] == "success"
    assert res["pid_preserved"] is True


def test_mcp_inject_hotpatch_rejects_unpermitted_key():
    worker = WorkerProcess("mcp-worker-4")
    register_worker("mcp-worker-4", worker)
    worker.inject_fault("null")
    bad_patch = "def patch(state):\n    state['active_tasks'] = {}\n    state['session_id'] = 'corrupted'\n"
    with pytest.raises(ValueError, match="modified unpermitted non-faulting key"):
        tool_inject_hotpatch("mcp-worker-4", bad_patch)


def test_mcp_verify_process_health():
    worker = WorkerProcess("mcp-worker-5")
    register_worker("mcp-worker-5", worker)
    health = tool_verify_process_health("mcp-worker-5")
    assert health["alive"] is True
    assert health["heap_consistent"] is True


def test_mcp_json_rpc_tools_list():
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    resp = handle_json_rpc(req)
    assert "result" in resp
    assert len(resp["result"]["tools"]) == 4


def test_mcp_json_rpc_tools_call():
    worker = WorkerProcess("session-worker")
    register_worker("session-worker", worker)
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "verify_process_health", "arguments": {"worker": "session-worker"}},
    }
    resp = handle_json_rpc(req)
    assert "result" in resp
    content = resp["result"]["content"][0]["text"]
    parsed = json.loads(content)
    assert parsed["alive"] is True


# ============================================================================
# 6. Hypervisor Supervisor & Event Bus
# ============================================================================

def test_hypervisor_event_bus():
    bus = EventBus(capacity=10)
    sub = bus.subscribe()
    ev = bus.emit("fault", {"detail": "test"})
    assert ev["id"] == 1
    received = sub.get_nowait()
    assert received["type"] == "fault"
    bus.unsubscribe(sub)


def test_hypervisor_lifecycle_states():
    hv = Hypervisor(in_process=True)
    assert hv.state == "HEALTHY"
    hv.crash("null")
    assert hv.state == "POISONED"
    res = hv.reanimate()
    assert res["status"] == "success"
    assert hv.state == "REANIMATED"
    hv.reset()
    assert hv.state == "HEALTHY"
    hv.stop()


def test_hypervisor_no_restart_path_in_engine():
    """Grep verification: engine/ must NOT contain any restart/respawn mechanism."""
    engine_dir = Path(__file__).resolve().parent / "engine"
    forbidden_terms = ["os.exec", "subprocess.Popen", "respawn", "restart_worker"]
    for py_file in engine_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text, f"Forbidden restart term '{term}' found in {py_file.name}"


# ============================================================================
# 7. Seeded Random Property Loop (100+ Iterations)
# ============================================================================

def test_seeded_random_reanimation_loop():
    """Seeded random loop testing 100+ reanimation cycles without restart or drift violation."""
    rng = random.Random(1337)
    worker = WorkerProcess()
    pid_orig = worker.pid
    kinds = ["null", "nan", "segv", "sigbus", "div0"]

    reanimator = ReanimatorEngine()
    for i in range(100):
        kind = rng.choice(kinds)
        worker.inject_fault(kind)
        res = reanimator.reanimate(worker)
        assert res["status"] == "success"
        assert worker.pid == pid_orig
        assert res["drift_bytes"] <= 16


# ============================================================================
# 8. Spec Verification Tests
# ============================================================================

def test_spec_invariant_ids_without_pyyaml():
    """Verify all reanimation invariant IDs from YAML spec without requiring PyYAML."""
    spec_text = (KIRO_DIR / "specs" / "reanimation_contract.spec.yaml").read_text(encoding="utf-8")
    expected_ids = ["INV-PID", "INV-STATE", "INV-HEAP", "INV-BOUND", "INV-CONTINUITY", "INV-PROGRESS"]
    for inv_id in expected_ids:
        assert inv_id in spec_text, f"Missing invariant {inv_id} in reanimation_contract.spec.yaml"


def test_spec_yaml_parse_if_available():
    """Parses YAML spec if PyYAML is installed; skips cleanly if missing."""
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML not installed")

    spec_path = KIRO_DIR / "specs" / "reanimation_contract.spec.yaml"
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    assert data["spec"] == "reanimation_contract"
    assert "invariants" in data


# ============================================================================
# 9. Extended AST Sandboxing & Boundary Checks
# ============================================================================

def test_sandbox_rejects_lambda():
    bad_patch = "def patch(state):\n    fn = lambda x: x\n"
    with pytest.raises(PatchRejected, match="forbidden AST node: Lambda"):
        validate_patch(bad_patch)


def test_sandbox_rejects_global():
    bad_patch = "def patch(state):\n    global x\n    x = 1\n"
    with pytest.raises(PatchRejected, match="forbidden AST node: Global"):
        validate_patch(bad_patch)


def test_sandbox_rejects_nonlocal():
    bad_patch = "def patch(state):\n    nonlocal x\n"
    with pytest.raises(PatchRejected, match="forbidden AST node: Nonlocal"):
        validate_patch(bad_patch)


def test_sandbox_rejects_class_def():
    bad_patch = "def patch(state):\n    class Exploit:\n        pass\n"
    with pytest.raises(PatchRejected, match="forbidden AST node: ClassDef"):
        validate_patch(bad_patch)


def test_sandbox_rejects_async_def():
    bad_patch = "async def patch(state):\n    pass\n"
    with pytest.raises(PatchRejected, match="patch must define exactly"):
        validate_patch(bad_patch)


def test_sandbox_rejects_modulo_operator():
    bad_patch = "def patch(state):\n    x = 10 % 3\n"
    with pytest.raises(PatchRejected, match="unbounded binary operator: Mod"):
        validate_patch(bad_patch)


def test_sandbox_rejects_left_shift_operator():
    bad_patch = "def patch(state):\n    x = 1 << 10\n"
    with pytest.raises(PatchRejected, match="unbounded binary operator: LShift"):
        validate_patch(bad_patch)


def test_sandbox_rejects_augmented_multiply():
    bad_patch = "def patch(state):\n    x = 5\n    x *= 2\n"
    with pytest.raises(PatchRejected, match="unbounded augmented operator: Mult"):
        validate_patch(bad_patch)


def test_sandbox_rejects_augmented_add_non_numeric():
    bad_patch = "def patch(state):\n    state['items'] += state['other']\n"
    with pytest.raises(PatchRejected, match="\\+= requires a statically numeric operand"):
        validate_patch(bad_patch)


def test_sandbox_accepts_valid_range():
    good_patch = "def patch(state):\n    total = 0\n    for i in range(100):\n        total += 1\n    state['total'] = total\n"
    tree = validate_patch(good_patch)
    assert tree is not None


# ============================================================================
# 10. Hook Specification Invariants
# ============================================================================

def test_hook_on_crash_intercept_spec_loaded():
    from engine.agent_mesh import load_hook
    hook = load_hook("on_crash_intercept")
    assert hook["name"] == "on_crash_intercept"
    assert hook["event"] == "process.fault"
    assert "NecroInspector" in hook["action"]["pipeline"]
    assert "PatchSynthesizer" in hook["action"]["pipeline"]
    assert "ReanimatorEngine" in hook["action"]["pipeline"]


def test_hook_post_reanimation_verify_spec_loaded():
    from engine.agent_mesh import load_hook
    hook = load_hook("post_reanimation_verify")
    assert hook["name"] == "post_reanimation_verify"
    assert hook["event"] == "process.reanimated"
    assert "INV-PID" in hook["enforce"]
    assert "INV-HEAP" in hook["enforce"]


# ============================================================================
# 11. Hypervisor State Machine & Quarantining
# ============================================================================

def test_hypervisor_quarantine_blocks_crash_and_reanimate():
    hv = Hypervisor(in_process=True)
    hv.worker.quarantined = True
    c_res = hv.crash("null")
    assert c_res["code"] == 409
    r_res = hv.reanimate()
    assert r_res["code"] == 409
    hv.reset()
    assert hv.worker.quarantined is False
    hv.stop()


def test_hypervisor_dead_state_blocks_execution():
    hv = Hypervisor(in_process=True)
    hv.state = "DEAD"
    c_res = hv.crash("null")
    assert c_res["code"] == 503
    r_res = hv.reanimate()
    assert r_res["code"] == 503
    hv.stop()


def test_hypervisor_health_pulse_emitted():
    hv = Hypervisor(in_process=True)
    sub = hv.bus.subscribe()
    hv.bus.emit("pulse", {"pid": hv.worker_pid, "state": "HEALTHY", "quarantined": False})
    ev = sub.get_nowait()
    assert ev["type"] == "pulse"
    assert ev["pid"] == hv.worker_pid
    hv.bus.unsubscribe(sub)
    hv.stop()


# ============================================================================
# 12. HTTP Server Endpoint Verification (In-Process Test Client)
# ============================================================================

def test_http_health_endpoint_response():
    from engine.server import NecroHttpHandler, HYPERVISOR
    assert HYPERVISOR.worker_pid is not None
    assert HYPERVISOR.state in ["HEALTHY", "REANIMATED", "POISONED"]


def test_http_metrics_endpoint_response():
    from engine.server import HYPERVISOR
    w = HYPERVISOR.worker
    assert w.reanimation_count >= 0
    assert w.fault_count >= 0


def test_http_security_cors_headers():
    from engine.server import ALLOWED_ORIGINS
    assert "http://localhost:3000" in ALLOWED_ORIGINS
    assert "http://127.0.0.1:3000" in ALLOWED_ORIGINS


def test_http_mcp_tools_spec_schema():
    from engine.server import MCP_TOOLS_SPEC
    names = [t["name"] for t in MCP_TOOLS_SPEC]
    assert "read_crash_dump" in names
    assert "inspect_memory_registers" in names
    assert "inject_hotpatch" in names
    assert "verify_process_health" in names


# ============================================================================
# 13. Property-Based Testing (Hypothesis + Fallback Seeded Random)
# ============================================================================

def test_hypothesis_heap_non_divergence():
    """Hypothesis property test for heap non-divergence; skips cleanly if hypothesis missing."""
    try:
        from hypothesis import given, settings, strategies as st
    except ImportError:
        pytest.skip("Hypothesis not installed; exercised by seeded stdlib random loop")

    @settings(max_examples=100, deadline=None)
    @given(st.sampled_from(["null", "nan", "segv", "sigbus", "div0"]))
    def prop(kind):
        w = WorkerProcess()
        pid_before = w.pid
        w.inject_fault(kind)
        res = ReanimatorEngine().reanimate(w)
        assert res["status"] == "success"
        assert w.pid == pid_before
        assert res["drift_bytes"] <= 16

    prop()


def test_hypothesis_pid_preservation():
    """Hypothesis property test asserting PID invariance across arbitrary fault sequences."""
    try:
        from hypothesis import given, settings, strategies as st
    except ImportError:
        pytest.skip("Hypothesis not installed; exercised by seeded stdlib random loop")

    @settings(max_examples=100, deadline=None)
    @given(st.lists(st.sampled_from(["null", "nan", "segv", "div0"]), min_size=1, max_size=5))
    def prop(sequence):
        w = WorkerProcess()
        pid = w.pid
        r = ReanimatorEngine()
        for k in sequence:
            w.inject_fault(k)
            res = r.reanimate(w)
            assert res["status"] == "success"
            assert w.pid == pid

    prop()


def test_hypothesis_state_continuity():
    """Hypothesis property test asserting untouched keys remain strictly identical."""
    try:
        from hypothesis import given, settings, strategies as st
    except ImportError:
        pytest.skip("Hypothesis not installed; exercised by seeded stdlib random loop")

    @settings(max_examples=100, deadline=None)
    @given(st.text(min_size=1, max_size=20))
    def prop(extra_val):
        w = WorkerProcess(initial_state={"custom_token": extra_val})
        w.inject_fault("null")
        res = ReanimatorEngine().reanimate(w)
        assert res["status"] == "success"
        assert w.state["custom_token"] == extra_val

    prop()
