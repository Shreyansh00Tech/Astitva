"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { CalendarDays, Check, ChevronLeft, ChevronRight, Flag, KeyRound, ListTodo, Plus } from "lucide-react";
import { fetcher } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  CAT, type CatKey, addDays, dayDiff, fmtDay, fmtTime, plannerKey, sameDay, startOfDay, startOfWeek,
} from "@/lib/planner";
import { Card } from "@/components/ui/card";
import { PlannerDialog, type PlannerDraft } from "@/components/planner-dialog";

type View = "day" | "week" | "month";
type Ev = {
  id: string; title: string; sub?: string; start: Date; end: Date; allDay: boolean; cat: CatKey;
  done?: boolean; item?: any; href?: string; tone?: string; icon?: any;
};

const HOUR = 46; // px per hour in the time grid
const FILTERS: CatKey[] = ["WORK", "MEETING", "FOCUS", "DEADLINE", "PERSONAL", "PROJECT_TASK", "MILESTONE", "ACCESS"];
// Month cells show your own items first, then project dates/tasks, then access grants.
const RANK: Record<CatKey, number> = { DEADLINE: 0, MEETING: 1, WORK: 1, FOCUS: 1, PERSONAL: 1, MILESTONE: 2, PROJECT_TASK: 3, ACCESS: 4 };
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function grantTone(g: any) {
  if (g.status === "REVOKED") return "border-rose-400 bg-rose-50/70 text-rose-900/80 dark:bg-rose-500/10 dark:text-rose-200";
  if (g.status === "EXPIRED") return "border-slate-400 bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-300";
  if (g.is_emergency) return "border-orange-600 bg-orange-50 text-orange-950 dark:bg-orange-500/15 dark:text-orange-100";
  return "";
}

/** Everything that belongs on the employee's calendar: own tasks, project tasks, project dates and access grants. */
function buildEvents(planner: any, tl: any): Ev[] {
  const out: Ev[] = [];
  for (const i of planner?.items ?? []) {
    const s = new Date(i.start_at), e = new Date(i.end_at);
    out.push({ id: i.id, title: i.title, sub: i.notes || undefined, start: s, end: e, cat: i.category, done: i.done, item: i,
      allDay: i.all_day || !sameDay(s, new Date(e.getTime() - 1)) });
  }
  for (const t of planner?.project_tasks ?? []) {
    const d = new Date(t.due_at);
    out.push({ id: `t-${t.id}`, title: t.title, sub: `${t.code} · ${t.project} · due ${fmtTime(d)}`, start: d, end: d, allDay: true,
      cat: "PROJECT_TASK", done: t.status === "DONE", icon: ListTodo });
  }
  const p = tl?.project;
  if (p) {
    for (const [label, v, tone] of [
      ["Project start", p.start_date, "border-emerald-500 bg-emerald-50 text-emerald-950 dark:bg-emerald-500/15 dark:text-emerald-100"],
      ["Submission due", p.submission_date, ""],
      ["Project end", p.end_date, "border-rose-500 bg-rose-50 text-rose-950 dark:bg-rose-500/15 dark:text-rose-100"],
    ] as const) {
      if (!v) continue;
      const d = new Date(v);
      out.push({ id: `m-${label}`, title: `${label} · ${p.name}`, sub: p.code, start: d, end: d, allDay: true, cat: "MILESTONE", tone: tone || undefined, icon: Flag });
    }
    for (const g of tl.grants ?? []) {
      const s = new Date(g.granted_at), e = new Date(g.ended_at || g.expires_at);
      const ended = g.status !== "ACTIVE";
      out.push({ id: `g-${g.id}`, title: g.resource.name, start: s, end: e, allDay: true, cat: "ACCESS", tone: grantTone(g) || undefined, icon: KeyRound,
        sub: `${g.permissions.join(", ")} · ${ended ? (g.status === "REVOKED" ? "revoked" : "expired") : "expires"} ${fmtDay(e)} ${fmtTime(e)}${g.capped_to_project_end ? " · capped at project end" : ""}`,
        href: g.status === "ACTIVE" ? `/active-access/${g.resource.id}` : undefined, done: ended });
    }
  }
  return out;
}

