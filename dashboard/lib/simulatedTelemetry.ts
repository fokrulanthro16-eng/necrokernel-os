/**
 * Simulated fault signatures, CPU registers, and AST patch diffs for Vercel demo fallback mode.
 * Strictly maintains worker PID 9576 and invariant 0-byte drift.
 */

import { NecroEvent } from "./types";

export interface SimulatedFaultSpec {
  kind: string;
  signal: string;
  key: string;
  rip: string;
  diagnosis: {
    fault_kind: string;
    signal: string;
    faulting_key: string;
    execution_pointer: string;
    registers: Record<string, string>;
    call_stack: Array<{ frame: number; fn: string; file: string; line: number }>;
    details: Record<string, unknown>;
    timestamp: number;
  };
  patch_src: string;
  ast_diff: string;
}

export function getSimulatedFault(kind: string | null): SimulatedFaultSpec {
  const ts = Date.now() / 1000;

  switch (kind) {
    case "div0":
      return {
        kind: "ZERO_DIVISION",
        signal: "SIGFPE",
        key: "metrics",
        rip: "0x7fff0800",
        diagnosis: {
          fault_kind: "ZERO_DIVISION",
          signal: "SIGFPE",
          faulting_key: "metrics",
          execution_pointer: "0x7fff0800",
          registers: {
            rax: "0x16752187140",
            rbx: "0x6",
            rcx: "0x8",
            rdx: "0xb0720669",
            rsi: "0x0",
            rdi: "0x167520e0810",
            rsp: "0x16752125010",
            rbp: "0x167521252b0",
            rip: "0x7fff0800",
          },
          call_stack: [
            { frame: 0, fn: "checked_accessor", file: "engine/kernel_emulator.py", line: 150 },
            { frame: 1, fn: "execute_task", file: "engine/kernel_emulator.py", line: 210 },
          ],
          details: { divisor: 0 },
          timestamp: ts,
        },
        patch_src: "def patch(state):\n    state['metrics'] = {'latency_ms': 1.0, 'errors': 0}\n",
        ast_diff:
          "--- identity_patch\n+++ synthesized_patch\n@@ -1,2 +1,2 @@\n def patch(state):\n-    pass\n+    state['metrics'] = {'latency_ms': 1.0, 'errors': 0}",
      };

    case "segv":
      return {
        kind: "SEGMENTATION_FAULT",
        signal: "SIGSEGV",
        key: "active_tasks",
        rip: "0x7fff0041b8e4",
        diagnosis: {
          fault_kind: "SEGMENTATION_FAULT",
          signal: "SIGSEGV",
          faulting_key: "active_tasks",
          execution_pointer: "0x7fff0041b8e4",
          registers: {
            rax: "0xdeadbeef",
            rbx: "0x0",
            rcx: "0x30",
            rdx: "0x7ffff7dc1020",
            rsi: "0x7ffff7dc1050",
            rdi: "0x1",
            rsp: "0x7fffffffd9e0",
            rbp: "0x7fffffffda10",
            rip: "0x7fff0041b8e4",
          },
          call_stack: [
            { frame: 0, fn: "checked_accessor", file: "engine/kernel_emulator.py", line: 162 },
            { frame: 1, fn: "execute_task", file: "engine/kernel_emulator.py", line: 215 },
          ],
          details: { faulting_address: "0x7fff0041b8e0", offset: "0x30" },
          timestamp: ts,
        },
        patch_src: "def patch(state):\n    state['active_tasks'] = ['stream_metrics', 'kv_lease']\n",
        ast_diff:
          "--- identity_patch\n+++ synthesized_patch\n@@ -1,2 +1,2 @@\n def patch(state):\n-    pass\n+    state['active_tasks'] = ['stream_metrics', 'kv_lease']",
      };

    case "sigbus":
      return {
        kind: "BUS_ERROR",
        signal: "SIGBUS",
        key: "crypto_context",
        rip: "0x7fff00421000",
        diagnosis: {
          fault_kind: "BUS_ERROR",
          signal: "SIGBUS",
          faulting_key: "crypto_context",
          execution_pointer: "0x7fff00421000",
          registers: {
            rax: "0x7fff00421001",
            rbx: "0x2",
            rcx: "0x10",
            rdx: "0x7ffff7dc2000",
            rsi: "0x0",
            rdi: "0x1",
            rsp: "0x7fffffffd9f0",
            rbp: "0x7fffffffda20",
            rip: "0x7fff00421000",
          },
          call_stack: [
            { frame: 0, fn: "checked_accessor", file: "engine/kernel_emulator.py", line: 170 },
            { frame: 1, fn: "execute_task", file: "engine/kernel_emulator.py", line: 220 },
          ],
          details: { alignment: "unaligned_access_32bit" },
          timestamp: ts,
        },
        patch_src: "def patch(state):\n    state['crypto_context'] = {'cipher': 'AES-256-GCM', 'epoch': 43}\n",
        ast_diff:
          "--- identity_patch\n+++ synthesized_patch\n@@ -1,2 +1,2 @@\n def patch(state):\n-    pass\n+    state['crypto_context'] = {'cipher': 'AES-256-GCM', 'epoch': 43}",
      };

    case "nan":
      return {
        kind: "INVALID_OPERATION",
        signal: "SIGFPE",
        key: "counters",
        rip: "0x7fff0800a012",
        diagnosis: {
          fault_kind: "INVALID_OPERATION",
          signal: "SIGFPE",
          faulting_key: "counters",
          execution_pointer: "0x7fff0800a012",
          registers: {
            rax: "0x7ff8000000000000",
            rbx: "0x0",
            rcx: "0x1",
            rdx: "0x0",
            rsi: "0x0",
            rdi: "0x0",
            rsp: "0x7fffffffd9e0",
            rbp: "0x7fffffffda10",
            rip: "0x7fff0800a012",
          },
          call_stack: [
            { frame: 0, fn: "checked_accessor", file: "engine/kernel_emulator.py", line: 180 },
            { frame: 1, fn: "execute_task", file: "engine/kernel_emulator.py", line: 225 },
          ],
          details: { fpu_status: "FE_INVALID" },
          timestamp: ts,
        },
        patch_src: "def patch(state):\n    state['counters'] = {'requests': 101, 'tokens': 5430}\n",
        ast_diff:
          "--- identity_patch\n+++ synthesized_patch\n@@ -1,2 +1,2 @@\n def patch(state):\n-    pass\n+    state['counters'] = {'requests': 101, 'tokens': 5430}",
      };

    case "null":
    default:
      return {
        kind: "NULL_POINTER",
        signal: "SIGSEGV",
        key: "session_id",
        rip: "0x7fff0041a000",
        diagnosis: {
          fault_kind: "NULL_POINTER",
          signal: "SIGSEGV",
          faulting_key: "session_id",
          execution_pointer: "0x7fff0041a000",
          registers: {
            rax: "0x0000000000000000",
            rbx: "0x0",
            rcx: "0x0",
            rdx: "0x0",
            rsi: "0x0",
            rdi: "0x0",
            rsp: "0x7fffffffd9e0",
            rbp: "0x7fffffffda10",
            rip: "0x7fff0041a000",
          },
          call_stack: [
            { frame: 0, fn: "checked_accessor", file: "engine/kernel_emulator.py", line: 140 },
            { frame: 1, fn: "execute_task", file: "engine/kernel_emulator.py", line: 200 },
          ],
          details: { deref_address: "0x00000000" },
          timestamp: ts,
        },
        patch_src: "def patch(state):\n    state['session_id'] = 'sess-live-0x4a1f'\n",
        ast_diff:
          "--- identity_patch\n+++ synthesized_patch\n@@ -1,2 +1,2 @@\n def patch(state):\n-    pass\n+    state['session_id'] = 'sess-live-0x4a1f'",
      };
  }
}
