"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { examWebSocketUrl } from "@/lib/api/level1-exam";
import type { ExamNetworkStatus, ExamWsMessage } from "@/types/level1-exam";
import { WS_HEARTBEAT_INTERVAL_MS } from "../lib/constants";

const MAX_RETRIES = 10;
const BASE_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 10_000;

export interface ExamSocketCallbacks {
  onSessionState: (remainingSeconds: number | null, questionIdx: number) => void;
  onResumeApproved: (remainingSeconds: number | null, questionIdx: number) => void;
  onTerminated: () => void;
  onAdminWarning: (message: string) => void;
  getRemainingSeconds: () => number;
  getCurrentQuestionIdx: () => number;
}

/**
 * Live session WebSocket (/ws/interview/{id}). Heartbeats timer + question index every 10s,
 * reconnects with capped exponential back-off and surfaces hold/terminate/admin-warning events.
 * Server close codes 4001/4003/4004 are final (no retry).
 */
export function useExamSocket({
  submissionId,
  token,
  callbacks,
}: {
  submissionId: string | undefined;
  token: string | null;
  callbacks: ExamSocketCallbacks;
}): { networkStatus: ExamNetworkStatus } {
  const [networkStatus, setNetworkStatus] = useState<ExamNetworkStatus>("connected");
  const cbRef = useRef(callbacks);
  useEffect(() => {
    cbRef.current = callbacks;
  });

  const statusRef = useRef<ExamNetworkStatus>("connected");
  const update = useCallback((s: ExamNetworkStatus | ((p: ExamNetworkStatus) => ExamNetworkStatus)) => {
    const next = typeof s === "function" ? s(statusRef.current) : s;
    statusRef.current = next;
    setNetworkStatus(next);
  }, []);

  useEffect(() => {
    if (!submissionId || !token) return;
    let disposed = false;
    let ws: WebSocket | null = null;
    let heartbeat: ReturnType<typeof setInterval> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retries = 0;

    const stopHeartbeat = () => {
      if (heartbeat) clearInterval(heartbeat);
      heartbeat = null;
    };

    const handleMessage = (event: MessageEvent) => {
      let msg: ExamWsMessage;
      try {
        msg = JSON.parse(event.data as string) as ExamWsMessage;
      } catch {
        return;
      }
      const cbs = cbRef.current;
      switch (msg.type) {
        case "connected":
          update("connected");
          if (msg.remaining_seconds !== undefined || msg.current_question_idx !== undefined)
            cbs.onSessionState(msg.remaining_seconds ?? null, msg.current_question_idx ?? 0);
          break;
        case "pong":
          if (statusRef.current === "reconnecting") update("connected");
          break;
        case "on_hold":
          update("on_hold");
          break;
        case "resume_approved":
          update("connected");
          cbs.onResumeApproved(msg.remaining_seconds ?? null, msg.current_question_idx ?? 0);
          break;
        case "terminated":
          update("offline");
          cbs.onTerminated();
          break;
        case "admin_warning":
          if (msg.message) cbs.onAdminWarning(msg.message);
          break;
      }
    };

    const connect = () => {
      if (disposed) return;
      const socket = new WebSocket(examWebSocketUrl(submissionId, token));
      ws = socket;

      socket.onopen = () => {
        if (disposed) {
          socket.close();
          return;
        }
        retries = 0;
        update((p) => (p === "on_hold" ? p : "connected"));
        stopHeartbeat();
        heartbeat = setInterval(() => {
          if (socket.readyState !== WebSocket.OPEN) return;
          socket.send(
            JSON.stringify({
              type: "ping",
              remaining_seconds: cbRef.current.getRemainingSeconds(),
              current_question_idx: cbRef.current.getCurrentQuestionIdx(),
            })
          );
        }, WS_HEARTBEAT_INTERVAL_MS);
      };
      socket.onmessage = handleMessage;
      socket.onclose = (ev) => {
        stopHeartbeat();
        if (disposed) return;
        if ([4001, 4003, 4004].includes(ev.code)) return;
        update((p) => (p === "on_hold" ? p : "reconnecting"));
        if (retries >= MAX_RETRIES) return;
        const delay = Math.min(BASE_BACKOFF_MS * 2 ** retries, MAX_BACKOFF_MS);
        retries += 1;
        retryTimer = setTimeout(connect, delay);
      };
    };

    const onOnline = () => {
      if (statusRef.current === "on_hold" || disposed) return;
      update("reconnecting");
      if (!ws || ws.readyState === WebSocket.CLOSED) connect();
    };
    const onOffline = () => {
      update((p) => (p === "on_hold" ? p : "offline"));
      stopHeartbeat();
    };

    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    connect();

    return () => {
      disposed = true;
      stopHeartbeat();
      if (retryTimer) clearTimeout(retryTimer);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      if (ws) {
        ws.onclose = null;
        ws.onmessage = null;
        if (ws.readyState !== WebSocket.CONNECTING) ws.close();
      }
    };
  }, [submissionId, token, update]);

  return { networkStatus };
}