/** Side-by-side columns for overlapping timed events in one day. */
function layoutDay(evs: Ev[]) {
  const sorted = [...evs].sort((a, b) => a.start.getTime() - b.start.getTime() || b.end.getTime() - a.end.getTime());
  const out: { ev: Ev; col: number; cols: number }[] = [];
  let cluster: { ev: Ev; col: number }[] = [];
  let clusterEnd = 0;
  const flush = () => { const n = Math.max(1, ...cluster.map((c) => c.col + 1)); cluster.forEach((c) => out.push({ ...c, cols: n })); cluster = []; };
  for (const ev of sorted) {
    const s = ev.start.getTime(), e = Math.max(ev.end.getTime(), s + 20 * 60000);
    if (cluster.length && s >= clusterEnd) flush();
    const used = new Set(cluster.filter((c) => Math.max(c.ev.end.getTime(), c.ev.start.getTime() + 20 * 60000) > s).map((c) => c.col));
    let col = 0; while (used.has(col)) col++;
    cluster.push({ ev, col });
    clusterEnd = Math.max(clusterEnd, e);
  }
  if (cluster.length) flush();
  return out;
}

/** Lanes for all-day / multi-day bars across the visible days. */
function layoutSpans(evs: Ev[], first: Date, n: number) {
  const rows = evs.map((ev) => ({ ev, s: Math.max(0, dayDiff(ev.start, first)), e: Math.min(n - 1, dayDiff(ev.end, first)) }))
    .filter((r) => r.e >= 0 && r.s <= n - 1)
    .sort((a, b) => a.s - b.s || (b.e - b.s) - (a.e - a.s));
  const lanes: number[][] = [];
  return rows.map((r) => {
    let lane = lanes.findIndex((l) => l.every((x) => x < r.s));
    if (lane === -1) { lanes.push([]); lane = lanes.length - 1; }
    lanes[lane].push(r.e);
    return { ...r, lane };
  });
}

function Chip({ ev, className, onOpen, compact }: { ev: Ev; className?: string; onOpen: (ev: Ev) => void; compact?: boolean }) {
  const c = CAT[ev.cat];
  const I = ev.icon;
  const body = (
    <>
      {I && <I className="h-3 w-3 shrink-0 opacity-70" />}
      {ev.done && ev.item && <Check className="h-3 w-3 shrink-0" />}
      <span className={cn("truncate", ev.done && ev.cat !== "ACCESS" && "line-through opacity-60")}>{ev.title}</span>
    </>
  );
  const cls = cn("flex h-[22px] w-full items-center gap-1 overflow-hidden rounded-[5px] border-l-[3px] px-1.5 text-left text-[11.5px] font-medium leading-none transition-[filter] hover:brightness-[.97]",
    ev.tone || cn(c.chip, c.text), compact && "h-5 text-[11px]", className);
  const tip = [ev.title, ev.sub].filter(Boolean).join("\n");
  if (ev.href) return <Link href={ev.href} title={tip} className={cls}>{body}</Link>;
  return <button type="button" title={tip} onClick={(e) => { e.stopPropagation(); onOpen(ev); }} className={cn(cls, !ev.item && "cursor-default")}>{body}</button>;
}

function TimedBlock({ ev, col, cols, onOpen }: { ev: Ev; col: number; cols: number; onOpen: (ev: Ev) => void }) {
  const c = CAT[ev.cat];
  const mins = ev.start.getHours() * 60 + ev.start.getMinutes();
  const dur = Math.max(22, (ev.end.getTime() - ev.start.getTime()) / 60000);
  const h = (dur / 60) * HOUR;
  return (
    <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(ev); }} title={[ev.title, ev.sub].filter(Boolean).join("\n")}
      className={cn("cal-pop absolute overflow-hidden rounded-md border-l-[3px] px-1.5 text-left", h < 30 ? "flex items-center py-0" : "py-1", " shadow-[0_1px_0_rgba(0,0,0,0.04)] transition-[filter,box-shadow] hover:z-20 hover:shadow-md",
        ev.done ? "border bg-card text-muted-foreground" : cn(c.chip, c.text), ev.done && c.chip.split(" ")[0])}
      style={{ top: (mins / 60) * HOUR + 1, height: h - 2, left: `calc(${(col / cols) * 100}% + 2px)`, width: `calc(${100 / cols}% - 4px)` }}>
      {h < 30 ? (
        <div className={cn("flex items-baseline gap-1.5 truncate text-[11px] leading-none", ev.done && "line-through")}>
          <span className="truncate font-semibold">{ev.title}</span><span className="shrink-0 opacity-70">{fmtTime(ev.start)}</span>
        </div>
      ) : <div className={cn("truncate text-[12px] font-semibold leading-tight", ev.done && "line-through")}>{ev.title}</div>}
      {h > 34 && <div className={cn("truncate text-[10.5px] opacity-75", ev.done && "line-through")}>{fmtTime(ev.start)} – {fmtTime(ev.end)}</div>}
      {h > 60 && ev.sub && <div className="mt-0.5 line-clamp-2 text-[10.5px] opacity-70">{ev.sub}</div>}
    </button>
  );
}

