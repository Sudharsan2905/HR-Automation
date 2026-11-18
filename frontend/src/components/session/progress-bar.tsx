"use client";

interface ProgressBarProps {
  current: number;
  total: number;
}

export function SessionProgressBar({ current, total }: ProgressBarProps) {
  const percent = total > 0 ? ((current + 1) / total) * 100 : 0;

  return (
    <div className="flex items-center gap-3 text-sm text-white/70">
      <span>Q{current + 1}/{total}</span>
      <div className="flex-1 h-1.5 bg-white/10 rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-[#00e5ff] to-[#7c3aed] rounded-full transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
