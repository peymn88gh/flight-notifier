import type { AlertRecord, Location } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

function authHeaders(): HeadersInit {
  return {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": window.Telegram?.WebApp.initData || ""
  };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "خطای ارتباط با سرور" }));
    throw new Error(body.detail || "خطای ارتباط با سرور");
  }
  return response.json() as Promise<T>;
}

export const api = {
  session: () =>
    request<{ user_id: string; phone_masked: string; first_name?: string }>(
      "/api/session",
      { method: "POST" }
    ),
  locations: () => request<Location[]>("/api/locations"),
  alerts: () => request<AlertRecord[]>("/api/alerts"),
  createAlert: (criteria: unknown) =>
    request<AlertRecord>("/api/alerts", {
      method: "POST",
      body: JSON.stringify({ criteria })
    }),
  cancelAlert: (id: string) =>
    request<AlertRecord>(`/api/alerts/${id}/cancel`, { method: "POST" })
};

