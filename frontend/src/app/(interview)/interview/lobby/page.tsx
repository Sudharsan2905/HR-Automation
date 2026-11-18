"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConditionCard } from "@/components/lobby/condition-card";
import { SessionTimer } from "@/components/session/session-timer";
import { useCamera } from "@/hooks/use-camera";
import { useAuthStore } from "@/stores/auth-store";
import { startSession } from "@/lib/api/session";
import { useSessionStore } from "@/stores/session-store";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Loader2, Camera, CameraOff, Maximize, LogOut, Monitor, Lock } from "lucide-react";
import { storeScreenStream, clearScreenStream } from "@/lib/screen-capture";
import { AudioMicCheck } from "@/components/lobby/audio-mic-check";
import { toast } from "sonner";

export default function LobbyPage() {
  const router = useRouter();
  const logout = useAuthStore((s) => s.logout);
  const { videoRef, active: cameraActive, hardwareExists, detectHardware, start: startCamera } = useCamera();
  const [fullscreen, setFullscreen] = useState(false);
  const [audioCheckPassed, setAudioCheckPassed] = useState(false);
  const [screenGranted, setScreenGranted] = useState(false);
  const [rulesAccepted, setRulesAccepted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const setSession = useSessionStore((s) => s.setSession);
  const setLobbyJoke = useSessionStore((s) => s.setLobbyJoke);
  const preparedAudioCheck = useSessionStore((s) => s.preparedAudioCheck);

  useEffect(() => {
    detectHardware();
  }, [detectHardware]);

  useEffect(() => {
    const handleFsChange = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handleFsChange);
    return () => document.removeEventListener("fullscreenchange", handleFsChange);
  }, []);

  const enterFullscreen = async () => {
    try {
      await document.documentElement.requestFullscreen();
    } catch {
      toast.error("Fullscreen not supported");
    }
  };

  const enableScreenRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: "monitor" } as MediaTrackConstraints,
        audio: false,
      });

      const videoTrack = stream.getVideoTracks()[0];
      const settings = videoTrack.getSettings() as MediaTrackSettings & { displaySurface?: string };

      if (settings.displaySurface !== "monitor") {
        stream.getTracks().forEach((t) => t.stop());
        toast.error("Please select 'Entire Screen' — not a window or tab", { duration: 4000 });
        return;
      }

      // If user manually stops sharing from the browser toolbar, reset the check
      videoTrack.onended = () => {
        setScreenGranted(false);
        clearScreenStream();
      };

      storeScreenStream(stream);
      setScreenGranted(true);
    } catch {
      toast.error("Screen recording access denied");
    }
  }, []);

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  const cameraReady = hardwareExists === false || cameraActive;
  const allReady = cameraReady && audioCheckPassed && fullscreen && screenGranted && rulesAccepted;

  const handleStart = async () => {
    setLoading(true);
    try {
      const session = await startSession(hardwareExists !== false);
      setSession(session.session_id, session.interview_id, session.total_questions, session.current_question_index, {
        cameraAvailable: session.camera_available,
        roomName: session.room_name,
        token: session.token,
        livekitUrl: session.livekit_url,
        interviewTitle: session.interview_title,
        interviewerName: session.interviewer_name,
        candidateName: session.candidate_name,
        domain: session.domain,
        domainTitle: session.domain_title,
      });
      router.push("/interview/session");
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Failed to start session");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 relative">
      {/* Logout button */}
      <Button
        variant="ghost"
        onClick={() => setLogoutOpen(true)}
        className="absolute top-4 right-4 text-white/60 hover:text-white hover:bg-white/10"
      >
        <LogOut className="mr-2 h-4 w-4" /> Logout
      </Button>

      <ConfirmDialog
        open={logoutOpen}
        onOpenChange={setLogoutOpen}
        title="Logout?"
        description="Your access key is one-time use. If you logout now, it will expire and you will need a new key from your panel member to log in again."
        confirmLabel="Logout"
        variant="destructive"
        onConfirm={handleLogout}
      />

      <div className="w-full max-w-lg space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold">Interview Lobby</h1>
          <p className="text-white/60">Complete all checks before starting</p>
          <SessionTimer />
        </div>

        {/* Camera preview */}
        <div className="aspect-video bg-white/5 rounded-lg overflow-hidden border border-white/10">
          {cameraActive ? (
            <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover" style={{ transform: "scaleX(-1)" }} />
          ) : hardwareExists === false ? (
            <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-white/40">
              <CameraOff className="h-10 w-10" />
              <span className="text-sm">No Camera Detected</span>
            </div>
          ) : (
            <div className="w-full h-full flex items-center justify-center text-white/30">
              Camera preview will appear here
            </div>
          )}
        </div>

        <div className="space-y-3">
          <ConditionCard
            label={hardwareExists === false ? "Camera — Not Available" : "Camera Access"}
            met={cameraReady}
            action={
              hardwareExists === false ? (
                <span className="text-xs text-white/40">Skipped — no hardware</span>
              ) : (
                <Button size="sm" onClick={startCamera} className="bg-[#00e5ff] text-slate-950 hover:bg-[#00e5ff]/80">
                  <Camera className="mr-2 h-4 w-4" /> Enable
                </Button>
              )
            }
          />
          <AudioMicCheck
            passed={audioCheckPassed}
            disabled={!cameraReady}
            preloadedData={preparedAudioCheck}
            onPass={(joke) => { setAudioCheckPassed(true); setLobbyJoke(joke); }}
          />
          <ConditionCard
            label="Screen Recording (Entire Screen)"
            met={screenGranted}
            action={
              audioCheckPassed ? (
                <Button size="sm" onClick={enableScreenRecording} className="bg-[#00e5ff] text-slate-950 hover:bg-[#00e5ff]/80">
                  <Monitor className="mr-2 h-4 w-4" /> Enable
                </Button>
              ) : (
                <div className="flex items-center gap-1.5 text-xs text-white/25">
                  <Lock className="h-3.5 w-3.5" /> Complete mic test first
                </div>
              )
            }
          />
          <ConditionCard
            label="Rules Acknowledged"
            met={rulesAccepted}
            action={
              <div className="flex items-center gap-2">
                <Checkbox
                  id="rules"
                  checked={rulesAccepted}
                  disabled={!screenGranted}
                  onCheckedChange={(c) => setRulesAccepted(!!c)}
                  className="border-white/40 data-[state=checked]:bg-[#00e5ff] data-[state=checked]:border-[#00e5ff] disabled:opacity-25 disabled:cursor-not-allowed"
                />
                <label htmlFor="rules" className={`text-xs cursor-pointer ${screenGranted ? "text-white/60" : "text-white/25"}`}>
                  Tab switching will be logged
                </label>
              </div>
            }
          />
          <ConditionCard
            label="Fullscreen Mode"
            met={fullscreen}
            action={
              rulesAccepted ? (
                <Button size="sm" onClick={enterFullscreen} className="bg-[#00e5ff] text-slate-950 hover:bg-[#00e5ff]/80">
                  <Maximize className="mr-2 h-4 w-4" /> Enter
                </Button>
              ) : (
                <div className="flex items-center gap-1.5 text-xs text-white/25">
                  <Lock className="h-3.5 w-3.5" /> Accept rules first
                </div>
              )
            }
          />
        </div>

        <Button
          onClick={handleStart}
          disabled={!allReady || loading}
          className="w-full bg-[#00e5ff] text-slate-950 hover:bg-[#00e5ff]/90"
          size="lg"
        >
          {loading && <Loader2 className="mr-2 h-5 w-5 animate-spin" />}
          Start Interview
        </Button>
      </div>
    </div>
  );
}
