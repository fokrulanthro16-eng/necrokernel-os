"use client";

import { HvState, NecroEvent } from "@/lib/types";

interface Stage {
  key: string;
  label: string;
  states: HvState[];
  active: string;
  idle: string;
}

const STAGES: Stage[] = [
  {
    key: "healthy",
    label: "HEALTHY",
    states: ["HEALTHY"],
    active: "border-cyan-400 bg-emerald-900/40 text-cyan-200 shadow-[0_0_18px_rgba(34,211,238,0.5)]",
    idle: "border-cyan-900 text-cyan-900",
  },
  {
    key: "poisoned",
    label: "POISONED / ZOMBIE",
    states: ["POISONED", "UNRESPONSIVE", "DEAD", "QUARANTINED"],
    active: "border-red-500 bg-red-950/60 text-red-300 animate-necropulse",
    idle: "border-red-950 text-red-950",
  },
  {
    key: "patch",
    label: "PATCH SYNTHESIS",
    states: ["PATCH_SYNTHESIS"],
    active: "border-amber-400 bg-amber-950/50 text-amber-200 shadow-[0_0_18px_rgba(251,191,36,0.5)]",
    idle: "border-amber-950 text-amber-950",
  },
  {
    key: "reanimated",
    label: "REANIMATED",
    states: ["REANIMATED"],
    active: "border-emerald-400 bg-emerald-950/60 text-emerald-200 shadow-[0_0_18px_rgba(52,211,153,0.6)]",
    idle: "border-emerald-950 text-emerald-950",
  },
];

export function currentState(events: NecroEvent[]): { state: HvState; pid: number } {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "state" && e.state) return { state: e.state as HvState, pid: (e.pid as number) ?? 9576 };
  }
  return { state: "HEALTHY", pid: 9576 };
}

export default function LifecycleVisualizer({ events }: { events: NecroEvent[] }) {
  const { state, pid } = currentState(events);
  return (
    <section className="rounded border border-slate-800 bg-black/60 p-4">
      <header className="mb-4 flex items-center justify-between text-xs">
        <span className="uppercase tracking-widest text-cyan-300">Process Life-Cycle</span>
        <span>
          state: <b className="text-slate-100">{state}</b> | worker PID:{" "}
          <b className="text-slate-100">{pid}</b>
        </span>
      </header>
      <ol className="flex flex-col items-stretch gap-2 md:flex-row md:items-center">
        {STAGES.map((s, i) => {
          const on = state !== null && s.states.includes(state);
          return (
            <li key={s.key} className="flex flex-1 items-center gap-2">
              <div
                className={`flex-1 rounded border-2 px-3 py-4 text-center text-xs font-bold transition-all ${
                  on ? s.active : s.idle
                }`}
                data-active={on}
              >
                {s.label}
                {on && state !== "HEALTHY" && state !== s.label && s.key === "poisoned" && (
                  <div className="mt-1 text-[10px] font-normal">{state}</div>
                )}
              </div>
              {i < STAGES.length - 1 && <span className="text-slate-600">&rarr;</span>}
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-[10px] text-slate-500">
        The PID must stay identical across a reanimation (no restart).
      </p>
    </section>
  );
}
