export const API_BASE = process.env.NEXT_PUBLIC_NECRO_API ?? "http://127.0.0.1:8000";

export type HvState =
  | "HEALTHY"
  | "POISONED"
  | "PATCH_SYNTHESIS"
  | "REANIMATED"
  | "UNRESPONSIVE"
  | "DEAD"
  | "QUARANTINED";

export type EventType =
  | "state"
  | "fault"
  | "hook"
  | "steering"
  | "patch"
  | "inspect"
  | "mcp"
  | "pulse";

export interface NecroEvent {
  id: number;
  ts: number;
  type: EventType;
  [key: string]: unknown;
}

export const EVENT_TYPES: EventType[] = [
  "state", "fault", "hook", "steering", "patch", "inspect", "mcp", "pulse",
];

export type ConnStatus = "connecting" | "open" | "reconnecting" | "demo";
