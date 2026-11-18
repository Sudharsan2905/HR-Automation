"use client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { ExternalLink } from "lucide-react";

export const RESDEX_URL = "https://resdex.naukri.com/";
export const RESDEX_LOGIN_MESSAGE = "Login with Naukri ResDex to continue extraction.";

export function ResdexLoginDialog({ open, onRetry, onCancel }: { open: boolean; onRetry: () => void; onCancel: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogTitle className="text-base font-medium leading-relaxed">{RESDEX_LOGIN_MESSAGE}</DialogTitle>
        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="outline" onClick={() => window.open(RESDEX_URL, "_blank", "noopener")}>
            <ExternalLink className="mr-2 h-4 w-4" /> Open Naukri ResDex
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onCancel}>Cancel</Button>
            <Button onClick={onRetry}>Retry</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
