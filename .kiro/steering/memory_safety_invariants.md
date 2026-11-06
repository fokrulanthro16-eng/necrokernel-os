# Memory Safety Invariants

Hard boundaries for every agent in the NecroKernel-OS mesh.

- NO_CONTAINER_REBOOT: true
- NO_PROCESS_RESTART: true
- EPSILON_BYTES: 16
- MAX_CYCLES: 8

1. Never reboot the container or restart the worker. PID must be identical before and after recovery.
2. Sentinel guards are deterministic: null references become `{}`-style sentinel objects with zero values; poisoned numbers (NaN, inf) become `0`; out-of-range indices (including negative ones) clamp to the last valid index. No randomness.
3. Patches may only touch the faulting key(s) named in the crash dump.
4. Every reanimation must be followed by the `post_reanimation_verify` hook.
5. Faults happen in a separate worker OS process. Real signals (SIGSEGV, SIGBUS, SIGFPE) are only sent with `os.kill` to that worker's own PID and handled by Python handlers; ZeroDivisionError is trapped. Agents never touch other processes, real host memory, or invalid addresses. The "memory corruption" is checked-accessor logic on a shared-memory heap, not a hardware fault (CPython cannot resume a genuine hardware SIGSEGV).
6. Heap drift after a reanimation must satisfy |M_after - M_before| <= EPSILON_BYTES (M = bytes of the canonical heap frame), and every non-faulting key must be byte-identical. Reanimation loops are bounded by MAX_CYCLES per task. Both values mirror `tolerances` in `.kiro/specs/reanimation_contract.spec.yaml`.
7. Hook signals: `on_crash_intercept` fires on process.fault, `post_reanimation_verify` fires on process.reanimated; both are audited on the event bus together with steering validations and MCP tool calls.
8. Property tests use Hypothesis with `max_examples >= 100` and `deadline=None` when it is installed, plus a seeded stdlib random loop of 100+ iterations that always runs. Never report an unrun test as passing.
