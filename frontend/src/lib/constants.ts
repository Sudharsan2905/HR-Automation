export const ROUTES = {
  LOGIN: "/login",
  DASHBOARD: "/dashboard",
  HIRING: "/hiring",
  EXAM: "/exam",
} as const;

export const STATUS_COLORS: Record<string, string> = {
  draft: "bg-amber-100 text-amber-800",
  ready: "bg-emerald-100 text-emerald-800",
  used: "bg-gray-100 text-gray-800",
  finalized: "bg-purple-100 text-purple-800",
  completed: "bg-green-100 text-green-800",
  partially_completed: "bg-amber-100 text-amber-800",
  active: "bg-green-100 text-green-800",
  generating: "bg-blue-100 text-blue-800",
  failed: "bg-red-100 text-red-800",
  assigned: "bg-purple-100 text-purple-800",
  in_progress: "bg-sky-100 text-sky-800",
  report_generating: "bg-blue-100 text-blue-800",
  report_ready: "bg-green-100 text-green-800",
  report_failed: "bg-red-100 text-red-800",
};

export const ROLE_HOME: Record<string, string> = {
  super_admin: ROUTES.DASHBOARD,
  candidate: ROUTES.EXAM,
};
