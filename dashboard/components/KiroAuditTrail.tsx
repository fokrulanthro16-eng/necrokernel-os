"use client";

import { NecroEvent } from "@/lib/types";

type Group = { title: string; empty: string; rows: NecroEvent[]; render: (e: NecroEvent) => string };

export default function KiroAuditTrail({ events }: { events: NecroEvent[] }) {
  const pick = (t: string) => events.filter((e) => e.type === t).slice(-50).reverse();
  const groups: Group[] = [
    {
      title: "Kiro Hook Invocations",
      empty: "no hooks fired",
      rows: pick("hook"),
      render: (e) =>
        `${e.name} on ${e.event}` +
        (e.ok === undefined ? "" : e.ok ? " : verified OK" : ` : FAILED ${JSON.stringify(e.failed)}`),
    },
    {
      title: "Steering Validations",
      empty: "no steering checks yet",
      rows: pick("steering"),
      render: (e) => `${e.file} : ${e.check}`,
    },
    {
      title: "MCP Gateway Calls",
      empty: "no MCP calls yet",
      rows: pick("mcp"),
      render: (e) => `${e.server}.${e.tool}(worker=${e.worker})`,
    },
  ];

  return (
    <section className="rounded border border-slate-800 bg-black/60">
      <header className="border-b border-slate-800 px-3 py-2 text-xs uppercase tracking-widest text-fuchsia-300">
        Kiro Audit Trail
      </header>
      <div className="grid gap-px bg-slate-800 md:grid-cols-3">
        {groups.map((g) => (
          <div key={g.title} className="h-72 overflow-y-auto bg-[#05070a] p-3 text-xs">
            <h3 className="mb-2 font-bold text-slate-200">
              {g.title} <span className="text-slate-600">({g.rows.length})</span>
            </h3>
            {g.rows.length === 0 && <div className="text-slate-600">{g.empty}</div>}
            <ul className="space-y-1">
              {g.rows.map((e) => (
                <li key={e.id} className="break-words">
                  <span className="text-slate-600">{new Date(e.ts * 1000).toISOString().slice(11, 19)} </span>
                  {g.render(e)}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
