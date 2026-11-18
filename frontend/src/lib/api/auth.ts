import apiClient from "@/lib/api-client";
import type { LoginRequest, CandidateLoginRequest, TokenResponse } from "@/types/auth";

export const login = (data: LoginRequest) =>
  apiClient.post<unknown, TokenResponse>("/auth/login", data);

export const candidateLogin = (data: CandidateLoginRequest) =>
  apiClient.post<unknown, TokenResponse>("/auth/candidate/login", data);
