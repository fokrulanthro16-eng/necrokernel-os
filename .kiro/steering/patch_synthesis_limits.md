# Patch Synthesis Limits

Sandboxed AST synthesis limits enforced by `engine/agent_mesh.py`.

- MAX_LOC: 25
- MAX_RUNTIME_MS: 350

1. Patches are Python source defining `def patch(state):` only.
2. Maximum 25 lines of code (non-blank, non-comment). Larger patches are rejected.
3. Execution ceiling is 350 ms. Patches that exceed it are aborted and rejected.
4. Forbidden: imports, `while`, lambda, try/with, global/nonlocal, dunder attribute access, calls other than a small allowlist (`isinstance`, `len`, `min`, `max`, `range`, `float`, `int`).
5. Also forbidden: `*`, `**`, `<<` and `%` operators. A single builtin operation (e.g. `[0] * 10**9`) cannot be interrupted mid-call, so the 350 ms ceiling is enforced by rejecting such operators before execution.
6. `range()` takes only integer literals up to 10000 (RANGE_CAP), because `max(range(N))` is a single uninterruptible call. `+` and `+=` need a statically numeric operand (a number literal or `int`/`float`/`len` call), which blocks self-concatenation memory blowup such as `x = x + x`.
7. A patch that is rejected, times out or raises is rolled back; the heap is left unchanged.
8. Patches are synthesized with an AST diff (`ast.unparse` + `difflib`) against the identity patch, validated on the supervisor side, then validated and applied again inside the worker process (same PID, shared-memory heap) with the key scope limited to the faulting key.
