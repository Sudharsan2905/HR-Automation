"use client";

import { useCallback, useEffect, useRef } from "react";
import { saveExamAnswer } from "@/lib/api/level1-exam";
import type { ExamAnswer } from "@/types/level1-exam";

/** Debounced per-question autosave. The UI never waits on the network. */
export function useAnswerSync(submissionId: string, debounceMs = 500) {
  const answers = useRef<Record<string, ExamAnswer>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const sync = useCallback(
    async (questionId: string, answer: ExamAnswer) => {
      try {
        await saveExamAnswer(submissionId, questionId, answer);
      } catch {
        /* best-effort; the candidate can re-answer */
      }
    },
    [submissionId]
  );

  const setAnswer = useCallback(
    (questionId: string, answer: ExamAnswer) => {
      answers.current[questionId] = answer;
      clearTimeout(timers.current[questionId]);
      timers.current[questionId] = setTimeout(() => {
        delete timers.current[questionId];
        void sync(questionId, answer);
      }, debounceMs);
    },
    [sync, debounceMs]
  );

  const flushPending = useCallback(async () => {
    const entries = Object.entries(timers.current);
    timers.current = {};
    await Promise.all(
      entries.map(([qid, timer]) => {
        clearTimeout(timer);
        return sync(qid, answers.current[qid]);
      })
    );
  }, [sync]);

  useEffect(() => {
    const t = timers.current;
    return () => Object.values(t).forEach(clearTimeout);
  }, []);

  return { setAnswer, flushPending };
}
