export type ProfileStatus = "pool" | "shortlisted" | "selected" | "rejected" | "on_hold" | "below_threshold";
export type RunStatus = "pending" | "scraping" | "screening" | "done" | "failed" | "cancelled";
export type AnalysisStatus = "generating" | "done" | "failed";
/** Where a scrape run reads from: lower case on runs, capitalised ("Naukri" / "LinkedIn") on profiles. */
export type SourceKey = "naukri" | "linkedin";

export interface SkillSpec {
  name: string;
  variants: string[];
}

export interface SourcingRequirements {
  role_title: string;
  experience_min_years: number | null;
  experience_max_years: number | null;
  ctc_max_lacs: number | null;
  locations: string[];
  mandatory_skills: SkillSpec[];
  preferred_skills: SkillSpec[];
  target_companies: string[];
  avoid_companies: string[];
}

export interface SourcingSearchPlan {
  primary_keywords: string;
  narrowed_keywords: string;
  use_narrowed: boolean;
  experience_min: number | null;
  experience_max: number | null;
  locations: string[];
  ctc_max_lacs: number | null;
}

export interface SourcingRun {
  id: string;
  run_no: number;
  mode: "pool" | "scrape";
  source: SourceKey;
  status: RunStatus;
  error: string | null;
  /** What the extension saw when the run failed (page text, cards, search step). For support; not shown. */
  debug?: string;
  pages_from: number | null;
  pages_to: number | null;
  pages_crawled: number | null;
  phase: "hunting" | "prefetch";
  next_action: "next_page" | null;
  source_url: string;
  profiles_received: number;
  profiles_new: number;
  profiles_shortlisted: number;
  created_at: string;
  finished_at: string | null;
}

export type StatusCounts = Record<ProfileStatus, number>;

export interface SourcingJdSummary {
  id: string;
  title: string;
  role_title: string;
  analysis_status: AnalysisStatus;
  analysis_error: string | null;
  counts: StatusCounts;
  created_at: string;
}

export interface SourcingJdDetail extends SourcingJdSummary {
  jd_text: string;
  requirements: SourcingRequirements;
  search_plan: SourcingSearchPlan;
  next_page: number;
  pool_exhausted: boolean;
  linkedin_next_page: number;
  linkedin_exhausted: boolean;
  linkedin_search_level: number;
  pool_count: number;
  active_run: SourcingRun | null;
  runs: SourcingRun[];
}

export interface SourcingJdListResponse {
  total: number;
  items: SourcingJdSummary[];
}

export interface StatusEvent {
  status: string;
  by: string;
  at: string;
  note: string;
}

export interface SourcedProfile {
  id: string;
  run_id: string;
  shortlisted_in_run_id: string | null;
  source: "Naukri" | "LinkedIn" | string;
  name: string;
  headline: string;
  location: string;
  current_company: string;
  current_title: string;
  experience_years: number | null;
  current_ctc_lacs: number | null;
  skills: string[];
  source_link: string;
  email: string;
  phone: string;
  score: number | null;
  score_breakdown: Record<string, number | string | null>;
  match_reasons: string[];
  related_notes: string[];
  status: ProfileStatus;
  status_history: StatusEvent[];
  candidate_user_id: string | null;
  existing_candidate_owner: string | null;
}

export interface SkillFinding {
  skill: string;
  match: "present" | "related" | "absent";
  related_skill: string;
  strength: "none" | "basic" | "strong" | "excellent";
  evidence: string;
}

export interface PreferredFinding {
  skill: string;
  present: boolean;
  evidence: string;
}

/** GET /sourcing/profiles/{id} — everything SkillMate holds about one candidate. */
export interface SourcedProfileDetail extends Omit<SourcedProfile, "status_history"> {
  jd_title: string;
  total_experience: string;
  current_ctc: string;
  experiences: Record<string, unknown>[];
  education: Record<string, unknown>[];
  mandatory_findings: SkillFinding[];
  preferred_findings: PreferredFinding[];
  screening_flags: Record<string, boolean>;
  contact_revealed_at: string | null;
  created_at: string;
  status_history: (StatusEvent & { by_name: string })[];
}

export interface RunStartResult {
  run: SourcingRun;
  mode: "pool" | "scrape";
  source?: SourceKey;
  search_plan?: SourcingSearchPlan;
  page_from?: number;
  page_to?: number;
  /** LinkedIn: the step of the extension's search ladder earlier runs settled on. */
  search_level?: number;
}

export interface SetStatusResult {
  needs_contact: boolean;
  candidate_error: string | null;
  profile: SourcedProfile;
}

export interface SaveContactResult {
  profile: SourcedProfile;
  candidate_error: string | null;
}

export type RunFailReason = "not_logged_in" | "captcha" | "restricted" | "cancelled" | "error";
