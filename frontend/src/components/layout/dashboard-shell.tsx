"use client";

import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";
import { useUiStore } from "@/stores/ui-store";
import { cn } from "@/lib/utils";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);

  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className={cn("transition-all duration-300 flex flex-col min-h-screen", sidebarOpen ? "ml-64" : "ml-16")}>
        <Topbar />
        <main className="p-6 flex-1 flex flex-col">{children}</main>
      </div>
    </div>
  );
}
