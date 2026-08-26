import type { AlertRecord, HotelAlertRecord, HotelDestination, Location } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FIELD_LABELS: Record<string, string> = {
  "criteria.outbound_dates.start": "تاریخ رفت",
  "criteria.outbound_dates.end": "پایان بازه رفت",
  "criteria.return_dates.start": "تاریخ برگشت",
  "criteria.return_dates.end": "پایان بازه برگشت",
  "criteria.outbound_times.start": "شروع ساعت رفت",
  "criteria.outbound_times.end": "پایان ساعت رفت",
  "criteria.return_times.start": "شروع ساعت برگشت",
  "criteria.return_times.end": "پایان ساعت برگشت",
  "criteria.checkin_dates.start": "تاریخ ورود",
  "criteria.checkin_dates.end": "پایان بازه ورود",
  "criteria.destination": "مقصد",
  "criteria.nights": "تعداد شب",
  "criteria.rooms": "تعداد اتاق"
};

type ValidationError = {
  loc?: Array<string | number>;
  msg?: string;
};

function formatApiError(body: unknown): string {
  const fallback = "خطای ارتباط با سرور";
  if (!body || typeof body !== "object" || !("detail" in body)) return fallback;

  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (!Array.isArray(detail)) return fallback;

  const messages = detail.map((item: unknown) => {
    if (!item || typeof item !== "object") return String(item);
    const error = item as ValidationError;
    const path = Array.isArray(error.loc)
      ? error.loc.filter((part) => part !== "body").join(".")
      : "";
    const label = FIELD_LABELS[path] || path;
    const message = typeof error.msg === "string" ? error.msg : "مقدار نامعتبر است";
    return label ? label + ": " + message : message;
  });

  return messages.filter(Boolean).join(" • ") || fallback;
}

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
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(formatApiError(body), response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  session: () =>
    request<{
      user_id: string;
      phone_masked: string;
      first_name?: string;
      max_active_alerts: number;
    }>(
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
    request<AlertRecord>(`/api/alerts/${id}/cancel`, { method: "POST" }),
  hotelDestinations: () => request<HotelDestination[]>("/api/hotel-destinations"),
  hotelAlerts: () => request<HotelAlertRecord[]>("/api/hotel-alerts"),
  createHotelAlert: (criteria: unknown) =>
    request<HotelAlertRecord>("/api/hotel-alerts", {
      method: "POST",
      body: JSON.stringify({ criteria })
    }),
  cancelHotelAlert: (id: string) =>
    request<HotelAlertRecord>(`/api/hotel-alerts/${id}/cancel`, { method: "POST" })
};
