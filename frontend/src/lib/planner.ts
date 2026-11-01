"use client";

import { mutate } from "swr";
import { api } from "@/lib/api";

/** Calendar and planner helpers shared by the employee calendar and the My tasks panel. Dates are local time. */

export type CatKey = "WORK" | "MEETING" | "FOCUS" | "DEADLINE" | "PERSONAL" | "PROJECT_TASK" | "ACCESS" | "MILESTONE";
export const PLANNER_CATS = ["WORK", "MEETING", "FOCUS", "DEADLINE", "PERSONAL"] as const;

// Full class names so Tailwind keeps them. chip = soft fill + strong left edge, like a paper calendar tab.
export const CAT: Record<CatKey, { label: string; dot: string; chip: string; text: string }> = {
  WORK: { label: "Work", dot: "bg-sky-500", chip: "border-sky-500 bg-sky-50 dark:bg-sky-500/15", text: "text-sky-950 dark:text-sky-100" },
  MEETING: { label: "Meetings", dot: "bg-violet-500", chip: "border-violet-500 bg-violet-50 dark:bg-violet-500/15", text: "text-violet-950 dark:text-violet-100" },
  FOCUS: { label: "Focus time", dot: "bg-emerald-500", chip: "border-emerald-500 bg-emerald-50 dark:bg-emerald-500/15", text: "text-emerald-950 dark:text-emerald-100" },
  DEADLINE: { label: "Deadlines", dot: "bg-rose-500", chip: "border-rose-500 bg-rose-50 dark:bg-rose-500/15", text: "text-rose-950 dark:text-rose-100" },
  PERSONAL: { label: "Personal", dot: "bg-amber-500", chip: "border-amber-500 bg-amber-50 dark:bg-amber-500/15", text: "text-amber-950 dark:text-amber-100" },
  PROJECT_TASK: { label: "Project tasks", dot: "bg-teal-500", chip: "border-teal-500 bg-teal-50 dark:bg-teal-500/15", text: "text-teal-950 dark:text-teal-100" },
  ACCESS: { label: "Access grants", dot: "bg-indigo-500", chip: "border-indigo-500 bg-indigo-50 dark:bg-indigo-500/15", text: "text-indigo-950 dark:text-indigo-100" },
  MILESTONE: { label: "Project dates", dot: "bg-orange-500", chip: "border-orange-500 bg-orange-50 dark:bg-orange-500/15", text: "text-orange-950 dark:text-orange-100" },
};

export const DAY_MS = 86400000;
export const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, d.getHours(), d.getMinutes());
export const startOfWeek = (d: Date) => { const s = startOfDay(d); return addDays(s, -((s.getDay() + 6) % 7)); }; // Monday
export const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
export const dayDiff = (a: Date, b: Date) => Math.round((startOfDay(a).getTime() - startOfDay(b).getTime()) / DAY_MS);
export const pad = (n: number) => String(n).padStart(2, "0");
export const dateInput = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const timeInput = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const fmtTime = (d: Date) => d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
export const fmtDay = (d: Date, o: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }) => d.toLocaleDateString(undefined, o);

export function plannerKey(start: Date, end: Date) {
  return `/api/me/planner?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`;
}

/** Refresh every planner range on screen (calendar + task list) after a change. */
export const refreshPlanner = () => mutate((k) => typeof k === "string" && k.startsWith("/api/me/planner"));

export async function savePlanner(id: string | null, body: Record<string, unknown>) {
  const r = id ? await api(`/api/me/planner/${id}`, { method: "PATCH", json: body }) : await api("/api/me/planner", { json: body });
  await refreshPlanner();
  return r;
}

export async function deletePlanner(id: string) {
  await api(`/api/me/planner/${id}`, { method: "DELETE" });
  await refreshPlanner();
}
