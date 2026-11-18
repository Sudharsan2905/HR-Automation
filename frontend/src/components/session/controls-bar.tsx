"use client";

import { Button } from "@/components/ui/button";
import { Pause, Play, PhoneOff } from "lucide-react";

interface ControlsBarProps {
  connected: boolean;
  aiPaused: boolean;
  completing: boolean;
  onTogglePause: () => void;
  onComplete: () => void;
}

export function ControlsBar({ connected, aiPaused, completing, onTogglePause, onComplete }: ControlsBarProps) {
  return (
    <div className="flex items-center justify-center gap-4 p-4 border-t border-white/10 bg-[#0a0e27]/90">
      <Button
        onClick={onTogglePause}
        variant="outline"
        className="border-white/20 text-white/70 hover:bg-white/10 gap-2"
        disabled={!connected}
      >
        {aiPaused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
        {aiPaused ? "Resume AI" : "Pause AI"}
      </Button>
      <Button
        onClick={onComplete}
        disabled={completing || !connected}
        className="bg-red-500 hover:bg-red-600 text-white gap-2"
        size="lg"
      >
        <PhoneOff className="h-5 w-5" />
        {completing ? "Ending..." : "End Interview"}
      </Button>
    </div>
  );
}
