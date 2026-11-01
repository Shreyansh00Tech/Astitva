"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { CalendarPlus, Check, ListTodo, Pencil, Plus, Trash2 } from "lucide-react";
import { errorMessage, fetcher } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  CAT, PLANNER_CATS, addDays, dateInput, deletePlanner, fmtDay, fmtTime, plannerKey, sameDay, savePlanner, startOfDay, timeInput,
} from "@/lib/planner";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PlannerDialog, type PlannerDraft } from "@/components/planner-dialog";

type Tab = "today" | "upcoming" | "done";

function nextSlot() {
  const n = new Date();
  n.setMinutes(n.getMinutes() < 30 ? 30 : 60, 0, 0);
  return n;
}

function dayLabel(d: Date) {
  const t = startOfDay(new Date());
  if (sameDay(d, t)) return "Today";
  if (sameDay(d, addDays(t, 1))) return "Tomorrow";
  if (sameDay(d, addDays(t, -1))) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

/** Quick add + list of the employee's own tasks. Each task sits on a date, so it shows up in the calendar too. */
export function MyTasksCard({ className }: { className?: string }) {
  const today = useMemo(() => startOfDay(new Date()), []);
  const key = plannerKey(addDays(today, -14), addDays(today, 45));
  const { data } = useSWR(key, fetcher);
  const [tab, setTab] = useState<Tab>("today");
  const [draft, setDraft] = useState<PlannerDraft | null>(null);
  const slot = useMemo(nextSlot, []);
  const [q, setQ] = useState({ title: "", date: dateInput(slot), time: timeInput(slot), category: "WORK" });
  const [busy, setBusy] = useState(false);

  const items: any[] = data?.items ?? [];
  const lists = useMemo(() => {
    const byStart = [...items].sort((a, b) => +new Date(a.start_at) - +new Date(b.start_at));
    return {
      today: byStart.filter((i) => sameDay(new Date(i.start_at), today)),
      upcoming: byStart.filter((i) => !i.done && new Date(i.start_at) >= addDays(today, 1)),
      done: byStart.filter((i) => i.done).reverse(),
    };
  }, [items, today]);
  const todayDone = lists.today.filter((i) => i.done).length;
  const overdue = items.filter((i) => !i.done && new Date(i.end_at) < new Date() && !sameDay(new Date(i.start_at), today)).length;

  async function quickAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!q.title.trim()) return;
    const start = new Date(`${q.date}T${q.time || "10:00"}`);
    setBusy(true);
    try {
      await savePlanner(null, { title: q.title, category: q.category, start_at: start.toISOString(), end_at: new Date(start.getTime() + 3600000).toISOString() });
      toast.success(`Added to ${dayLabel(start).toLowerCase() === "today" ? "today" : dayLabel(start)} at ${fmtTime(start)}`);
      setQ((p) => ({ ...p, title: "" }));
    } catch (e2) { toast.error(errorMessage(e2)); } finally { setBusy(false); }
  }

  async function toggle(i: any) {
    try { await savePlanner(i.id, { done: !i.done }); } catch (e) { toast.error(errorMessage(e)); }
  }
  async function remove(i: any) {
    try { await deletePlanner(i.id); toast.success("Task removed"); } catch (e) { toast.error(errorMessage(e)); }
  }

  const list = lists[tab];
  let lastDay = "";

  return (
    <Card className={cn("flex h-full flex-col lg:h-[460px]", className)}>
      <CardHeader title={<span className="inline-flex items-center gap-1.5"><ListTodo className="h-4 w-4 text-violet" />My tasks</span>}
        description="Add a task, pick the day and time, and it lands on your calendar"
        action={overdue ? <Badge tone="warning">{overdue} overdue</Badge> : <Badge tone="violet">{todayDone}/{lists.today.length} today</Badge>} />
      <CardBody className="flex min-h-0 flex-1 flex-col gap-3">
        {/* quick add */}
        <form onSubmit={quickAdd} className="rounded-lg border bg-muted/30 p-2 focus-within:border-violet/50 focus-within:ring-2 focus-within:ring-violet/15">
          <div className="flex items-center gap-2">
            <Plus className="ml-1 h-4 w-4 shrink-0 text-muted-foreground" />
            <input value={q.title} onChange={(e) => setQ({ ...q, title: e.target.value })} maxLength={160} placeholder="Add a task, e.g. Prepare demo notes"
              className="h-8 min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground/70" aria-label="Task title" />
            <button type="submit" disabled={!q.title.trim() || busy}
              className="inline-flex h-7 items-center gap-1 rounded-md bg-violet px-2.5 text-xs font-medium text-white shadow-sm transition hover:bg-violet/90 disabled:opacity-40">
              <CalendarPlus className="h-3.5 w-3.5" />Add
            </button>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-7">
            <input type="date" value={q.date} onChange={(e) => setQ({ ...q, date: e.target.value })} aria-label="Date"
              className="h-7 rounded-md border bg-card px-1.5 text-[11.5px] tabular outline-none focus:border-violet" />
            <input type="time" value={q.time} onChange={(e) => setQ({ ...q, time: e.target.value })} aria-label="Time"
              className="h-7 rounded-md border bg-card px-1.5 text-[11.5px] tabular outline-none focus:border-violet" />
            <div className="flex items-center gap-0.5 rounded-md border bg-card p-0.5">
              {PLANNER_CATS.map((c) => (
                <button type="button" key={c} title={CAT[c].label} onClick={() => setQ({ ...q, category: c })}
                  className={cn("flex h-6 items-center gap-1 rounded px-1.5 text-[10.5px] transition-colors", q.category === c ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/60")}>
                  <i className={cn("h-2 w-2 rounded-full", CAT[c].dot)} />{q.category === c && CAT[c].label}
                </button>
              ))}
            </div>
            <button type="button" onClick={() => setDraft({ start: new Date(`${q.date}T${q.time || "10:00"}`) })} className="ml-auto text-[11px] text-violet hover:underline">More options</button>
          </div>
        </form>

        {/* tabs */}
        <div className="flex gap-1 border-b">
          {([["today", "Today", lists.today.length], ["upcoming", "Upcoming", lists.upcoming.length], ["done", "Done", lists.done.length]] as const).map(([k, label, n]) => (
            <button key={k} onClick={() => setTab(k)} className={cn("-mb-px border-b-2 px-2 pb-1.5 text-xs font-medium transition-colors", tab === k ? "border-violet text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {label} <span className="tabular text-muted-foreground">{n}</span>
            </button>
          ))}
        </div>

        {/* list */}
        <div className="min-h-0 flex-1 overflow-y-auto scroll-thin pr-1">
          {!data ? <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-10 animate-pulse rounded-md bg-muted" />)}</div>
            : !list.length ? (
              <div className="flex h-full flex-col items-center justify-center gap-1 py-6 text-center">
                <ListTodo className="h-6 w-6 text-muted-foreground/50" />
                <p className="text-xs font-medium">{tab === "done" ? "Nothing finished yet" : tab === "today" ? "Nothing planned for today" : "No upcoming tasks"}</p>
                <p className="text-2xs text-muted-foreground">Type a task above and press Enter.</p>
              </div>
            ) : list.map((i, idx) => {
              const s = new Date(i.start_at), e = new Date(i.end_at);
              const lbl = dayLabel(s);
              const header = tab !== "today" && lbl !== lastDay ? (lastDay = lbl) : null;
              const late = !i.done && e < new Date();
              return (
                <div key={i.id}>
                  {header && <div className="mb-1 mt-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground first:mt-0">{header}</div>}
                  <div className="ov-slide group flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-accent/60" style={{ animationDelay: `${Math.min(idx, 8) * 40}ms` }}>
                    <button onClick={() => toggle(i)} aria-label={i.done ? "Mark not done" : "Mark done"}
                      className={cn("flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                        i.done ? cn(CAT[i.category as keyof typeof CAT].dot, "border-transparent") : "border-muted-foreground/40 hover:border-violet")}>
                      {i.done && <Check className="h-3 w-3 text-white" strokeWidth={3.5} />}
                    </button>
                    <button onClick={() => setDraft({ item: i })} className="min-w-0 flex-1 text-left">
                      <div className={cn("truncate text-[13px]", i.done && "text-muted-foreground line-through")}>{i.title}</div>
                      <div className="flex items-center gap-1.5 text-2xs text-muted-foreground">
                        <i className={cn("h-1.5 w-1.5 rounded-full", CAT[i.category as keyof typeof CAT].dot)} />
                        <span>{CAT[i.category as keyof typeof CAT].label}</span>·
                        <span className={cn("tabular", late && "font-medium text-warning")}>{i.all_day ? "All day" : `${fmtTime(s)} – ${fmtTime(e)}`}{tab === "done" ? ` · ${fmtDay(s)}` : ""}{late ? " · overdue" : ""}</span>
                        {i.priority === "HIGH" && <span className="font-medium text-critical">· High</span>}
                      </div>
                    </button>
                    <div className="flex opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <button onClick={() => setDraft({ item: i })} aria-label="Edit" className="rounded p-1 text-muted-foreground hover:bg-card hover:text-foreground"><Pencil className="h-3.5 w-3.5" /></button>
                      <button onClick={() => remove(i)} aria-label="Delete" className="rounded p-1 text-muted-foreground hover:bg-card hover:text-critical"><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  </div>
                </div>
              );
            })}
        </div>
        {data?.project_tasks?.some((t: any) => t.status !== "DONE") && (
          <div className="border-t pt-2 text-2xs text-muted-foreground">
            <span className="inline-flex items-center gap-1"><i className="h-1.5 w-1.5 rounded-full bg-teal-500" />{data.project_tasks.filter((t: any) => t.status !== "DONE").length} project task(s) due soon are also on your calendar.</span>
          </div>
        )}
      </CardBody>
      <PlannerDialog draft={draft} onClose={() => setDraft(null)} />
    </Card>
  );
}
