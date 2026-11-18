export interface GlobalResponse<T = unknown> {
  success: boolean;
  message: string;
  data: T | null;
  error: string | ValidationError[] | null;
}

export interface ValidationError {
  field: string;
  message: string;
}

export interface ApiError {
  success: false;
  message: string;
  data: null;
  error: string | ValidationError[];
}
