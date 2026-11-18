"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/stores/auth-store";
import type { SourcingSearchPlan } from "@/types/sourcing";

// Talks to the SkillMate Sourcing extension through window.postMessage. The extension's
// bridge.js content script relays between this page and its background worker.

const PAGE = "skillmate-page";
const EXT = "skillmate-ext";

export type ProgressStage = "searching" | "scraping" | "screening" | "done" | "error";
export interface RunProgress {
  stage: ProgressStage;
  page?: number;
  pageTo?: number;
  reason?: string;
}

interface ExtMessage {
  source: string;
  type: string;
  requestId?: string;
  runId?: string;
  [key: string]: unknown;
}

function apiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_URL;
  if (env && /^https?:\/\//.test(env)) return env.replace(/\/$/, "");
  return `${window.location.origin}${env && env.startsWith("/") ? env.replace(/\/$/, "") : "/api"}`;
}

const newId = () => Math.random().toString(36).slice(2) + Date.now().toString(36);

export function useSkillmateExtension() {
  const token = useAuthStore((s) => s.token);
  const [installed, setInstalled] = useState<boolean | null>(null);
  // The extension was reloaded/updated after this page loaded: only a page reload reconnects it.
  const [stale, setStale] = useState(false);
  const [progress, setProgress] = useState<Record<string, RunProgress>>({});
  const pending = useRef(new Map<string, (msg: ExtMessage) => void>());

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin) return;
      const data = event.data as ExtMessage;
      if (!data || data.source !== EXT || typeof data.type !== "string") return;

      if (data.type === "SKILLMATE_PONG") setInstalled(true);
      if (data.type === "SKILLMATE_ERROR" && data.reason === "extension_reloaded") {
        setInstalled(true);
        setStale(true);
      }

      if (data.type === "SKILLMATE_PROGRESS" && typeof data.runId === "string") {
        const { stage, page, pageTo, reason } = data as unknown as RunProgress & { runId: string };
        setProgress((prev) => ({ ...prev, [data.runId as string]: { stage, page, pageTo, reason } }));
      }

      if (data.requestId && pending.current.has(data.requestId)) {
        const resolve = pending.current.get(data.requestId)!;
        pending.current.delete(data.requestId);
        resolve(data);
      }
    };
    window.addEventListener("message", onMessage);

    window.postMessage({ source: PAGE, type: "SKILLMATE_PING", requestId: newId() }, window.location.origin);
    const t = setTimeout(() => setInstalled((v) => (v === null ? false : v)), 1500);
    return () => {
      window.removeEventListener("message", onMessage);
      clearTimeout(t);
    };
  }, []);

  const request = useCallback(
    (type: string, payload: Record<string, unknown>, timeoutMs: number): Promise<ExtMessage | null> =>
      new Promise((resolve) => {
        const requestId = newId();
        const timer = setTimeout(() => {
          pending.current.delete(requestId);
          resolve(null);
        }, timeoutMs);
        pending.current.set(requestId, (msg) => {
          clearTimeout(timer);
          resolve(msg);
        });
        window.postMessage({ source: PAGE, type, requestId, ...payload }, window.location.origin);
      }),
    [],
  );

  // "ok" | "not_logged_in" | "extension_reloaded" | "no_response"
  const checkLogin = useCallback(async (): Promise<string> => {
    const res = await request("SKILLMATE_CHECK_LOGIN", {}, 45_000);
    if (!res) return "no_response";
    if (res.reason === "extension_reloaded") return "extension_reloaded";
    return res.loggedIn === true ? "ok" : "not_logged_in";
  }, [request]);

  const source = useCallback(
    (args: { runId: string; plan: SourcingSearchPlan; pageFrom: number; pageTo: number }) => {
      setProgress((prev) => ({ ...prev, [args.runId]: { stage: "searching" } }));
      window.postMessage(
        { source: PAGE, type: "SKILLMATE_SOURCE", requestId: newId(), ...args, apiBase: apiBase(), token },
        window.location.origin,
      );
    },
    [token],
  );

  const reveal = useCallback(
    async (args: { profileId: string; name: string; sourceLink: string }):
      Promise<{ ok: boolean; reason?: string; candidateError?: string }> => {
      const res = await request("SKILLMATE_REVEAL", { ...args, apiBase: apiBase(), token }, 120_000);
      if (!res) return { ok: false, reason: "timeout" };
      return {
        ok: res.ok === true,
        reason: typeof res.reason === "string" ? res.reason : undefined,
        candidateError: typeof res.candidateError === "string" ? res.candidateError : undefined,
      };
    },
    [request, token],
  );

  const cancel = useCallback((runId: string) => {
    window.postMessage({ source: PAGE, type: "SKILLMATE_CANCEL", requestId: newId(), runId }, window.location.origin);
  }, []);

  return { installed, stale, checkLogin, source, reveal, cancel, progress };
}