function MiniMonth({ cursor, onPick, rangeStart, rangeDays }: { cursor: Date; onPick: (d: Date) => void; rangeStart: Date; rangeDays: number }) {
  const [month, setMonth] = useState(() => new Date(cursor.getFullYear(), cursor.getMonth(), 1));
  useEffect(() => { setMonth(new Date(cursor.getFullYear(), cursor.getMonth(), 1)); }, [cursor]);
  const first = startOfWeek(month);
  const today = new Date();
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[13px] font-semibold">{month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</div>
        <div className="flex">
          <button aria-label="Previous month" className="rounded p-1 text-muted-foreground hover:bg-accent" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft className="h-3.5 w-3.5" /></button>
          <button aria-label="Next month" className="rounded p-1 text-muted-foreground hover:bg-accent" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight className="h-3.5 w-3.5" /></button>
        </div>
      </div>
      <div className="grid grid-cols-7 text-center text-[9.5px] font-medium uppercase tracking-wide text-muted-foreground">{WEEKDAYS.map((d) => <div key={d} className="pb-1">{d.slice(0, 2)}</div>)}</div>
      <div className="grid grid-cols-7 gap-y-0.5 text-center text-[11.5px]">
        {Array.from({ length: 42 }).map((_, i) => {
          const d = addDays(first, i);
          const inRange = dayDiff(d, rangeStart) >= 0 && dayDiff(d, rangeStart) < rangeDays;
          const isToday = sameDay(d, today);
          return (
            <button key={i} onClick={() => onPick(d)}
              className={cn("mx-auto flex h-6 w-6 items-center justify-center rounded-md tabular transition-colors",
                d.getMonth() !== month.getMonth() && "text-muted-foreground/45",
                inRange && !isToday && "bg-violet/10 font-medium text-violet",
                isToday ? "bg-violet font-semibold text-white" : "hover:bg-accent")}>{d.getDate()}</button>
          );
        })}
      </div>
    </div>
  );
}

