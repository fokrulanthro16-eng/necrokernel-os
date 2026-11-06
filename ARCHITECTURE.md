# NecroKernel-OS Architecture

This document describes what the code in this repository does. Where a thing is simulated or only planned, it says so.

## 1. Process model

| Component | Where | Real or simulated |
|-----------|-------|-------------------|
| Worker | `engine/worker_daemon.py`, started with `multiprocessing` (spawn); own OS PID | Real process |
| Supervisor | `engine/hypervisor.py`; monitor thread calls `os.waitpid(pid, WNOHANG)` and sends health pulses | Real |
| IPC | `multiprocessing.Pipe` (ops: exec task, apply patch, dump, pulse) | Real |
| Heap | `multiprocessing.shared_memory`, 64 KiB (`SHM_SIZE = 65536`) | Real shared memory |
| Invalid memory access | Checked accessors on the heap decide an access is "out of range" or "null" | **Simulated** |
| Registers / execution pointer | Derived from the Python frame at the fault | **Simulated** |
| eBPF telemetry interceptor | No code in this repo | **Planned / conceptual** |

The supervisor never restarts the worker. `engine/` contains no restart path (a test greps for it) and a worker killed from outside is detected by `waitpid` and reported, not respawned.

## 2. POSIX signal handling

- The worker installs Python-level handlers for `SIGSEGV`, `SIGBUS` and `SIGFPE` (`signal.signal`).
- A checked accessor that detects a bad access records context (kind, key, bounds) and then calls `os.kill(os.getpid(), SIG)`: a **real signal, sent only to the worker's own PID**. Nothing ever signals another process.
- CPython runs the handler between bytecodes, in the interrupted frame. The handler raises a `HardwareFault` into that frame; the worker catches it at its task loop, writes a structured crash dump and keeps serving. If delivery is deferred, the accessor raises the same exception itself.
- A genuine hardware `SIGSEGV` (bad pointer dereference) cannot be resumed from Python: returning from the C-level handler re-executes the faulting instruction. That is why the invalid access is simulated and only the signal delivery is real.
- `ZeroDivisionError` is trapped as an ordinary exception and mapped to `SIGFPE` in the dump.

| Fault kind | Signal | Deterministic sentinel applied by the patch |
|------------|--------|---------------------------------------------|
| `NULL_DEREF` | SIGSEGV | `{}`-style sentinel with zero values |
| `POISONED_OPERAND` (NaN, inf) | SIGFPE | `0` |
| `SIGSEGV` index out of range (incl. negative) | SIGSEGV | clamp to last valid index |
| `UNMAPPED_ACCESS` | SIGBUS | clamp to last valid index |
| `ZERO_DIVISION` | SIGFPE | divisor `1` |

## 3. Shared memory segments

The heap is one JSON document in a `SharedMemory` block with an 8-byte header (`>II`: generation, payload length).

- Single writer (the worker) uses a **seqlock**: generation is made odd before the write and even after.
- Readers (the supervisor) read generation, payload, generation again and retry if they differ or are odd.
- Payloads larger than the segment (minus header) are refused.
- "Heap drift" is `|M_after - M_before|` where `M` is the byte length of the canonical (sorted-key, compact) JSON frame. The tolerance is `epsilon_bytes = 16` in `.kiro/specs/reanimation_contract.spec.yaml`.

## 4. Agent crew and hotpatching

1. `on_crash_intercept` hook (`.kiro/hooks/`) fires on `process.fault`.
2. **NecroInspector** reads the crash dump (kind, signal, field, bounds, poison operand) and produces a diagnosis.
3. **PatchSynthesizer** emits a `def patch(state):` source and an AST diff (`ast.unparse` + `difflib`) against the identity patch.
4. Sandbox validation (limits read from `.kiro/steering/patch_synthesis_limits.md`): at most 25 LOC, 350 ms ceiling, no imports/`while`/lambda/try/with/global/dunder, calls limited to `isinstance, len, min, max, range, float, int`, operators `*`, `**`, `<<`, `%` rejected, `range()` only with integer literals up to 10000, `+`/`+=` need a statically numeric operand.
5. **Reanimator** hot-swaps the patch through the hypervisor. The worker validates it again and runs it in-process against only the faulting key(s); a rejected, timed-out or raising patch is rolled back.
6. `post_reanimation_verify` hook checks the invariants below. Failure quarantines the worker (no reboot); `POST /hv/reset` performs an audited release on the same PID.
7. The interrupted task is re-executed. At most `max_cycles = 8` fault/patch/verify cycles run per task.

## 5. Invariants (from `.kiro/specs/reanimation_contract.spec.yaml`)

| ID | Statement |
|----|-----------|
| INV-PID | `pid_after == pid_before` |
| INV-STATE | for every preserved key `k`: `state_after[k] == state_before[k]`, unless `k` is a patched key |
| INV-HEAP | for every patched key: not null and not poisoned after recovery |
| INV-HEAP-DRIFT | `abs(M_after - M_before) <= 16` bytes |
| INV-BOUND | `loc(patch) <= 25` and `elapsed_ms(patch) <= 350` |
| INV-CONTINUITY | session digest, crypto-context digest, counters and worker token unchanged except patched keys |
| INV-PROGRESS | the interrupted task returns a result on re-execution |

## 6. Verification: property-based testing status

`test_reanimation_cycle.py` contains two layers:

1. **Hypothesis property test** (`@settings(max_examples >= 100, deadline=None)`). It is written but **has never executed** in the authoring environment (Hypothesis could not be installed there); pytest reports it as skipped. Install `requirements.txt` and run it to get a real result.
2. **Seeded stdlib random loops** of 100+ iterations per invariant. These always run and are the only property-style evidence so far.

Last real run in the authoring sandbox: `60 passed, 2 skipped` (the skips are the Hypothesis test and the PyYAML spec-parse test). The `test_spec_invariant_ids_without_pyyaml` test covers spec IDs without PyYAML.

This is testing, not formal verification: nothing here is machine-checked proof.

## 7. HTTP surface

`engine/server.py` (stdlib, default `127.0.0.1:8000`, override bind with `NECRO_HOST`): `/health`, `/tools`, `/events` (SSE, max 16 streams), `/hv/state|crash|reanimate|reset`, `/rpc` (MCP-style). No authentication; POSTs require JSON content type, a localhost `Host` and an allow-listed or absent `Origin`.
