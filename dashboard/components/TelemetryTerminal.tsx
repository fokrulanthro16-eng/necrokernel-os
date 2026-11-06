"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ConnStatus, NecroEvent } from "@/lib/types";

const COLORS: Record<string, string> = {
  state: "text-cyan-300",
  fault: "text-red-400",
  hook: "text-fuchsia-300",
  steering: "text-sky-300",
  patch: "text-amber-300",
  inspect: "text-violet-300",
  mcp: "text-teal-300",
  pulse: "text-slate-500",
};

function fmt(ev: NecroEvent): string {
  const { id, ts, type, ...rest } = ev;
  return JSON.stringify(rest);
}

export default function TelemetryTerminal({
  events,
  status,
  onClear,
}: {
  events: NecroEvent[];
  status: ConnStatus;
  onClear: () => void;
}) {
  const [showPulse, setShowPulse] = useState(false);
  const [follow, setFollow] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const rows = useMemo(
    () => (showPulse ? events : events.filter((e) => e.type !== "pulse")),
    [events, showPulse]
  );

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [rows, follow]);

  const dot =
    status === "open" || status === "demo"
      ? "bg-emerald-400"
      : status === "connecting"
      ? "bg-amber-400"
      : "bg-red-500";

  return (
    <section className="flex h-[28rem] flex-col rounded border border-slate-800 bg-black/60">
      <header className="flex items-center justify-between border-b border-slate-800 px-3 py-2 text-xs">
        <span className="uppercase tracking-widest text-cyan-300">Telemetry Terminal</span>
        <span className="flex items-center gap-3">
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={showPulse} onChange={(e) => setShowPulse(e.target.checked)} />
            pulses
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
            follow
          </label>
          <button className="rounded border border-slate-700 px-2 hover:bg-slate-800" onClick={onClear}>
            clear
          </button>
          <span className="flex items-center gap-1.5">
            <span className={`inline-block h-2 w-2 rounded-full ${dot}`} />
            {status === "demo" ? (
              <span className="rounded border border-emerald-500/40 bg-emerald-950/80 px-2 py-0.5 text-[10px] font-bold tracking-wider text-emerald-300">
                DEMO SIMULATOR ACTIVE
              </span>
            ) : (
              <span className="text-slate-300">{status}</span>
            )}
          </span>
        </span>
      </header>
      <div ref={box} className="flex-1 overflow-y-auto p-3 text-xs leading-5">
        {rows.length === 0 && <div className="text-slate-600">waiting for worker IPC events...</div>}
        {rows.map((ev) => (
          <div key={ev.id} className="whitespace-pre-wrap break-all">
            <span className="text-slate-600">
              {new Date(ev.ts * 1000).toISOString().slice(11, 23)} #{ev.id}{" "}
            </span>
            <span className={`${COLORS[ev.type] ?? "text-slate-300"} font-bold`}>[{ev.type}]</span>{" "}
            <span className="text-slate-300">{fmt(ev)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
