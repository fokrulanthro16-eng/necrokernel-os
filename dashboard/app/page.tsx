"use client";

import ControlPanel from "@/components/ControlPanel";
import KiroAuditTrail from "@/components/KiroAuditTrail";
import LifecycleVisualizer from "@/components/LifecycleVisualizer";
import TelemetryTerminal from "@/components/TelemetryTerminal";
import { useNecroEvents } from "@/lib/useNecroEvents";

export default function Page() {
  const {
    events,
    status,
    isDemo,
    injectSimulatedFault,
    triggerSimulatedReanimate,
    triggerSimulatedReset,
    clear,
  } = useNecroEvents();

  return (
    <main className="mx-auto max-w-6xl space-y-4 p-4">
      <h1 className="text-lg font-bold tracking-widest text-cyan-300">NECROKERNEL-OS // HYPERVISOR</h1>
      <ControlPanel
        isDemo={isDemo}
        onInjectFault={injectSimulatedFault}
        onReanimate={triggerSimulatedReanimate}
        onReset={triggerSimulatedReset}
      />
      <LifecycleVisualizer events={events} />
      <TelemetryTerminal events={events} status={status} onClear={clear} />
      <KiroAuditTrail events={events} />
    </main>
  );
}
