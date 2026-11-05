// API client. The access token is held in memory only (not localStorage) to
// limit exposure to XSS; a page reload requires signing in again.
import type { User } from "../types/api";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

let token: string | null = null;
let onUnauthorized: () => void = () => {};
export const session = {
  set(t: string | null) { token = t; },
  onUnauthorized(cb: () => void) { onUnauthorized = cb; },
};

const BASE = (globalThis as { AUTOLINK_API_BASE?: string }).AUTOLINK_API_BASE ?? "";

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res: Response;
  try {
    res = await fetch(BASE + path, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "network_error", "The backend is unreachable. Check that it is running.");
  }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    if (res.status === 401 && path !== "/api/v1/auth/login") onUnauthorized();
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? "http_error", err.message ?? `Request failed (${res.status})`, err.details);
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b),
  login: (username: string, password: string) =>
    request<{ access_token: string; user: User; expires_in: number }>("POST", "/api/v1/auth/login", { username, password }),
};

export const can = {
  write: (u: User | null) => u?.role === "admin" || u?.role === "engineer",
  admin: (u: User | null) => u?.role === "admin",
};
