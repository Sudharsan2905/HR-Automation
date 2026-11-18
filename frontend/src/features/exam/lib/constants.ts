import type { MalpracticeType } from "@/types/level1-exam";

export const MIN_ESSAY_CHARS = 150;
export const VIOLATION_DEBOUNCE_MS = 2_000;
export const WS_HEARTBEAT_INTERVAL_MS = 10_000;
export const MALPRACTICE_LIMIT = 3;
export const DEVTOOLS_SIZE_THRESHOLD = 160;

export const VIOLATION_MESSAGES: Record<MalpracticeType, string> = {
  tab_switch: "Tab switch detected",
  fullscreen_exit: "Fullscreen exit detected",
  screen_share_stop: "Screen sharing stopped",
  devtools_open: "Developer tools opened",
  copy_paste: "Copy/paste attempted",
  keyboard_shortcut: "Keyboard shortcut blocked",
  multiple_faces: "Multiple faces detected",
  face_absence: "Face not visible",
  eye_direction: "Looking away from screen",
  background_noise: "Background noise detected",
  audio_violation: "Audio violation detected",
  speaking: "Speaking detected",
  notification_received: "OS notification interaction detected",
};

/** First occurrence only warns locally; the second is reported to the server. */
export const TWO_STRIKE_TYPES = new Set<MalpracticeType>([
  "face_absence",
  "multiple_faces",
  "eye_direction",
  "audio_violation",
  "speaking",
  "background_noise",
]);

export const examPaths = {
  entry: (l: string) => `/exam/${l}`,
  instructions: (l: string) => `/exam/${l}/instructions`,
  session: (l: string, id: string) => `/exam/${l}/session/${id}`,
  completed: (l: string) => `/exam/${l}/completed`,
};

export function isDevToolsOpen(): boolean {
  return (
    globalThis.outerWidth - globalThis.innerWidth > DEVTOOLS_SIZE_THRESHOLD ||
    globalThis.outerHeight - globalThis.innerHeight > DEVTOOLS_SIZE_THRESHOLD
  );
}
