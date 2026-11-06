# NecroKernel-OS: Devpost submission (Kiroween 2026)

**One line:** a hypervisor that treats a crashed worker as a patient: it inspects the dump, synthesizes a tiny bounded patch, applies it inside the same process and resumes the task, with the PID unchanged.

Repo: <https://github.com/fokrulanthro16-eng/necrokernel-os>

## Category mapping

These are our own fit arguments, not results or claims of winning.

| Category | Why we think it fits | Honest caveat |
|----------|----------------------|---------------|
| 1st Place Overall | Kiro specs, hooks, steering, MCP and agents are load-bearing: steering files are read by the engine at runtime and a test checks they match the code constants. | Small scope; dashboard unbuilt. |
| Best Frankenstein | Stitches together unlike parts: POSIX signals, shared memory, AST sandboxing, MCP tools, Kiro hooks and a live SSE dashboard, into one "reanimation" loop. | |
| Best Startup | Pitch: crash-time hot recovery for stateful workers (sessions, crypto contexts) instead of restart. | Prototype on a simulated fault model. No customers, no market data, no business metrics. |

## What is real vs simulated

- Real: separate spawned worker OS PID, `os.waitpid`, `multiprocessing.shared_memory`, Pipe IPC, signals sent with `os.kill` to the worker's own PID and caught by Python handlers.
- Simulated: the invalid memory access (checked-accessor logic) and the registers (derived from the Python frame). A genuine hardware SIGSEGV cannot be resumed in CPython.
- Not implemented: the eBPF telemetry interceptor (conceptual only; current path is signal handlers + Pipe).
- Local simulation: the MCP gateway has no authentication.

## Technical deep dive

See [ARCHITECTURE.md](ARCHITECTURE.md) and the diagrams in [README.md](README.md). Summary:

fault in worker -> real self-signal -> Python handler -> structured dump -> hook `on_crash_intercept` -> NecroInspector -> PatchSynthesizer (AST diff, sandbox: 25 LOC, 350 ms) -> Reanimator (`hot_swap`, key-scoped, rollback on failure) -> hook `post_reanimation_verify` -> task re-executed in the same process.

## Mathematical invariants

Let `p` be the worker PID, `H` the canonical heap frame, `M(H)` its byte length, `K` the patched keys.

- INV-PID: `p_after = p_before`
- INV-STATE: `for all k not in K: H_after[k] = H_before[k]` (byte-identical)
- INV-HEAP-DRIFT: `| M(H_after) - M(H_before) | <= 16`
- INV-BOUND: `loc(patch) <= 25` and `t(patch) <= 350 ms`
- Bounded recovery: at most 8 fault/patch/verify cycles per task
- INV-PROGRESS: the interrupted task returns a result

Source of truth: `.kiro/specs/reanimation_contract.spec.yaml`.

## Proof metrics (all from real runs)

**Test suite** (`python -m pytest -q test_reanimation_cycle.py`, sandbox, Python 3.11): `60 passed, 2 skipped` in about 8 s. Skipped: the Hypothesis property test (Hypothesis not installable there, so it **has never run**) and the PyYAML spec test. Invariants were exercised by seeded stdlib loops of 100+ iterations each.

**Recovery run** (`scripts/measure_recovery.py 50`, local server, one machine, one run; raw file [`docs/assets/measured_recovery.json`](docs/assets/measured_recovery.json)):

| Metric | Measured |
|--------|----------|
| Cycles attempted / succeeded | 50 / 50 (10 each of null, nan, segv, sigbus, div0) |
| Worker PID before / after | 106 / 106 |
| Worker restarts | 0 |
| Fault/patch/verify cycles used per task | 1 (max) |
| `/hv/reanimate` round trip, median / p95 / max | 3.11 ms / 3.89 ms / 4.08 ms |

"Zero downtime" here means: the worker process is never restarted and the PID is unchanged. The interrupted task is blocked for the few milliseconds the recovery takes. The latency figures are localhost HTTP timings on a sandbox, not a benchmark.

**Not measured:** Hypothesis results, dashboard build/runtime, Docker build, behaviour under load, multi-worker scale.

## Built with Kiro

`.kiro/specs` (contract + patch verification), `.kiro/hooks` (`on_crash_intercept`, `post_reanimation_verify`), `.kiro/steering` (memory safety invariants, patch limits), `.kiro/mcp` (4 tools: `read_crash_dump`, `inspect_memory_registers`, `inject_hotpatch`, `verify_process_health`).

## Run it

```
python -m pytest -q test_reanimation_cycle.py
python -m engine.server &
python scripts/measure_recovery.py 50
# or: docker compose up --build   (Docker path not built by us)
```

## What's next

Implement the eBPF interceptor (currently only conceptual), run the Hypothesis suite in CI, build and test the dashboard, authenticate the MCP gateway.
