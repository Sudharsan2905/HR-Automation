"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Camera, Check, Loader2, Mic, Monitor, Wifi } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  examErrorMessage,
  getExamAssessment,
  isExamUnauthorized,
  startExamAssessment,
} from "@/lib/api/level1-exam";
import type { ExamAssessment } from "@/types/level1-exam";
import { ExamDialog } from "../components/exam-dialog";
import { ExamHeader } from "../components/exam-header";
import { StatusScreen } from "../components/status-screen";
import { useExamAuth } from "../hooks/use-exam-auth";
import { examPaths, isDevToolsOpen } from "../lib/constants";
import { markAssessmentDone, saveSubmissionId } from "../lib/session-storage";
import { storeMonitoringStreams } from "../lib/stream-store";

type Net = "checking" | "connected" | "disconnected";

const RULES = [
  "Ensure you have a stable internet connection throughout the assessment.",
  "The assessment runs in fullscreen mode — do not exit fullscreen at any point.",
  "Do not open Developer Tools or AI tools at any point during the assessment.",
  "Each round has a time limit. The round auto-submits when time runs out.",
  "Once you submit a round, you cannot go back to change answers.",
  "Read each question carefully before answering.",
];

function PermissionRow({
  icon,
  title,
  granted,
  loading,
  label,
  onGrant,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  granted: boolean;
  loading: boolean;
  label: string;
  onGrant: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border p-3">
      <span className="text-muted-foreground">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        {children}
      </div>
      <Button size="sm" variant={granted ? "secondary" : "default"} disabled={granted || loading} onClick={onGrant}>
        {loading ? <Loader2 className="animate-spin" /> : granted ? <Check /> : null}
        {granted ? "Granted" : label}
      </Button>
    </div>
  );
}

