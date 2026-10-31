"use client";

export class ApiError extends Error {
  status: number;
  data: any;
  constructor(status: number, message: string, data: any) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function csrf() {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|; )astitva_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.data?.detail;
    if (typeof d === "string") return d;
    if (d?.message) return d.problems ? `${d.message} ${d.problems.join(" ")}` : d.message;
    if (Array.isArray(d)) return d.map((x: any) => x.msg).join("; ");
    return e.message;
  }
  return e instanceof Error ? e.message : "Something went wrong";
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => setTimeout(() => (refreshing = null), 0));
  }
  return refreshing;
}

export async function api<T = any>(path: string, opts: RequestInit & { json?: any; retry?: boolean; headers?: Record<string, string> } = {}): Promise<T> {
  const { json, retry = true, headers = {}, ...rest } = opts;
  const method = (rest.method || (json !== undefined ? "POST" : "GET")).toUpperCase();
  const h: Record<string, string> = { ...headers };
  if (json !== undefined) h["Content-Type"] = "application/json";
  if (method !== "GET") h["X-CSRF-Token"] = csrf();
  const res = await fetch(path, {
    ...rest, method, headers: h, credentials: "same-origin",
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 401 && retry && !path.startsWith("/api/auth/")) {
    if (await tryRefresh()) return api<T>(path, { ...opts, retry: false });
    if (typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    }
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, typeof data === "string" ? data : data?.detail?.message || data?.detail || res.statusText, data);
  return data as T;
}

export const fetcher = (path: string) => api(path);
