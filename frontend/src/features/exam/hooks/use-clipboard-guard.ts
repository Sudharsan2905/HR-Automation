"use client";

import { useEffect } from "react";
import { toast } from "sonner";

/** Blocks copy/cut/paste, right-click, F12 and print/cut shortcuts during the exam. */
export function useClipboardGuard(enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const blockedCtrl = new Set(["p", "x", "a", "c", "v"]);

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "F12") {
        e.preventDefault();
        toast.error("Developer Tools are not allowed during the assessment");
        return;
      }
      if ((e.ctrlKey || e.metaKey) && blockedCtrl.has(e.key.toLowerCase())) {
        e.preventDefault();
        toast.error("This action is not allowed during the assessment");
      }
    };
    const onClipboard = (e: ClipboardEvent) => {
      e.preventDefault();
      const action = e.type === "copy" ? "Copy" : e.type === "paste" ? "Paste" : "Cut";
      toast.error(`${action} action is not allowed on this page`);
    };
    const onContextMenu = (e: MouseEvent) => {
      e.preventDefault();
      toast.error("Right-click is not allowed during the assessment");
    };

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("copy", onClipboard);
    document.addEventListener("paste", onClipboard);
    document.addEventListener("cut", onClipboard);
    document.addEventListener("contextmenu", onContextMenu);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("copy", onClipboard);
      document.removeEventListener("paste", onClipboard);
      document.removeEventListener("cut", onClipboard);
      document.removeEventListener("contextmenu", onContextMenu);
    };
  }, [enabled]);
}
