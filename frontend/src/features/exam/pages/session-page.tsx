"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Menu } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useExamStore } from "@/stores/exam-store";
import type { MalpracticeType } from "@/types/level1-exam";
import { ConnectionOverlay } from "../components/connection-overlay";
import { ExamDialog } from "../components/exam-dialog";
import { ExamHeader } from "../components/exam-header";
import { ExamSetupScreen } from "../components/exam-setup-screen";
import { MalpracticeWarning } from "../components/malpractice-warning";
import { MonitoringPanel, TimerCard } from "../components/monitoring-panel";
import { ProgressSidebar } from "../components/progress-sidebar";
import { QuestionView, questionTypeLabel } from "../components/question-view";
import { RoundInstructions } from "../components/round-instructions";
import { StatusScreen } from "../components/status-screen";
import { ExamPhase, useExamOrchestrator } from "../hooks/use-exam-orchestrator";
import { useClipboardGuard } from "../hooks/use-clipboard-guard";
import { useExamAuth } from "../hooks/use-exam-auth";
import { useExamProctoring, useIsFullscreen } from "../hooks/use-exam-proctoring";
import { useExamSession } from "../hooks/use-exam-session";
import { useMalpractice } from "../hooks/use-malpractice";
import { useScreenCapture } from "../hooks/use-screen-capture";
import { MIN_ESSAY_CHARS, VIOLATION_DEBOUNCE_MS, examPaths } from "../lib/constants";
import { clearMonitoringStreams } from "../lib/stream-store";

