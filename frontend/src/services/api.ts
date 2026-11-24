// Thin typed client for the HAL backend. Errors use the backend's { error: { code, message, details } } envelope.
const TOKEN_KEY = "hal.reviewerToken";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

export function getReviewerToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setReviewerToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the token simply is not remembered */
  }
}

async function request<T>(path: string, init: RequestInit = {}, reviewer = false): Promise<T> {
  const headers = new Headers(init.headers);
  if (reviewer) {
    const token = getReviewerToken();
    if (!token) throw new ApiError(401, "missing_token", "Enter your reviewer token (top right) first");
    headers.set("X-Reviewer-Token", token);
  }
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api${path}`, { ...init, headers, cache: "no-store" });
  if (!res.ok) {
    let code = "http_error";
    let message = `${res.status} ${res.statusText}`;
    let details: unknown;
    try {
      const body = await res.json();
      if (body?.error) ({ code, message, details } = body.error);
      else if (body?.detail) message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, message, details);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, reviewer = false) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }, reviewer),
  postForm: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
};

export const downloadUrl = (path: string) => `/api${path}`;
