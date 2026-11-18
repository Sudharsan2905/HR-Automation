export type Role = "super_admin" | "candidate";

export interface LoginRequest {
  email: string;
  password: string;
}

export interface CandidateLoginRequest {
  email: string;
  access_key: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  role: Role;
}

export interface JwtPayload {
  sub: string;
  role: Role;
  /** Candidate tokens: "l1" (AI exam) or "l2" (voice interview). */
  scope?: string | string[];
  email: string;
  full_name?: string;
  exp: number;
  jti: string;
}