export function InstructionsPage({ shareLink }: { shareLink: string }) {
  const router = useRouter();
  const { mounted, token, isCandidate, candidateName } = useExamAuth();

  const [assessment, setAssessment] = useState<ExamAssessment | null>(null);
  const [loading, setLoading] = useState(true);
  const [net, setNet] = useState<Net>("checking");
  const [starting, setStarting] = useState(false);
  const [video, setVideo] = useState(false);
  const [audio, setAudio] = useState(false);
  const [screen, setScreen] = useState(false);
  const [busy, setBusy] = useState<"" | "camera" | "mic" | "screen">("");
  const [screenModal, setScreenModal] = useState(false);
  const startingRef = useRef(false);
  const previewRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (mounted && !token) router.replace(examPaths.entry(shareLink));
  }, [mounted, token, router, shareLink]);

  useEffect(() => {
    if (!isCandidate) return;
    let cancelled = false;
    getExamAssessment(shareLink)
      .then((a) => {
        if (cancelled) return;
        setAssessment(a);
        setNet("connected");
      })
      .catch((e) => {
        if (cancelled) return;
        if (!isExamUnauthorized(e)) toast.error("Assessment not found");
        setNet(navigator.onLine ? "checking" : "disconnected");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [isCandidate, shareLink]);

  useEffect(() => {
    const off = () => setNet("disconnected");
    const on = () => setNet((n) => (n === "disconnected" ? "checking" : n));
    window.addEventListener("offline", off);
    window.addEventListener("online", on);
    return () => {
      window.removeEventListener("offline", off);
      window.removeEventListener("online", on);
    };
  }, []);

  if (!mounted || loading)
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
      </div>
    );
  if (!assessment)
    return (
      <StatusScreen
        icon={<Wifi className="size-6" />}
        title="Assessment not found"
        description="This link is not valid or the assessment is unavailable."
        actionLabel="Back"
        onAction={() => router.replace(examPaths.entry(shareLink))}
      />
    );

  const mon = assessment.monitoring_config ?? {};
  const monitored = assessment.accessibility === "monitoring";
  const needsVideo = monitored && !!mon.video_monitoring;
  const needsAudio = monitored && !!mon.audio_monitoring;
  const needsScreen = monitored && !!mon.screenshot_enabled;
  const ready =
    net === "connected" && (!needsVideo || video) && (!needsAudio || audio) && (!needsScreen || screen);
  const totalQ = assessment.rounds?.reduce((a, r) => a + (r.question_count || 0), 0) ?? 0;
  const totalMin = assessment.rounds?.reduce((a, r) => a + (r.max_duration_minutes || 0), 0) ?? 0;

  const grantCamera = async () => {
    setBusy("camera");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      const track = s.getVideoTracks()[0];
      storeMonitoringStreams({ camera: new MediaStream([track]) });
      setVideo(true);
      requestAnimationFrame(() => {
        if (previewRef.current) previewRef.current.srcObject = new MediaStream([track]);
      });
    } catch {
      toast.error("Please allow camera access to proceed");
    } finally {
      setBusy("");
    }
  };
  const grantMic = async () => {
    setBusy("mic");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      storeMonitoringStreams({ audio: new MediaStream([s.getAudioTracks()[0]]) });
      setAudio(true);
    } catch {
      toast.error("Please allow microphone access to proceed");
    } finally {
      setBusy("");
    }
  };
  const grantScreen = async () => {
    setBusy("screen");
    try {
      const s = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: "monitor" } as MediaTrackConstraints,
        audio: false,
      });
      const surface = (s.getVideoTracks()[0].getSettings() as MediaTrackSettings & { displaySurface?: string })
        .displaySurface;
      if (surface !== undefined && surface !== "monitor") {
        s.getTracks().forEach((t) => t.stop());
        setScreenModal(true);
        return;
      }
      storeMonitoringStreams({ screen: s });
      setScreen(true);
    } catch {
      toast.error("Screen sharing access is required to proceed");
    } finally {
      setBusy("");
    }
  };

  const start = async () => {
    if (startingRef.current) return;
    if (isDevToolsOpen()) return void toast.error("Please close Developer Tools before starting the assessment");
    if (!ready) return void toast.error("Please complete the required setup first");
    startingRef.current = true;
    setStarting(true);
    try {
      const sub = await startExamAssessment(shareLink);
      saveSubmissionId(shareLink, sub.id);
      router.replace(examPaths.session(shareLink, sub.id));
    } catch (e) {
      const msg = examErrorMessage(e);
      if (msg.toLowerCase().includes("already completed")) {
        markAssessmentDone(shareLink);
        router.replace(examPaths.completed(shareLink));
      } else if (isExamUnauthorized(e)) {
        router.replace(`${examPaths.entry(shareLink)}?expired=1`);
      } else {
        toast.error(msg || "Failed to start assessment");
      }
    } finally {
      startingRef.current = false;
      setStarting(false);
    }
  };

  return (
    <div className="min-h-screen bg-muted/20">
      <ExamHeader candidateName={candidateName} />
      <div className="mx-auto max-w-3xl space-y-6 p-4 sm:p-8">
        <div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h1 className="text-2xl font-semibold">{assessment.name}</h1>
            <Badge variant={net === "connected" ? "secondary" : "destructive"}>
              {net === "connected" ? "Internet Connected" : net === "checking" ? "Checking…" : "Internet Disconnected"}
            </Badge>
          </div>
          {assessment.description ? <p className="mt-2 text-sm text-muted-foreground">{assessment.description}</p> : null}
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            [`${totalMin} min`, "Total Duration"],
            [String(totalQ), "Questions"],
            [monitored ? "Monitored" : "Normal", "Mode"],
            [String(assessment.rounds?.length || 1), "Rounds"],
          ].map(([v, l]) => (
            <div key={l} className="rounded-lg border bg-background p-3 text-center">
              <div className="text-lg font-semibold">{v}</div>
              <div className="text-xs text-muted-foreground">{l}</div>
            </div>
          ))}
        </div>

        <section className="space-y-2 rounded-xl border bg-background p-5">
          <h2 className="font-semibold">General Instructions</h2>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
            {RULES.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          {monitored ? (
            <p className="mt-3 rounded-md bg-amber-500/10 p-3 text-sm text-amber-700">
              Enable Do Not Disturb mode on your device before starting to avoid interruptions.
            </p>
          ) : null}
        </section>

        {monitored && (needsVideo || needsAudio || needsScreen) ? (
          <section className="space-y-3 rounded-xl border bg-background p-5">
            <h2 className="font-semibold">Assessment Setup</h2>
            {needsVideo ? (
              <PermissionRow icon={<Camera className="size-5" />} title="Camera Access" granted={video} loading={busy === "camera"} label="Grant Camera Access" onGrant={() => void grantCamera()}>
                {video ? <video ref={previewRef} autoPlay muted playsInline className="mt-2 h-24 rounded bg-black" /> : null}
              </PermissionRow>
            ) : null}
            {needsAudio ? (
              <PermissionRow icon={<Mic className="size-5" />} title="Microphone Access" granted={audio} loading={busy === "mic"} label="Grant Microphone Access" onGrant={() => void grantMic()} />
            ) : null}
            {needsScreen ? (
              <PermissionRow icon={<Monitor className="size-5" />} title="Screen Share Access" granted={screen} loading={busy === "screen"} label="Share Screen" onGrant={() => void grantScreen()} />
            ) : null}
          </section>
        ) : null}

        <div className="flex flex-col items-center justify-between gap-4 rounded-xl border bg-background p-5 sm:flex-row">
          <div>
            <p className="font-semibold">All the Best{candidateName ? `, ${candidateName}` : ""}!</p>
            <p className="text-sm text-muted-foreground">Take a deep breath, stay confident, and do your best.</p>
          </div>
          <Button size="lg" disabled={!ready || starting} onClick={() => void start()}>
            {starting ? <Loader2 className="animate-spin" /> : null}
            {monitored && !ready && net === "connected" ? "Grant Required Access to Continue" : "Start Assessment"}
          </Button>
        </div>
      </div>

      <ExamDialog
        open={screenModal}
        mandatory
        title="Entire Screen Required"
        footer={
          <>
            <Button variant="outline" onClick={() => setScreenModal(false)}>Cancel</Button>
            <Button
              onClick={() => {
                setScreenModal(false);
                void grantScreen();
              }}
            >
              Try Again
            </Button>
          </>
        }
      >
        You shared a window or browser tab instead of your entire screen. Click Try Again, open the Entire Screen tab, select your monitor and click Share.
      </ExamDialog>
    </div>
  );
}
