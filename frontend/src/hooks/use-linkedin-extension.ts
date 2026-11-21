"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/stores/auth-store";
import type { SourcingSearchPlan } from "@/types/sourcing";

// Talks to the SkillMate LinkedIn Sourcing extension through window.postMessage. This is a SEPARATE
// extension from the Naukri one (use-skillmate-extension.ts): its messages are namespaced "li" so the
// two never answer each other, and either can be installed without the other. The extension's bridge.js
// content script relays between this page and its background worker.

// The oldest extension build this page works with. 1.1.0 added the search ladder (broaden the search when LinkedIn
// finds nobody); 1.2.0 takes a candidate only with an email (it opens each contact dialog), which SkillMate now insists
// on: an older build would send people without one and get nothing in. Chrome does NOT reload an unpacked extension when
// its files change, so after an update the old code keeps running until it is reloaded at chrome://extensions: refuse it.
export const LINKEDIN_EXTENSION_MIN_VERSION = "1.2.0";

/** -1 / 0 / 1 like a comparator, for dotted numeric versions ("1.10.0" > "1.9.0"). */
export function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map((n) => parseInt(n, 10) || 0);
  const pb = b.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}

const PAGE = "skillmate-li-page";
const EXT = "skillmate-li-ext";

export type LinkedinStage = "searching" | "scraping" | "contacts" | "screening" | "done" | "error";
export interface LinkedinProgress {
  stage: LinkedinStage;
  page?: number;
  pageTo?: number;
  reason?: string;
  /** stage "contacts": contact dialogs read so far / to read on this page */
  done?: number;
  total?: number;
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

export function useLinkedinExtension() {
  const token = useAuthStore((s) => s.token);
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  // The extension was reloaded/updated after this page loaded: only a page reload reconnects it.
  const [stale, setStale] = useState(false);
  const [progress, setProgress] = useState<Record<string, LinkedinProgress>>({});
  const pending = useRef(new Map<string, (msg: ExtMessage) => void>());

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin) return;
      const data = event.data as ExtMessage;
      if (!data || data.source !== EXT || typeof data.type !== "string") return;

      if (data.type === "LINKEDIN_PONG") {
        setInstalled(true);
        setStale(false);   // a fresh bridge answered: the extension was reloaded and this page is connected again
        setVersion(typeof data.version === "string" ? data.version : "0.0.0");
      }
      if (data.type === "LINKEDIN_ERROR" && data.reason === "extension_reloaded") {
        setInstalled(true);
        setStale(true);
      }

      if (data.type === "LINKEDIN_PROGRESS" && typeof data.runId === "string") {
        const { stage, page, pageTo, reason, done, total } = data as unknown as LinkedinProgress & { runId: string };
        setProgress((prev) => ({ ...prev, [data.runId as string]: { stage, page, pageTo, reason, done, total } }));
      }

      if (data.requestId && pending.current.has(data.requestId)) {
        const resolve = pending.current.get(data.requestId)!;
        pending.current.delete(data.requestId);
        resolve(data);
      }
    };
    window.addEventListener("message", onMessage);

    window.postMessage({ source: PAGE, type: "LINKEDIN_PING", requestId: newId() }, window.location.origin);
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
    const res = await request("LINKEDIN_CHECK_LOGIN", {}, 45_000);
    if (!res) return "no_response";
    if (res.reason === "extension_reloaded") return "extension_reloaded";
    return res.loggedIn === true ? "ok" : "not_logged_in";
  }, [request]);

  const source = useCallback(
    (args: { runId: string; plan: SourcingSearchPlan; pageFrom: number; pageTo: number; searchLevel?: number }) => {
      setProgress((prev) => ({ ...prev, [args.runId]: { stage: "searching" } }));
      window.postMessage(
        { source: PAGE, type: "LINKEDIN_SOURCE", requestId: newId(), ...args, apiBase: apiBase(), token },
        window.location.origin,
      );
    },
    [token],
  );

  // Read the phone/email a selected candidate shared on LinkedIn. `reason: "no_email"` is the ordinary outcome
  // for anyone who is not a 1st-degree connection.
  const reveal = useCallback(
    async (args: { profileId: string; name: string; sourceLink: string }):
      Promise<{ ok: boolean; reason?: string; candidateError?: string }> => {
      const res = await request("LINKEDIN_REVEAL", { ...args, apiBase: apiBase(), token }, 120_000);
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
    window.postMessage({ source: PAGE, type: "LINKEDIN_CANCEL", requestId: newId(), runId }, window.location.origin);
  }, []);

  // Running an older build than this page needs (see LINKEDIN_EXTENSION_MIN_VERSION): reload the extension.
  const outdated = version !== null && compareVersions(version, LINKEDIN_EXTENSION_MIN_VERSION) < 0;

  // While the extension is out of date (or cut off by a reload), ask again every few seconds: once it is reloaded at
  // chrome://extensions its fresh bridge answers, and this page recovers without a manual page reload.
  useEffect(() => {
    if (!outdated && !stale) return;
    const t = setInterval(
      () => window.postMessage({ source: PAGE, type: "LINKEDIN_PING", requestId: newId() }, window.location.origin),
      3000,
    );
    return () => clearInterval(t);
  }, [outdated, stale]);

  return { installed, version, outdated, stale, checkLogin, source, reveal, cancel, progress };
}
