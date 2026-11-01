"use client";

import { useEffect, useRef } from "react";
import { socketsEnabled } from "@/lib/realtime";

export type ChatEvent =
  | { type: "chat"; message: { id: string; conversation_id: string; sender_id: string; body: string; created_at: string }; sender_name?: string }
  | { type: "read"; conversation_id: string };

// One shared WebSocket per tab for the sidebar badge and the Messages page.
const listeners = new Set<(e: ChatEvent) => void>();
let ws: WebSocket | null = null;
let retry: ReturnType<typeof setTimeout> | undefined;

function connect() {
  if (ws || typeof window === "undefined" || !socketsEnabled) return;
  const base = process.env.NEXT_PUBLIC_WS_URL || `${location.protocol === "https:" ? "wss" : "ws"}://${location.hostname}:8000`;
  try {
    ws = new WebSocket(`${base}/api/ws/messages`);
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "chat" || m.type === "read") listeners.forEach((l) => l(m));
    };
    ws.onclose = (ev) => {
      ws = null;
      // 4403: not a messaging member, so do not keep retrying. Polling still covers everyone else.
      if (listeners.size && ev.code !== 4403) retry = setTimeout(connect, 8000);
    };
  } catch { ws = null; }
}

export function useChatEvents(handler: (e: ChatEvent) => void, enabled = true) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!enabled) return;
    const l = (e: ChatEvent) => ref.current(e);
    listeners.add(l);
    connect();
    return () => {
      listeners.delete(l);
      if (!listeners.size) { clearTimeout(retry); ws?.close(); ws = null; }
    };
  }, [enabled]);
}
