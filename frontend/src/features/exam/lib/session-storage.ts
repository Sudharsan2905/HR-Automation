/** sessionStorage helpers scoped to the share link (tab-scoped, ephemeral). */
const sub = (l: string) => `skillmate_exam_sub_${l}`;
const done = (l: string) => `skillmate_exam_done_${l}`;

function safeSet(k: string, v: string) {
  try {
    sessionStorage.setItem(k, v);
  } catch {
    /* unavailable — server enforces security */
  }
}
function safeGet(k: string): string | null {
  try {
    return sessionStorage.getItem(k);
  } catch {
    return null;
  }
}

export const saveSubmissionId = (l: string, id: string) => safeSet(sub(l), id);
export const getSubmissionId = (l: string) => safeGet(sub(l));
export const markAssessmentDone = (l: string) => safeSet(done(l), "true");
export const isAssessmentDone = (l: string) => safeGet(done(l)) === "true";
export function clearAssessmentSession(l: string) {
  try {
    sessionStorage.removeItem(sub(l));
    sessionStorage.removeItem(done(l));
  } catch {
    /* ignore */
  }
}
