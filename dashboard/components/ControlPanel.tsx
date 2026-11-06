"use client";

import { useState } from "react";
import { API_BASE } from "@/lib/types";

const CRASHES: { label: string; kind: string | null }[] = [
  { label: "null deref", kind: null },
  { label: "NaN", kind: "nan" },
  { label: "SIGSEGV", kind: "segv" },
  { label: "SIGBUS", kind: "sigbus" },
  { label: "div by zero", kind: "div0" },
];

export default function ControlPanel({
  isDemo,
  onInjectFault,
  onReanimate,
  onReset,
}: {
  isDemo?: boolean;
  onInjectFault?: (kind: string | null) => void;
  onReanimate?: () => void;
  onReset?: () => void;
}) {
  const [msg, setMsg] = useState("");

  const handleDemoAction = (path: string, body?: unknown) => {
    if (path === "/hv/crash") {
      const kind = (body as { kind?: string | null })?.kind ?? null;
      onInjectFault?.(kind);
      setMsg(`/hv/crash (${kind ?? "null"}) -> SIMULATED`);
    } else if (path === "/hv/reanimate") {
      onReanimate?.();
      setMsg("/hv/reanimate -> SIMULATED");
    } else if (path === "/hv/reset") {
      onReset?.();
      setMsg("/hv/reset -> SIMULATED");
    }
  };

  async function post(path: string, body?: unknown) {
    if (isDemo) {
      handleDemoAction(path, body);
      return;
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);
      const r = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setMsg(`${path} -> HTTP ${r.status}`);
    } catch {
      // Fallback to client-side demo action if backend is unreachable / blocked on Vercel
      handleDemoAction(path, body);
    }
  }

  const btn = "rounded border px-3 py-1 text-xs hover:bg-slate-800 transition-colors";
  return (
    <section className="flex flex-wrap items-center gap-2 rounded border border-slate-800 bg-black/60 p-3">
      <span className="mr-2 text-xs uppercase tracking-widest text-slate-400">Inject fault</span>
      {CRASHES.map((c) => (
        <button
          key={c.label}
          className={`${btn} border-red-800 text-red-300 hover:border-red-600`}
          onClick={() => post("/hv/crash", { kind: c.kind })}
        >
          {c.label}
        </button>
      ))}
      <button
        className={`${btn} border-amber-700 text-amber-300 hover:border-amber-500`}
        onClick={() => post("/hv/reanimate")}
      >
        reanimate
      </button>
      <button
        className={`${btn} border-cyan-700 text-cyan-300 hover:border-cyan-500`}
        onClick={() => post("/hv/reset")}
      >
        reset
      </button>
      {isDemo && (
        <span className="rounded border border-emerald-600/40 bg-emerald-950/60 px-2 py-0.5 text-[10px] font-bold text-emerald-400">
          DEMO SIMULATOR
        </span>
      )}
      <span className="ml-auto text-xs text-slate-500">{msg}</span>
    </section>
  );
}