/** Week / day / month calendar for the signed-in employee, plus an agenda list on phones. */
export function EmployeeCalendar({ timeline }: { timeline: any }) {
  const [view, setView] = useState<View>("week");
  const [cursor, setCursor] = useState(() => startOfDay(new Date()));
  const [off, setOff] = useState<Set<CatKey>>(new Set());
  const [draft, setDraft] = useState<PlannerDraft | null>(null);
  const [showAllLanes, setShowAllLanes] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => { const t = setInterval(() => setNow(new Date()), 60000); return () => clearInterval(t); }, []);
  useEffect(() => { if (scroller.current) scroller.current.scrollTop = HOUR * 7.6; }, [view]);

  const { first, days } = useMemo(() => {
    if (view === "day") return { first: cursor, days: 1 };
    if (view === "week") return { first: startOfWeek(cursor), days: 7 };
    return { first: startOfWeek(new Date(cursor.getFullYear(), cursor.getMonth(), 1)), days: 42 };
  }, [view, cursor]);
  // Phones always get the agenda for the cursor's week, so fetch at least that week.
  const fetchStart = view === "day" ? startOfWeek(cursor) : first;
  const fetchEnd = addDays(fetchStart, Math.max(days, 7));
  const { data: planner } = useSWR(plannerKey(fetchStart, fetchEnd), fetcher, { keepPreviousData: true });

  const events = useMemo(() => buildEvents(planner, timeline).filter((e) => !off.has(e.cat)), [planner, timeline, off]);
  const visDays = Array.from({ length: days }, (_, i) => addDays(first, i));
  const open = (ev: Ev) => { if (ev.item) setDraft({ item: ev.item }); };

  const step = (dir: number) => setCursor((c) => view === "day" ? addDays(c, dir) : view === "week" ? addDays(c, 7 * dir) : new Date(c.getFullYear(), c.getMonth() + dir, 1));
  const title = view === "month" ? cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" })
    : view === "day" ? cursor.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })
    : `${fmtDay(first, { day: "numeric", month: "short" })} – ${fmtDay(addDays(first, 6), { day: "numeric", month: "short", year: "numeric" })}`;

  const counts = useMemo(() => {
    const all = buildEvents(planner, timeline);
    return Object.fromEntries(FILTERS.map((k) => [k, all.filter((e) => e.cat === k).length]));
  }, [planner, timeline]);

  return (
    <Card id="employee-calendar" className="overflow-hidden">
      <div className="flex min-h-0 flex-col lg:flex-row">
        {/* ----------------------------------------------------------- sidebar */}
        <aside className="hidden w-[232px] shrink-0 flex-col gap-5 border-r bg-muted/25 p-4 lg:flex">
          <button onClick={() => setDraft({})} className="flex h-9 items-center justify-center gap-1.5 rounded-full bg-violet text-[13px] font-medium text-white shadow-sm shadow-violet/25 transition hover:bg-violet/90">
            <Plus className="h-4 w-4" />New task
          </button>
          <MiniMonth cursor={cursor} rangeStart={first} rangeDays={view === "month" ? 0 : days} onPick={(d) => { setCursor(d); if (view === "month") setView("week"); }} />
          <div>
            <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">My calendars</div>
            <div className="space-y-0.5">
              {FILTERS.map((k) => {
                const on = !off.has(k);
                return (
                  <button key={k} onClick={() => setOff((s) => { const n = new Set(s); on ? n.add(k) : n.delete(k); return n; })}
                    className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[12.5px] hover:bg-accent">
                    <span className={cn("flex h-3.5 w-3.5 items-center justify-center rounded-[4px] border-2", on ? cn(CAT[k].dot, "border-transparent") : "border-muted-foreground/40")}>
                      {on && <Check className="h-2.5 w-2.5 text-white" strokeWidth={3.5} />}
                    </span>
                    <span className={cn("flex-1", !on && "text-muted-foreground")}>{CAT[k].label}</span>
                    <span className="text-2xs tabular text-muted-foreground">{counts[k] || ""}</span>
                  </button>
                );
              })}
            </div>
          </div>
          {timeline?.project && (
            <div className="mt-auto rounded-lg border bg-card p-2.5 text-2xs">
              <div className="font-medium text-foreground">{timeline.project.name}</div>
              <div className="mt-0.5 text-muted-foreground">Access you get for this project ends by <b className="text-foreground">{fmtDay(new Date(timeline.project.end_date))}</b>.</div>
            </div>
          )}
        </aside>

        {/* ----------------------------------------------------------- main */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 border-b px-3 py-3 sm:px-4">
            <CalendarDays className="h-4 w-4 text-violet" />
            <h3 className="mr-auto text-[15px] font-semibold tracking-tight sm:text-[17px]">{title}</h3>
            <div className="flex items-center rounded-full border bg-card p-0.5 shadow-sm">
              <button aria-label="Previous" onClick={() => step(-1)} className="rounded-full p-1 text-muted-foreground hover:bg-accent"><ChevronLeft className="h-4 w-4" /></button>
              <button onClick={() => setCursor(startOfDay(new Date()))} className="px-2.5 text-[10.5px] font-semibold uppercase tracking-[0.14em]">Today</button>
              <button aria-label="Next" onClick={() => step(1)} className="rounded-full p-1 text-muted-foreground hover:bg-accent"><ChevronRight className="h-4 w-4" /></button>
            </div>
            <div className="hidden rounded-full border bg-muted/40 p-0.5 md:flex">
              {(["day", "week", "month"] as View[]).map((v) => (
                <button key={v} onClick={() => setView(v)} className={cn("rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors", view === v ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>{v}</button>
              ))}
            </div>
            <button aria-label="New task" onClick={() => setDraft({})} className="flex h-8 w-8 items-center justify-center rounded-full bg-violet text-white shadow-sm shadow-violet/30 transition hover:scale-105 lg:hidden"><Plus className="h-4 w-4" /></button>
          </div>

          {/* desktop / tablet grid */}
          <div className="hidden md:block">
            {view === "month" ? (
              <MonthGrid first={first} cursor={cursor} events={events} now={now} onOpen={open}
                onPickDay={(d) => { setCursor(d); setView("day"); }} onAdd={(d) => { const s = new Date(d); s.setHours(10, 0, 0, 0); setDraft({ start: s }); }} />
            ) : (
              <>
                {/* day headers */}
                <div className="grid border-b" style={{ gridTemplateColumns: `56px repeat(${days}, minmax(0,1fr))` }}>
                  <div />
                  {visDays.map((d) => {
                    const today = sameDay(d, now);
                    return (
                      <button key={d.toISOString()} onClick={() => { setCursor(d); setView("day"); }} className="px-1 py-2">
                        <div className={cn("mx-auto flex w-fit items-baseline gap-1.5 rounded-lg px-2.5 py-1 transition-colors", today ? "bg-violet text-white shadow-sm shadow-violet/30" : "hover:bg-accent")}>
                          <span className="text-[17px] font-semibold tabular leading-none">{d.getDate()}</span>
                          <span className={cn("text-[9.5px] font-semibold uppercase tracking-[0.14em]", today ? "text-white/85" : "text-muted-foreground")}>{d.toLocaleDateString(undefined, { weekday: days === 1 ? "long" : "short" })}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
                <AllDayRow first={first} days={days} events={events.filter((e) => e.allDay)} onOpen={open} expanded={showAllLanes} onToggle={() => setShowAllLanes((v) => !v)} />
                <TimeGrid scroller={scroller} visDays={visDays} events={events.filter((e) => !e.allDay)} now={now} onOpen={open}
                  onSlot={(d) => setDraft({ start: d })} />
              </>
            )}
          </div>

          {/* phone agenda */}
          <Agenda cursor={cursor} setCursor={setCursor} events={events} now={now} onOpen={open} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t bg-muted/20 px-4 py-2 text-2xs text-muted-foreground">
        <span>Click an empty slot to add a task. Your tasks are private to you.</span>
        <span className="inline-flex items-center gap-1"><Flag className="h-3 w-3" />Project dates</span>
        <span className="inline-flex items-center gap-1"><KeyRound className="h-3 w-3" />Access grant (start to expiry)</span>
        <span className="inline-flex items-center gap-1"><i className="h-px w-4 bg-critical" />Now</span>
      </div>

      <PlannerDialog draft={draft} onClose={() => setDraft(null)} />
    </Card>
  );
}

function AllDayRow({ first, days, events, onOpen, expanded, onToggle }: { first: Date; days: number; events: Ev[]; onOpen: (e: Ev) => void; expanded: boolean; onToggle: () => void }) {
  const spans = layoutSpans(events, first, days);
  const lanes = spans.length ? Math.max(...spans.map((s) => s.lane)) + 1 : 0;
  const LIMIT = 3;
  const shown = expanded ? lanes : Math.min(lanes, LIMIT);
  const hidden = spans.filter((s) => s.lane >= shown).length;
  return (
    <div className="grid border-b" style={{ gridTemplateColumns: `56px minmax(0,1fr)` }}>
      <div className="flex flex-col items-end justify-between py-1.5 pr-2 text-[9.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        <span>All day</span>
        {lanes > LIMIT && <button onClick={onToggle} className="normal-case tracking-normal text-violet hover:underline">{expanded ? "less" : `+${hidden}`}</button>}
      </div>
      <div className="relative" style={{ height: Math.max(30, shown * 25 + 8) }}>
        <div className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${days}, minmax(0,1fr))` }}>
          {Array.from({ length: days }).map((_, i) => <div key={i} className="border-l" />)}
        </div>
        {spans.filter((s) => s.lane < shown).map(({ ev, s, e, lane }) => (
          <div key={ev.id} className="cal-pop absolute px-[3px]" style={{ top: 4 + lane * 25, left: `${(s / days) * 100}%`, width: `${((e - s + 1) / days) * 100}%` }}>
            <Chip ev={ev} onOpen={onOpen} />
          </div>
        ))}
      </div>
    </div>
  );
}

function TimeGrid({ scroller, visDays, events, now, onOpen, onSlot }: {
  scroller: React.RefObject<HTMLDivElement | null>; visDays: Date[]; events: Ev[]; now: Date; onOpen: (e: Ev) => void; onSlot: (d: Date) => void;
}) {
  const n = visDays.length;
  const todayIdx = visDays.findIndex((d) => sameDay(d, now));
  const nowTop = ((now.getHours() * 60 + now.getMinutes()) / 60) * HOUR;
  return (
    <div ref={scroller} className="relative h-[540px] overflow-y-auto scroll-thin">
      <div className="relative grid" style={{ gridTemplateColumns: `56px repeat(${n}, minmax(0,1fr))`, height: HOUR * 24 }}>
        {/* hour labels */}
        <div className="relative">
          {Array.from({ length: 24 }).map((_, h) => h > 0 && (
            <div key={h} className="absolute right-2 -translate-y-1/2 text-[10px] tabular text-muted-foreground" style={{ top: h * HOUR }}>
              {new Date(2000, 0, 1, h).toLocaleTimeString(undefined, { hour: "numeric" })}
            </div>
          ))}
        </div>
        {visDays.map((d, i) => {
          const dayEvs = events.filter((e) => sameDay(e.start, d));
          const weekend = d.getDay() === 0 || d.getDay() === 6;
          return (
            <div key={d.toISOString()} className={cn("relative border-l", weekend && "bg-muted/30", i === todayIdx && "bg-violet/[0.035]")}
              onClick={(e) => {
                const y = e.clientY - e.currentTarget.getBoundingClientRect().top;
                const mins = Math.floor((y / HOUR) * 2) * 30;
                const s = new Date(d); s.setHours(0, mins, 0, 0); onSlot(s);
              }}>
              {Array.from({ length: 24 }).map((_, h) => (
                <div key={h} className="absolute inset-x-0 border-t border-border/70" style={{ top: h * HOUR }}>
                  <div className="absolute inset-x-0 border-t border-dashed border-border/40" style={{ top: HOUR / 2 }} />
                </div>
              ))}
              {layoutDay(dayEvs).map(({ ev, col, cols }) => <TimedBlock key={ev.id} ev={ev} col={col} cols={cols} onOpen={onOpen} />)}
            </div>
          );
        })}
        {todayIdx >= 0 && (
          <div className="pointer-events-none absolute inset-x-0 z-10" style={{ top: nowTop }}>
            <div className="absolute left-0 w-[52px] -translate-y-1/2 pr-1 text-right text-[10px] font-semibold tabular text-critical">{fmtTime(now)}</div>
            <div className="absolute left-14 right-0 h-px bg-critical/35" />
            <div className="absolute h-[2px] -translate-y-[0.5px] bg-critical" style={{ left: `calc(56px + (100% - 56px) * ${todayIdx / n})`, width: `calc((100% - 56px) / ${n})` }} />
            <div className="cal-now-dot absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-critical" style={{ left: `calc(56px + (100% - 56px) * ${todayIdx / n})` }} />
          </div>
        )}
      </div>
    </div>
  );
}

function MonthGrid({ first, cursor, events, now, onOpen, onPickDay, onAdd }: {
  first: Date; cursor: Date; events: Ev[]; now: Date; onOpen: (e: Ev) => void; onPickDay: (d: Date) => void; onAdd: (d: Date) => void;
}) {
  return (
    <div>
      <div className="grid grid-cols-7 border-b">{WEEKDAYS.map((d) => <div key={d} className="py-2 text-center text-[9.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{d}</div>)}</div>
      <div className="grid grid-cols-7">
        {Array.from({ length: 42 }).map((_, i) => {
          const d = addDays(first, i);
          const dayEvs = events.filter((e) => e.allDay ? dayDiff(d, e.start) >= 0 && dayDiff(e.end, d) >= 0 : sameDay(e.start, d))
            .sort((a, b) => RANK[a.cat] - RANK[b.cat] || a.start.getTime() - b.start.getTime());
          const fit = dayEvs.length > 3 ? 2 : 3;
          const today = sameDay(d, now);
          return (
            <div key={i} onClick={() => onAdd(d)} className={cn("group h-[108px] cursor-pointer overflow-hidden border-b border-l p-1 first:border-l-0 [&:nth-child(7n+1)]:border-l-0",
              d.getMonth() !== cursor.getMonth() && "bg-muted/30")}>
              <button onClick={(e) => { e.stopPropagation(); onPickDay(d); }}
                className={cn("mb-0.5 flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-[11.5px] font-semibold tabular",
                  today ? "bg-violet text-white" : d.getMonth() !== cursor.getMonth() ? "text-muted-foreground/60 hover:bg-accent" : "hover:bg-accent")}>{d.getDate()}</button>
              <div className="space-y-0.5">
                {dayEvs.slice(0, fit).map((ev) => <Chip key={ev.id} ev={ev} onOpen={onOpen} compact />)}
                {dayEvs.length > fit && <button onClick={(e) => { e.stopPropagation(); onPickDay(d); }} className="px-1 text-[10.5px] font-medium text-muted-foreground hover:text-foreground">+{dayEvs.length - fit} more</button>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Agenda({ cursor, setCursor, events, now, onOpen }: { cursor: Date; setCursor: (d: Date) => void; events: Ev[]; now: Date; onOpen: (e: Ev) => void }) {
  const wk = startOfWeek(cursor);
  const dayEvs = events.filter((e) => e.allDay ? dayDiff(cursor, e.start) >= 0 && dayDiff(e.end, cursor) >= 0 : sameDay(e.start, cursor))
    .sort((a, b) => Number(b.allDay) - Number(a.allDay) || a.start.getTime() - b.start.getTime());
  return (
    <div className="md:hidden">
      <div className="bg-gradient-to-b from-violet to-violet/85 px-3 pb-3 pt-2 text-white">
        <div className="grid grid-cols-7 text-center">
          {Array.from({ length: 7 }).map((_, i) => {
            const d = addDays(wk, i);
            const sel = sameDay(d, cursor);
            const has = events.some((e) => e.allDay ? dayDiff(d, e.start) >= 0 && dayDiff(e.end, d) >= 0 : sameDay(e.start, d));
            return (
              <button key={i} onClick={() => setCursor(d)} className="flex flex-col items-center gap-1 py-1">
                <span className="text-[9.5px] font-medium uppercase tracking-wide text-white/70">{WEEKDAYS[i].slice(0, 3)}</span>
                <span className={cn("flex h-8 w-8 items-center justify-center rounded-lg text-sm font-semibold tabular", sel ? "bg-white text-violet shadow" : sameDay(d, now) ? "ring-1 ring-white/70" : "")}>{d.getDate()}</span>
                <span className={cn("h-1 w-1 rounded-full", has ? "bg-white/90" : "bg-transparent")} />
              </button>
            );
          })}
        </div>
      </div>
      <div className="space-y-2 p-3">
        <div className="text-sm font-semibold">{cursor.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</div>
        {!dayEvs.length && <p className="py-6 text-center text-xs text-muted-foreground">Nothing planned. Tap + to add a task.</p>}
        {dayEvs.map((ev) => {
          const c = CAT[ev.cat];
          return (
            <button key={ev.id} onClick={() => onOpen(ev)} className={cn("flex w-full items-start gap-2 rounded-lg border border-l-4 px-3 py-2 text-left", ev.done ? "bg-card" : cn(c.chip, c.text), ev.tone)}>
              <div className="min-w-0 flex-1">
                <div className={cn("truncate text-[13px] font-medium", ev.done && "line-through opacity-70")}>{ev.title}</div>
                {ev.sub && <div className="truncate text-2xs opacity-70">{ev.sub}</div>}
              </div>
              <div className="shrink-0 text-right text-2xs font-medium tabular opacity-80">
                {ev.allDay ? "ALL DAY" : <>{fmtTime(ev.start)}<div className="opacity-70">to {fmtTime(ev.end)}</div></>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

