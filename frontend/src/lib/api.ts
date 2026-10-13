/**
 * API client for the CDA backend.
 *
 * Usage:
 *   import { api } from "@/lib/api";
 *   const classes = await api.get<PaginatedResponse<ClassItem>>("/classes/");
 *   const result = await api.post("/feedback/", body);
 *
 * The client auto-attaches the auth token from localStorage.
 * All paths are relative to NEXT_PUBLIC_API_URL (e.g., "/classes/" not the full URL).
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

class ApiClient {
  private getToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("cda_token");
  }

  private getHeaders(): HeadersInit {
    const headers: HeadersInit = {
      "Content-Type": "application/json",
    };
    const token = this.getToken();
    if (token) {
      headers["Authorization"] = `Token ${token}`;
    }
    return headers;
  }

  async get<T>(path: string): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body);
    }
    return res.json();
  }

  async post<T>(path: string, data?: unknown): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: this.getHeaders(),
      body: data ? JSON.stringify(data) : undefined,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body);
    }
    return res.json();
  }

  async patch<T>(path: string, data: unknown): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: "PATCH",
      headers: this.getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body);
    }
    return res.json();
  }

  async delete(path: string): Promise<void> {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: "DELETE",
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body);
    }
  }
}

export class ApiError extends Error {
  status: number;
  body: Record<string, unknown>;

  constructor(status: number, body: Record<string, unknown>) {
    super(`API Error ${status}`);
    this.status = status;
    this.body = body;
  }
}

/**
 * Flatten a DRF error body into readable messages.
 * Handles {"detail": "..."}, {"non_field_errors": [...]} and
 * {"<field>": ["..."]} shapes.
 */
export function getErrorMessages(err: unknown, fallback = "Something went wrong."): string[] {
  if (!(err instanceof ApiError)) return [fallback];
  const messages: string[] = [];
  for (const [field, value] of Object.entries(err.body)) {
    const list = Array.isArray(value) ? value : [value];
    for (const msg of list) {
      if (typeof msg !== "string") continue;
      const prefix = field === "detail" || field === "non_field_errors" ? "" : `${field.replace(/_/g, " ")}: `;
      messages.push(prefix + msg);
    }
  }
  return messages.length ? messages : [fallback];
}

export const api = new ApiClient();
