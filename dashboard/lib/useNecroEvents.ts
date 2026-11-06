"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE, ConnStatus, EVENT_TYPES, NecroEvent } from "./types";
import { getSimulatedFault } from "./simulatedTelemetry";

const MAX_EVENTS = 500;
const DEMO_PID = 9576;

/** Subscribes to the SSE feed with automatic demo fallback if backend is unreachable. */
export function useNecroEvents() {
  const [events, setEvents] = useState<NecroEvent[]>([]);
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const [isDemo, setIsDemo] = useState(false);
  const lastId = useRef(0);
  const simIdRef = useRef(10);
  const reanimCountRef = useRef(0);
  const activeFaultRef = useRef<string | null>("div0");
  const simTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const appendEvents = (newEvents: NecroEvent[]) => {
    setEvents((prev) => {
      const next = prev.concat(newEvents);
      return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
    });
  };

  const clearSimTimers = () => {
    for (const t of simTimersRef.current) clearTimeout(t);
    simTimersRef.current = [];
  };

  // Switch to clean client-side demo simulator
  const activateDemoMode = () => {
    setIsDemo(true);
    setStatus("demo");

    const now = Date.now() / 1000;
    const initialEvents: NecroEvent[] = [
      { id: 1, ts: now - 3, type: "state", state: "HEALTHY", pid: DEMO_PID },
      { id: 2, ts: now - 2, type: "pulse", state: "HEALTHY", pid: DEMO_PID, quarantined: false },
      {
        id: 3,
        ts: now - 1,
        type: "steering",
        file: ".kiro/steering/memory_safety.md",
        check: `INV-PID (${DEMO_PID}) and INV-STATE verified active`,
      },
    ];
    setEvents(initialEvents);
    lastId.current = 3;
  };

  const injectSimulatedFault = (kind: string | null) => {
    clearSimTimers();
    activeFaultRef.current = kind;
    const faultData = getSimulatedFault(kind);
    const now = Date.now() / 1000;

    // Stage 1: Immediate POISONED state
    const stage1Events: NecroEvent[] = [
      {
        id: ++simIdRef.current,
        ts: now,
        type: "state",
        state: "POISONED",
        pid: DEMO_PID,
      },
      {
        id: ++simIdRef.current,
        ts: now,
        type: "fault",
        kind: faultData.kind,
        signal: faultData.signal,
        key: faultData.key,
        rip: faultData.rip,
      },
      {
        id: ++simIdRef.current,
        ts: now,
        type: "hook",
        hook: "on_crash_intercept",
        event: "process.fault",
        kind: faultData.kind,
        key: faultData.key,
      },
    ];
    appendEvents(stage1Events);

    // Stage 2: After 650ms -> PATCH_SYNTHESIS
    const t1 = setTimeout(() => {
      const now2 = Date.now() / 1000;
      const stage2Events: NecroEvent[] = [
        {
          id: ++simIdRef.current,
          ts: now2,
          type: "state",
          state: "PATCH_SYNTHESIS",
          pid: DEMO_PID,
        },
        {
          id: ++simIdRef.current,
          ts: now2,
          type: "inspect",
          diagnosis: faultData.diagnosis,
        },
        {
          id: ++simIdRef.current,
          ts: now2,
          type: "patch",
          patch_src: faultData.patch_src,
          ast_diff: faultData.ast_diff,
        },
        {
          id: ++simIdRef.current,
          ts: now2,
          type: "steering",
          file: ".kiro/steering/patch_constraints.md",
          check: "loc <= 25 and latency <= 350ms : VALIDATED",
        },
        {
          id: ++simIdRef.current,
          ts: now2,
          type: "mcp",
          server: "necrokernel-mcp",
          tool: "inject_hotpatch",
          worker: "session-worker",
        },
      ];
      appendEvents(stage2Events);
    }, 650);
    simTimersRef.current.push(t1);

    // Stage 3: After 1400ms -> REANIMATED
    const t2 = setTimeout(() => {
      const now3 = Date.now() / 1000;
      reanimCountRef.current += 1;
      const stage3Events: NecroEvent[] = [
        {
          id: ++simIdRef.current,
          ts: now3,
          type: "hook",
          hook: "post_reanimation_verify",
          event: "process.reanimated",
          drift_bytes: 0,
          ok: true,
        },
        {
          id: ++simIdRef.current,
          ts: now3,
          type: "state",
          state: "REANIMATED",
          pid: DEMO_PID,
          drift_bytes: 0,
          reanimations: reanimCountRef.current,
        },
      ];
      appendEvents(stage3Events);
    }, 1400);
    simTimersRef.current.push(t2);
  };

  const triggerSimulatedReanimate = () => {
    clearSimTimers();
    const faultData = getSimulatedFault(activeFaultRef.current);
    const now = Date.now() / 1000;

    const synthEvents: NecroEvent[] = [
      {
        id: ++simIdRef.current,
        ts: now,
        type: "state",
        state: "PATCH_SYNTHESIS",
        pid: DEMO_PID,
      },
      {
        id: ++simIdRef.current,
        ts: now,
        type: "patch",
        patch_src: faultData.patch_src,
        ast_diff: faultData.ast_diff,
      },
    ];
    appendEvents(synthEvents);

    const t = setTimeout(() => {
      const now2 = Date.now() / 1000;
      reanimCountRef.current += 1;
      const reanimEvents: NecroEvent[] = [
        {
          id: ++simIdRef.current,
          ts: now2,
          type: "hook",
          hook: "post_reanimation_verify",
          event: "process.reanimated",
          drift_bytes: 0,
          ok: true,
        },
        {
          id: ++simIdRef.current,
          ts: now2,
          type: "state",
          state: "REANIMATED",
          pid: DEMO_PID,
          drift_bytes: 0,
          reanimations: reanimCountRef.current,
        },
      ];
      appendEvents(reanimEvents);
    }, 700);
    simTimersRef.current.push(t);
  };

  const triggerSimulatedReset = () => {
    clearSimTimers();
    const now = Date.now() / 1000;
    const resetEvents: NecroEvent[] = [
      {
        id: ++simIdRef.current,
        ts: now,
        type: "state",
        state: "HEALTHY",
        pid: DEMO_PID,
        reset: true,
      },
      {
        id: ++simIdRef.current,
        ts: now,
        type: "pulse",
        pid: DEMO_PID,
        state: "HEALTHY",
        quarantined: false,
      },
    ];
    appendEvents(resetEvents);
  };

  useEffect(() => {
    // If running in cloud / non-localhost (e.g. Vercel deployment), activate demo immediately
    if (typeof window !== "undefined") {
      const host = window.location.hostname;
      if (host !== "localhost" && host !== "127.0.0.1") {
        activateDemoMode();
        return;
      }
    }

    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let delay = 500;
    let closed = false;
    let failedAttempts = 0;

    const onMessage = (msg: MessageEvent) => {
      try {
        const ev = JSON.parse(msg.data) as NecroEvent;
        if (ev.id <= lastId.current) return;
        lastId.current = ev.id;
        appendEvents([ev]);
      } catch {
        /* ignore malformed frame */
      }
    };

    const checkBackendReachability = async () => {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 2000);
        const res = await fetch(`${API_BASE}/health`, {
          signal: controller.signal,
        });
        clearTimeout(timeoutId);
        if (!res.ok) throw new Error("Health check non-200");
      } catch {
        // Unreachable! Switch to demo mode
        if (!closed) {
          activateDemoMode();
        }
      }
    };

    const connect = () => {
      if (closed) return;
      try {
        es = new EventSource(`${API_BASE}/events`);
        es.onopen = () => {
          delay = 500;
          failedAttempts = 0;
          setStatus("open");
          setIsDemo(false);
        };
        for (const t of EVENT_TYPES) es.addEventListener(t, onMessage as EventListener);
        es.onerror = () => {
          es?.close();
          es = null;
          failedAttempts += 1;
          if (failedAttempts >= 2) {
            activateDemoMode();
            return;
          }
          setStatus("reconnecting");
          timer = setTimeout(connect, delay);
          delay = Math.min(delay * 2, 4000);
        };
      } catch {
        activateDemoMode();
      }
    };

    checkBackendReachability();
    connect();

    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      es?.close();
      clearSimTimers();
    };
  }, []);

  return {
    events,
    status,
    isDemo,
    injectSimulatedFault,
    triggerSimulatedReanimate,
    triggerSimulatedReset,
    clear: () => setEvents([]),
  };
}
