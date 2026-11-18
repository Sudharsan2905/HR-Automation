import { create } from "zustand";
import type { MalpracticeType } from "@/types/level1-exam";
import { MALPRACTICE_LIMIT } from "@/features/exam/lib/constants";

interface ExamState {
  malpracticeCount: number;
  malpracticeLimit: number;
  lastViolationType: MalpracticeType | null;
  isWarningVisible: boolean;
  warningMessage: string;
  isTerminated: boolean;
  terminationReason: string | null;
  setMalpracticeCount: (n: number) => void;
  setLastViolation: (type: MalpracticeType, message: string) => void;
  dismissWarning: () => void;
  setTerminated: (reason: string) => void;
  reset: () => void;
}

const initial = {
  malpracticeCount: 0,
  malpracticeLimit: MALPRACTICE_LIMIT,
  lastViolationType: null,
  isWarningVisible: false,
  warningMessage: "",
  isTerminated: false,
  terminationReason: null,
};

export const useExamStore = create<ExamState>()((set) => ({
  ...initial,
  setMalpracticeCount: (malpracticeCount) => set({ malpracticeCount }),
  setLastViolation: (type, message) =>
    set({ lastViolationType: type, warningMessage: message, isWarningVisible: true }),
  dismissWarning: () => set({ isWarningVisible: false }),
  setTerminated: (reason) =>
    set({ isTerminated: true, terminationReason: reason, isWarningVisible: false }),
  reset: () => set(initial),
}));
