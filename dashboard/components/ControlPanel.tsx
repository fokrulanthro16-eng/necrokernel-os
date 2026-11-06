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

export default function ControlPanel() {
  const [msg, setMsg] = useState("");

  async function post(path: string, body?: unknown) {
    try {
      const r = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      setMsg(`${path} -> HTTP ${r.status}`);
    } catch (err) {
      setMsg(`${path} failed: ${String(err)}`);
    }
  }

  const btn = "rounded border px-3 py-1 text-xs hover:bg-slate-800";
  return (
    <section className="flex flex-wrap items-center gap-2 rounded border border-slate-800 bg-black/60 p-3">
      <span className="mr-2 text-xs uppercase tracking-widest text-slate-400">Inject fault</span>
      {CRASHES.map((c) => (
        <button key={c.label} className={`${btn} border-red-800 text-red-300`}
          onClick={() => post("/hv/crash", { kind: c.kind })}>
          {c.label}
        </button>
      ))}
      <button className={`${btn} border-amber-700 text-amber-300`} onClick={() => post("/hv/reanimate")}>
        reanimate
      </button>
      <button className={`${btn} border-cyan-700 text-cyan-300`} onClick={() => post("/hv/reset")}>
        reset
      </button>
      <span className="ml-auto text-xs text-slate-500">{msg}</span>
    </section>
  );
}
