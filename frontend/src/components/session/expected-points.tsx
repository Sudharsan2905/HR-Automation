"use client";

interface ExpectedPointsProps {
  points: string[];
  questionIndex: number;
}

export function ExpectedPoints({ points, questionIndex }: ExpectedPointsProps) {
  if (points.length === 0) return null;

  return (
    <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-2">
      <h4 className="text-xs font-semibold text-white/40 uppercase tracking-wider">
        Expected Points — Q{questionIndex + 1}
      </h4>
      <ul className="space-y-1.5">
        {points.map((point, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-white/70">
            <span className="mt-1 h-1.5 w-1.5 rounded-full bg-[#00e5ff] shrink-0" />
            {point}
          </li>
        ))}
      </ul>
    </div>
  );
}
