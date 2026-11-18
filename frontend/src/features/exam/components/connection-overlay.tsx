import { PauseCircle, WifiOff } from "lucide-react";
import type { ExamNetworkStatus } from "@/types/level1-exam";

export function ConnectionOverlay({ status }: { status: ExamNetworkStatus }) {
  if (status === "connected") return null;
  const onHold = status === "on_hold";
  const offline = status === "offline";
  const title = onHold ? "Interview Paused" : offline ? "Connection Lost" : "Reconnecting…";
  const body = onHold
    ? "Your session has been placed on hold. Please wait — an administrator will resume your interview."
    : offline
      ? "Your internet connection was lost. Please check your network."
      : "Trying to reconnect to the interview server.";
  const hint = onHold
    ? "Once an administrator resumes your session your timer and answers will be restored."
    : "Your answers and progress are saved. The timer is paused.";
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4"
    >
      <div className="w-full max-w-md rounded-xl bg-background p-8 text-center shadow-lg">
        {onHold ? (
          <PauseCircle className="mx-auto size-10 text-amber-500" />
        ) : (
          <WifiOff className="mx-auto size-10 text-destructive" />
        )}
        <p className="mt-3 text-lg font-semibold">{title}</p>
        <p className="mt-2 text-sm text-muted-foreground">{body}</p>
        <p className="mt-3 text-xs text-muted-foreground">{hint}</p>
      </div>
    </div>
  );
}
