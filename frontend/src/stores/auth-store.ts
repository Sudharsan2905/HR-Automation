import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Role } from "@/types/auth";

interface AuthState {
  token: string | null;
  role: Role | null;
  email: string | null;
  fullName: string | null;
  setAuth: (token: string, role: Role, email: string, fullName?: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      role: null,
      email: null,
      fullName: null,
      setAuth: (token, role, email, fullName) => {
        document.cookie = `skillmate-role=${role}; path=/; max-age=${60 * 60 * 24}`;
        set({ token, role, email, fullName: fullName || null });
      },
      logout: () => {
        document.cookie = "skillmate-role=; path=/; max-age=0";
        set({ token: null, role: null, email: null, fullName: null });
      },
    }),
    { name: "skillmate-auth" }
  )
);