export function SessionPage({ shareLink, submissionId }: { shareLink: string; submissionId: string }) {
  const router = useRouter();
  const { mounted, token, candidateName } = useExamAuth();
  const terminated = useExamStore((s) => s.isTerminated);
  const resetExam = useExamStore((s) => s.reset);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [fullscreenBlocked, setFullscreenBlocked] = useState(false);
  const [screenBlocked, setScreenBlocked] = useState(false);
  const [initScreen, setInitScreen] = useState(false);

  const s = useExamSession({ shareLink, submissionId, token });
  const isFullscreen = useIsFullscreen();
  const screen = useScreenCapture({ shouldInitialize: initScreen });

  // Proctoring needs orchestrator gates; orchestrator needs proctoring readiness. The
  // readiness flags and gates are wired through state below.
  const [ready, setReady] = useState({ camera: false, audio: false });
  const orch = useExamOrchestrator({
    enabled: !s.isLoading && !!s.roundData,
    config: s.monitoringConfig,
    networkStatus: s.networkStatus,
    isCameraReady: ready.camera,
    isAudioReady: ready.audio,
    isScreenShareReady: screen.isCapturing,
    isFullscreen,
  });

  useEffect(() => {
    if (orch.shouldAcquireScreen && !initScreen) setInitScreen(true);
  }, [orch.shouldAcquireScreen, initScreen]);

  const [cooldowns] = useState<Partial<Record<string, number>>>({});
  const { flagViolation } = useMalpractice({
    submissionId,
    monitoringConfig: s.monitoringConfig,
    onTerminated: useCallback(() => {
      clearMonitoringStreams();
      router.replace(examPaths.entry(shareLink));
    }, [router, shareLink]),
    captureScreenFrame: screen.captureFrame,
  });
  const { examActiveRef } = orch;
  const flagSafe = useCallback(
    (type: MalpracticeType, description?: string) => {
      if (!examActiveRef.current) return;
      const now = performance.now();
      if (now - (cooldowns[type] ?? 0) < VIOLATION_DEBOUNCE_MS) return;
      cooldowns[type] = now;
      void flagViolation({ type, description });
    },
    [flagViolation, examActiveRef, cooldowns]
  );

  const proctor = useExamProctoring({
    config: s.monitoringConfig,
    submissionId,
    gates: {
      camera: orch.shouldAcquireCamera,
      audio: orch.shouldAcquireAudio,
      fullscreen: orch.shouldEnforceFullscreen,
    },
    examActiveRef,
    isPermissionFlowActiveRef: orch.isPermissionFlowActiveRef,
    isScreenCapturing: screen.isCapturing,
    captureFrame: screen.captureFrame,
    flagViolation: flagSafe,
    onCameraError: (m) => {
      orch.setPhaseError(m);
    },
    onFullscreenBlocked: () => setFullscreenBlocked(true),
  });

  // Mirror proctoring readiness into the orchestrator inputs.
  const { isCameraReady, isAudioReady } = proctor;
  useEffect(() => {
    setReady((r) =>
      r.camera === isCameraReady && r.audio === isAudioReady
        ? r
        : { camera: isCameraReady, audio: isAudioReady }
    );
  }, [isCameraReady, isAudioReady]);

  useEffect(() => {
    if (isFullscreen && fullscreenBlocked) setFullscreenBlocked(false);
  }, [isFullscreen, fullscreenBlocked]);

  const needsScreen = !!s.monitoringConfig.screenshot_enabled;
  const active = orch.phase === ExamPhase.ACTIVE;
  useEffect(() => {
    if (needsScreen && screen.isInitialized && active && !screen.isCapturing) setScreenBlocked(true);
    else if (screen.isCapturing) setScreenBlocked(false);
  }, [needsScreen, screen.isInitialized, active, screen.isCapturing]);

  useClipboardGuard(true);

  // Leaving the session releases every device.
  const { stopScreenCapture } = screen;
  useEffect(
    () => () => {
      stopScreenCapture();
      clearMonitoringStreams();
      resetExam();
    },
    [stopScreenCapture, resetExam]
  );

  // Key expired / logged out mid-exam.
  useEffect(() => {
    if (mounted && !token) router.replace(`${examPaths.entry(shareLink)}?expired=1`);
  }, [mounted, token, router, shareLink]);

  const withPermissionGuard = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T> => {
      orch.markPermissionFlowStart();
      try {
        return await fn();
      } finally {
        orch.markPermissionFlowEnd();
      }
    },
    [orch]
  );

  const shareScreen = useCallback(async () => {
    const ok = await withPermissionGuard(screen.startScreenCapture);
    orch.setPhaseError(ok ? null : "Screen sharing was denied or cancelled. Please share your entire screen.");
  }, [withPermissionGuard, screen.startScreenCapture, orch]);

  // ── render ──
  if (!mounted || s.isLoading)
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
      </div>
    );
  if (s.loadError || terminated)
    return (
      <StatusScreen
        icon={<span className="text-2xl">!</span>}
        title={terminated ? "Assessment Terminated" : "Unable to start"}
        description={
          terminated
            ? "Your session was ended after repeated violations. Please contact the administrator for re-access."
            : (s.loadError ?? "")
        }
        actionLabel="Back"
        onAction={() => router.replace(examPaths.entry(shareLink))}
      />
    );
  const round = s.roundData;
  if (!round) return null;

  if (orch.phase < ExamPhase.ACTIVE)
    return (
      <ExamSetupScreen
        phase={orch.phase}
        phaseLabel={orch.phaseLabel}
        phaseError={orch.phaseError}
        config={s.monitoringConfig}
        onShareScreen={() => void shareScreen()}
        onRequestFullscreen={() => void proctor.requestFullscreen()}
        onRetryCamera={() => {
          orch.setPhaseError(null);
          proctor.retryCamera();
        }}
        onRetryAudio={() => {
          orch.setPhaseError(null);
          proctor.retryAudio();
        }}
      />
    );

  const questions = round.questions;
  if (questions.length === 0)
    return (
      <StatusScreen
        icon={<span className="text-2xl">?</span>}
        title="No questions"
        description="No questions found for this round. Please contact the administrator."
      />
    );

  const q = questions[Math.min(s.currentIdx, questions.length - 1)];
  const answeredCount = Object.keys(s.answers).length;
  const isLast = s.currentIdx >= questions.length - 1;
  const essaysShort = questions.filter(
    (x) => x.type === "essay" && ((s.answers[x.id] as string) ?? "").length < MIN_ESSAY_CHARS
  );
  const roundCfg = s.assessmentRounds.find((r) => r.round_number === round.round_number) ?? {
    round_number: round.round_number,
    question_count: questions.length,
    max_duration_minutes: round.max_duration_minutes,
  };
  const { hh, mm, ss } = s.timer.formattedTime;

  const onNext = () => {
    if (q.type === "essay" && ((s.answers[q.id] as string) ?? "").length < MIN_ESSAY_CHARS) {
      toast.error(`Please write at least ${MIN_ESSAY_CHARS} characters before moving on.`);
      return;
    }
    s.navigateTo(s.currentIdx + 1);
  };
  const onSubmit = () => {
    if (essaysShort.length > 0) {
      toast.error(
        `${essaysShort.length} essay answer${essaysShort.length === 1 ? "" : "s"} must be at least ${MIN_ESSAY_CHARS} characters.`
      );
      return;
    }
    setShowConfirm(true);
  };
  const goHome = () => router.replace(examPaths.completed(shareLink));

  return (
    <div className="flex min-h-screen flex-col bg-muted/20">
      <ConnectionOverlay status={s.networkStatus} />
      <ExamHeader candidateName={candidateName} />
      <div className="relative flex flex-1">
        <aside
          className={`${sidebarOpen ? "block" : "hidden"} absolute inset-y-0 left-0 z-30 w-72 overflow-y-auto border-r bg-background lg:static lg:block`}
        >
          <ProgressSidebar
            roundNumber={round.round_number}
            rounds={s.assessmentRounds}
            questions={questions}
            currentIdx={s.currentIdx}
            answers={s.answers}
            visited={s.visited}
            onNavigate={(i) => {
              s.navigateTo(i);
              setSidebarOpen(false);
            }}
          />
        </aside>

        <main className="min-w-0 flex-1 space-y-4 p-4 sm:p-6">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Button size="icon-sm" variant="outline" className="lg:hidden" onClick={() => setSidebarOpen((v) => !v)} aria-label="Toggle progress panel">
              <Menu />
            </Button>
            <span className="rounded-full bg-primary/10 px-2.5 py-0.5 font-medium text-primary">Round {round.round_number}</span>
            <span className="text-muted-foreground">Q{s.currentIdx + 1} of {questions.length}</span>
            <span className="rounded-full border px-2.5 py-0.5 text-xs">{questionTypeLabel(q.type)}</span>
          </div>
          <QuestionView question={q} answers={s.answers} setAnswer={s.setAnswer} />
          <div className="flex justify-between">
            <Button variant="outline" disabled={s.currentIdx === 0} onClick={() => s.navigateTo(Math.max(0, s.currentIdx - 1))}>
              Previous
            </Button>
            {isLast ? (
              <Button onClick={onSubmit} disabled={s.submitting}>
                {s.submitting ? <Loader2 className="animate-spin" /> : null}Submit Round
              </Button>
            ) : (
              <Button onClick={onNext}>Next</Button>
            )}
          </div>
        </main>

        <aside className="hidden w-72 shrink-0 space-y-4 border-l bg-background p-4 xl:block">
          <TimerCard hh={hh} mm={mm} ss={ss} low={s.timer.isLowTime} paused={!s.timerActive && s.interviewStarted} />
          <MonitoringPanel
            config={s.monitoringConfig}
            isScreenCapturing={screen.isCapturing}
            networkStatus={s.networkStatus}
            videoRef={proctor.videoRef}
            bindVideo={proctor.bindCamera}
            analyserRef={proctor.analyserRef}
            audioActive={!!s.monitoringConfig.audio_monitoring}
            onFaceWarning={() => flagSafe("face_absence")}
          />
        </aside>
      </div>

      <RoundInstructions
        open={!s.interviewStarted && !s.submitting}
        roundNumber={round.round_number}
        roundConfig={roundCfg}
        totalRounds={s.assessmentRounds.length || 1}
        onStart={s.beginRound}
      />

      <ExamDialog
        open={showConfirm}
        title="Submit Round?"
        onClose={() => setShowConfirm(false)}
        footer={
          <>
            <Button variant="outline" onClick={() => setShowConfirm(false)}>Review Answers</Button>
            <Button
              disabled={s.submitting}
              onClick={() => {
                setShowConfirm(false);
                void s.finishRound();
              }}
            >
              Submit
            </Button>
          </>
        }
      >
        You&apos;ve answered {answeredCount} of {questions.length} questions. Once submitted, you cannot change your answers.
      </ExamDialog>

      <MalpracticeWarning />

      <ExamDialog
        open={s.adminWarning !== null}
        mandatory
        title="Message from Administrator"
        footer={<Button onClick={() => s.setAdminWarning(null)}>Acknowledge</Button>}
      >
        {s.adminWarning}
      </ExamDialog>

      <ExamDialog
        open={s.showTimeExpired}
        mandatory
        title="Time's Up"
        footer={<Button onClick={goHome}>Continue</Button>}
      >
        Your time for this round has expired. Your answers have been automatically submitted.
      </ExamDialog>

      <ExamDialog
        open={screenBlocked}
        mandatory
        title="Screen Sharing Required"
        footer={<Button className="w-full" onClick={() => void shareScreen()}>Share Screen Again</Button>}
      >
        Screen sharing has stopped or is unavailable. This assessment requires continuous screen monitoring. Share your entire screen to resume.
      </ExamDialog>

      <ExamDialog
        open={fullscreenBlocked}
        mandatory
        title="Fullscreen Required"
        footer={<Button className="w-full" onClick={() => void proctor.requestFullscreen()}>Return to Fullscreen</Button>}
      >
        You must remain in fullscreen mode during the interview. Exiting fullscreen has been recorded as a violation. Click the button below to resume.
      </ExamDialog>
    </div>
  );
}
