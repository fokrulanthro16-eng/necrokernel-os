"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE, ConnStatus, EVENT_TYPES, NecroEvent } from "./types";

const MAX_EVENTS = 500;

/** Subscribes to the SSE feed with manual reconnect and exponential backoff. */
export function useNecroEvents() {
  const [events, setEvents] = useState<NecroEvent[]>([]);
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const lastId = useRef(0);

  useEffect(() => {
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let delay = 500;
    let closed = false;

    const onMessage = (msg: MessageEvent) => {
      try {
        const ev = JSON.parse(msg.data) as NecroEvent;
        if (ev.id <= lastId.current) return;
        lastId.current = ev.id;
        setEvents((prev) => {
          const next = prev.concat(ev);
          return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
        });
      } catch {
        /* ignore malformed frame */
      }
    };

    const connect = () => {
      if (closed) return;
      es = new EventSource(`${API_BASE}/events`);
      es.onopen = () => {
        delay = 500;
        setStatus("open");
      };
      for (const t of EVENT_TYPES) es.addEventListener(t, onMessage as EventListener);
      es.onerror = () => {
        es?.close();
        es = null;
        setStatus("reconnecting");
        timer = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 8000);
      };
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, []);

  return { events, status, clear: () => setEvents([]) };
}
