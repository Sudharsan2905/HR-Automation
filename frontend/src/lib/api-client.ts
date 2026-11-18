import axios from "axios";
import type { GlobalResponse } from "@/types/api";

const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
});

// Paths where 401 should NOT trigger auto-logout (user is trying to log in)
const AUTH_PATHS = ["/auth/login", "/auth/candidate/login"];

apiClient.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem("skillmate-auth");
    if (stored) {
      try {
        const { state } = JSON.parse(stored);
        if (state?.token) {
          config.headers.Authorization = `Bearer ${state.token}`;
        }
      } catch {}
    }
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => {
    if (response.config.responseType === "blob") return response;

    const body = response.data as GlobalResponse;
    if (body && typeof body === "object" && "success" in body) {
      if (body.success) return body.data;
      return Promise.reject(body);
    }
    return response.data;
  },
  (error) => {
    const requestUrl = error.config?.url || "";
    const isAuthRequest = AUTH_PATHS.some((p) => requestUrl.includes(p));

    // Only auto-logout on 401 for authenticated API calls, not login attempts
    if (error.response?.status === 401 && !isAuthRequest && typeof window !== "undefined") {
      localStorage.removeItem("skillmate-auth");
      document.cookie = "skillmate-role=; path=/; max-age=0";
      window.location.href = "/login";
      return Promise.reject(error);
    }

    const body = error.response?.data;
    if (body && typeof body === "object" && "message" in body) {
      return Promise.reject(body);
    }
    return Promise.reject({
      success: false,
      message: error.message || "Network error",
      data: null,
      error: error.message,
    });
  }
);

export default apiClient;
