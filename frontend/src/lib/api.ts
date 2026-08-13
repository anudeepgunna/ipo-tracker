import type {
  AlertRule,
  AppNotification,
  Ipo,
  IpoDetail,
  NotificationChannel,
  ServerConfig,
  User,
} from "./types";

// Same-origin in dev (Vite proxies /api) and in production when the SPA is served
// behind the same host; VITE_API_BASE overrides for a split deployment.
const BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    // Always send the session cookie.
    credentials: "include",
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });

  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) message = typeof body.detail === "string" ? body.detail : message;
    } catch {
      /* response wasn't JSON; keep the status text */
    }
    throw new Error(message);
  }

  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  config: () => request<ServerConfig>("/api/config"),

  listIpos: (params: { status?: string; board?: string; watchlist?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.board) q.set("board", params.board);
    if (params.watchlist) q.set("watchlist", "true");
    const qs = q.toString();
    return request<Ipo[]>(`/api/ipos${qs ? `?${qs}` : ""}`);
  },

  getIpo: (symbol: string) => request<IpoDetail>(`/api/ipos/${symbol}`),

  // --- auth ---
  me: () => request<User>("/api/auth/me"),
  requestLink: (email: string) =>
    request<{ sent: boolean; dev_link?: string; error?: string }>("/api/auth/request-link", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  verify: (token: string) =>
    request<User>(`/api/auth/verify?token=${encodeURIComponent(token)}`, { method: "POST" }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  // --- watchlist ---
  watchlist: () => request<number[]>("/api/me/watchlist"),
  addWatch: (id: number) => request(`/api/me/watchlist/${id}`, { method: "PUT" }),
  removeWatch: (id: number) => request(`/api/me/watchlist/${id}`, { method: "DELETE" }),

  // --- channels ---
  channels: () => request<NotificationChannel[]>("/api/me/channels"),
  addChannel: (channel: string, destination = "") =>
    request<NotificationChannel>("/api/me/channels", {
      method: "POST",
      body: JSON.stringify({ channel, destination }),
    }),
  deleteChannel: (id: number) => request(`/api/me/channels/${id}`, { method: "DELETE" }),
  testChannel: (id: number) => request(`/api/me/channels/${id}/test`, { method: "POST" }),
  telegramLinkCode: () =>
    request<{ code: string; deep_link: string | null; command: string }>(
      "/api/telegram/link-code",
      { method: "POST" },
    ),
  telegramPoll: () => request<{ linked: number }>("/api/telegram/poll-updates", { method: "POST" }),

  // Public: set reminders without an account (email confirmed afterwards).
  subscribe: (body: { email: string; ipo_id: number; cadences: string[] }) =>
    request<{
      ok: boolean;
      created?: number;
      sent?: boolean;
      error?: string;
      message?: string;
      dev_link?: string;
    }>("/api/alerts/subscribe", { method: "POST", body: JSON.stringify(body) }),

  // --- rules ---
  rules: () => request<AlertRule[]>("/api/me/rules"),
  createRule: (rule: Record<string, unknown>) =>
    request<AlertRule>("/api/me/rules", { method: "POST", body: JSON.stringify(rule) }),
  deleteRule: (id: number) => request(`/api/me/rules/${id}`, { method: "DELETE" }),

  // --- inbox ---
  notifications: () => request<AppNotification[]>("/api/me/notifications"),
  markRead: (id: number) => request(`/api/me/notifications/${id}/read`, { method: "POST" }),
};

export function formatMoney(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `₹${value.toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function formatTimes(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(2)}x`;
}
