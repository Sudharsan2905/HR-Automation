"use client";

import type { ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** Modal that can be made mandatory (no ESC / outside-click / close button). */
export function ExamDialog({
  open,
  title,
  children,
  footer,
  mandatory = false,
  onClose,
  className,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  mandatory?: boolean;
  onClose?: () => void;
  className?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !mandatory && onClose?.()}>
      <DialogContent
        showCloseButton={!mandatory}
        className={className}
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => mandatory && e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="sr-only">{title}</DialogDescription>
        </DialogHeader>
        <div className="text-sm text-muted-foreground">{children}</div>
        {footer ? <DialogFooter>{footer}</DialogFooter> : null}
      </DialogContent>
    </Dialog>
  );
}
