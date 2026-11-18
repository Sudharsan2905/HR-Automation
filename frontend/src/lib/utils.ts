import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { JwtPayload } from "@/types/auth";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
      timeZone: "Asia/Kolkata",
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return "—";
  }
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return (
      new Date(iso).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      }) + " IST"
    );
  } catch {
    return "—";
  }
}

export function decodeJwt(token: string): JwtPayload | null {
  try {
    const base64 = token.split(".")[1];
    const json = atob(base64);
    return JSON.parse(json);
  } catch {
    return null;
  }
}

/** Normalises the candidate JWT `scope` claim to "l1" (AI exam) or "l2" (voice interview). */
export function candidateScope(scope: string | string[] | undefined | null): "l1" | "l2" | "" {
  const raw = (Array.isArray(scope) ? scope.join(" ") : scope || "").toLowerCase();
  if (/(^|[^a-z0-9])(l2|level2|level_2|level-2|2)([^a-z0-9]|$)/.test(raw)) return "l2";
  if (/(^|[^a-z0-9])(l1|level1|level_1|level-1|1)([^a-z0-9]|$)/.test(raw)) return "l1";
  return "";
}

const UMBRELLA_LABELS: Record<string, string> = { tech: "Tech", bde: "BDE", hr: "HR" };

export function umbrellaLabel(key: string) {
  return UMBRELLA_LABELS[key] ?? key;
}

export function formatSeconds(totalSeconds: number) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export function copyToClipboard(text: string): void {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text: string) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}
