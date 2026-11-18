import apiClient from "@/lib/api-client";
import type {
  ProfileStatus,
  RunFailReason,
  RunStartResult,
  SaveContactResult,
  SetStatusResult,
  SourcedProfile,
  SourcedProfileDetail,
  SourcingJdDetail,
  SourcingJdListResponse,
  SourcingJdSummary,
  SourcingRequirements,
  SourcingRun,
  SourcingSearchPlan,
} from "@/types/sourcing";

export const createSourcingJd = (input: { title?: string; jd_text?: string; jd_file?: File | null }) => {
  const fd = new FormData();
  if (input.title?.trim()) fd.append("title", input.title.trim());
  if (input.jd_text?.trim()) fd.append("jd_text", input.jd_text.trim());
  if (input.jd_file) fd.append("jd_file", input.jd_file);
  return apiClient.post<unknown, SourcingJdSummary>("/sourcing/jds", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const listSourcingJds = (params?: { skip?: number; limit?: number }) =>
  apiClient.get<unknown, SourcingJdListResponse>("/sourcing/jds", { params });

export const getSourcingJd = (id: string) =>
  apiClient.get<unknown, SourcingJdDetail>(`/sourcing/jds/${id}`);

export const reanalyzeSourcingJd = (id: string) =>
  apiClient.post<unknown, { message: string }>(`/sourcing/jds/${id}/reanalyze`, {});

export const updateRequirements = (id: string, req: SourcingRequirements) =>
  apiClient.put<unknown, SourcingJdDetail>(`/sourcing/jds/${id}/requirements`, req);

export const updateSearchPlan = (id: string, plan: SourcingSearchPlan) =>
  apiClient.put<unknown, SourcingJdDetail>(`/sourcing/jds/${id}/search-plan`, plan);

export const deleteSourcingJd = (id: string) =>
  apiClient.delete<unknown, { message: string }>(`/sourcing/jds/${id}`);

export const startRun = (id: string) =>
  apiClient.post<unknown, RunStartResult>(`/sourcing/jds/${id}/runs`, {});

export const getRun = (runId: string) =>
  apiClient.get<unknown, SourcingRun>(`/sourcing/runs/${runId}`);

export const failRun = (runId: string, reason: RunFailReason, detail?: string) =>
  apiClient.post<unknown, SourcingRun>(`/sourcing/runs/${runId}/fail`, { reason, detail: detail ?? "" });

export const listProfiles = (id: string, status?: ProfileStatus) =>
  apiClient.get<unknown, SourcedProfile[]>(`/sourcing/jds/${id}/profiles`, { params: status ? { status } : undefined });

export const setProfileStatus = (profileId: string, status: "selected" | "rejected" | "on_hold", note?: string) =>
  apiClient.post<unknown, SetStatusResult>(`/sourcing/profiles/${profileId}/status`, { status, note: note ?? "" });

export const getProfile = (profileId: string) =>
  apiClient.get<unknown, SourcedProfileDetail>(`/sourcing/profiles/${profileId}`);

export const saveContact = (profileId: string, contact: { email?: string; phone?: string }) =>
  apiClient.post<unknown, SaveContactResult>(`/sourcing/profiles/${profileId}/contact`, contact);
