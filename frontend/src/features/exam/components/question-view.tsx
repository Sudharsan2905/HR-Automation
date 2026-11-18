"use client";

import { cn } from "@/lib/utils";
import type { ExamAnswer, ExamAnswerMap, ExamQuestion } from "@/types/level1-exam";
import { MIN_ESSAY_CHARS } from "../lib/constants";
import { RichText } from "./rich-text";

type SetAnswer = (questionId: string, answer: ExamAnswer) => void;

export function questionTypeLabel(type: string) {
  if (type === "essay") return "Essay";
  if (type === "mcq_multiple") return "Multiple Choice";
  return "Single Choice";
}

function OptionList({
  q,
  answers,
  setAnswer,
  multiple,
}: {
  q: ExamQuestion;
  answers: ExamAnswerMap;
  setAnswer: SetAnswer;
  multiple: boolean;
}) {
  const current = answers[q.id];
  return (
    <div className="mt-4 space-y-2">
      {q.options?.map((opt) => {
        const selected = multiple
          ? ((current as string[] | undefined) ?? []).includes(opt.id)
          : current === opt.id;
        return (
          <label
            key={opt.id}
            className={cn(
              "flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/50",
              selected && "border-primary bg-primary/5"
            )}
          >
            <input
              type={multiple ? "checkbox" : "radio"}
              name={q.id}
              className="size-4 accent-primary"
              checked={selected}
              onChange={() => {
                if (!multiple) return setAnswer(q.id, opt.id);
                const cur = (current as string[] | undefined) ?? [];
                setAnswer(q.id, selected ? cur.filter((v) => v !== opt.id) : [...cur, opt.id]);
              }}
            />
            {opt.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={opt.image_url} alt="" className="max-h-24 rounded" />
            ) : null}
            {opt.text ? <span className="text-sm">{opt.text}</span> : null}
          </label>
        );
      })}
    </div>
  );
}

function Essay({ q, answers, setAnswer }: { q: ExamQuestion; answers: ExamAnswerMap; setAnswer: SetAnswer }) {
  const value = (answers[q.id] as string | undefined) ?? "";
  const len = value.length;
  const valid = len >= MIN_ESSAY_CHARS;
  const showError = len > 0 && !valid;
  const remaining = MIN_ESSAY_CHARS - len;
  return (
    <div className="mt-4">
      <textarea
        rows={10}
        value={value}
        placeholder="Write your answer here..."
        onChange={(e) => setAnswer(q.id, e.target.value)}
        className={cn(
          "w-full resize-y rounded-lg border bg-background p-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
          showError && "border-destructive"
        )}
      />
      <div className="mt-1 flex justify-between text-xs">
        {showError ? (
          <span className="text-destructive">
            {remaining} more character{remaining === 1 ? "" : "s"} needed
          </span>
        ) : valid ? (
          <span className="text-emerald-600">Minimum length met</span>
        ) : (
          <span className="text-muted-foreground">Minimum {MIN_ESSAY_CHARS} characters required</span>
        )}
        <span className={cn(showError && "text-destructive", valid && "text-emerald-600")}>
          {len} / {MIN_ESSAY_CHARS}
        </span>
      </div>
    </div>
  );
}

export function QuestionView({
  question,
  answers,
  setAnswer,
}: {
  question: ExamQuestion;
  answers: ExamAnswerMap;
  setAnswer: SetAnswer;
}) {
  return (
    <div className="rounded-xl border bg-background p-5 sm:p-6">
      {question.text ? <RichText>{question.text}</RichText> : null}
      {question.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={question.image_url} alt="" className="mt-3 max-h-80 rounded" />
      ) : null}
      {question.type === "essay" ? (
        <Essay q={question} answers={answers} setAnswer={setAnswer} />
      ) : (
        <OptionList
          q={question}
          answers={answers}
          setAnswer={setAnswer}
          multiple={question.type === "mcq_multiple"}
        />
      )}
    </div>
  );
}
