"use client";

import useSWR from "swr";
import { CalendarClock, Flag, FolderKanban, Link2, Users } from "lucide-react";
import { fetcher } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useCountUp, useMounted } from "@/lib/motion";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Avatar, EmptyState, Skeleton } from "@/components/ui/misc";
import { Badge } from "@/components/ui/badge";

const DAY = 86400000;
const short = (v?: string | null) => (v ? new Date(v).toLocaleDateString(undefined, { day: "2-digit", month: "short" }) : "—");
const inDays = (n?: number | null) => (n == null ? "" : n < 0 ? `${-n}d ago` : n === 0 ? "today" : `in ${n}d`);

// Both boxes share one fixed height on large screens so they sit as an equal pair under Daily work activity.
const BOX = "flex h-full flex-col lg:h-[460px]";

function ProjectCard({ d, self }: { d: any; self: boolean }) {
  const p = d.project;
  const timed = d.grants.filter((g: any) => g.status === "ACTIVE");
  const inside = timed.filter((g: any) => g.within_project).length;
  const mounted = useMounted();
  const pct = useCountUp(Math.round((p.progress ?? 0) * 100));
  return (
    <Card className={BOX}>
      <CardHeader title={<span className="inline-flex items-center gap-1.5"><FolderKanban className="h-4 w-4 text-violet" />Current project</span>}
        description={self ? "The project your time-bound access is tied to" : "The project this employee's time-bound access is tied to"} action={<Badge tone="success">{p.status === "ACTIVE" ? "Active" : p.status}</Badge>} />
      <CardBody className="flex min-h-0 flex-1 flex-col gap-4">
        <div>
          <div className="flex flex-wrap items-baseline gap-x-2"><h4 className="text-base font-semibold tracking-tight">{p.name}</h4><span className="font-mono text-2xs text-muted-foreground">{p.code}</span></div>
          <p className="mt-0.5 text-xs text-muted-foreground">{p.team_name} · {p.department}{p.my_role ? ` · ${self ? "You" : "Role"}: ${p.my_role}` : ""}</p>
        </div>

        <div className="grid grid-cols-3 gap-2">
          {[["Start", p.start_date, null], ["Submission due", p.submission_date, p.days_to_submission], ["Project end", p.end_date, p.days_to_end]].map(([k, v, n], i) => (
            <div key={k as string} className={cn("ov-rise relative rounded-md border px-2.5 py-2", k === "Submission due" && "border-warning/30 bg-warning/5")} style={{ animationDelay: `${i * 90}ms` }}>
              {k === "Submission due" && <span aria-hidden className="ov-soft-pulse pointer-events-none absolute -inset-px rounded-md border border-warning/40" />}
              <div className="text-2xs text-muted-foreground">{k}</div>
              <div className="text-sm font-semibold tabular">{short(v as string)}</div>
              {n != null && <div className={cn("text-2xs", k === "Submission due" ? "text-warning" : "text-muted-foreground")}>{inDays(n as number)}</div>}
            </div>
          ))}
        </div>

        {p.progress != null && (
          <div>
            <div className="mb-1 flex justify-between text-2xs text-muted-foreground"><span>Time elapsed</span><span className="tabular">{Math.round(pct)}%</span></div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="ov-bar h-full rounded-full bg-violet" style={{ width: mounted ? `${p.progress * 100}%` : 0 }} /></div>
            <div className="mt-1 text-2xs text-muted-foreground">{self ? "Your tasks" : "Tasks"}: {p.tasks.done} done · {p.tasks.open} open</div>
          </div>
        )}

        <div className="min-h-0 flex-1">
          <div className="mb-1.5 flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wide text-muted-foreground"><Users className="h-3.5 w-3.5" />Team · {d.team.length}</div>
          <div className="max-h-full space-y-1.5 overflow-y-auto scroll-thin pr-1">
            {d.team.map((m: any, i: number) => (
              <div key={m.id} className="ov-slide flex items-center gap-2" style={{ animationDelay: `${300 + i * 90}ms` }}>
                <Avatar name={m.name} className="h-6 w-6" />
                <div className="min-w-0 flex-1 truncate text-[13px]">{m.name}{m.is_me && self && <span className="text-muted-foreground"> (you)</span>}<span className="text-2xs text-muted-foreground"> · {m.designation}</span></div>
                <Badge tone={m.role === "Project Manager" ? "violet" : m.role === "Security Reviewer" ? "critical" : "outline"}>{m.role}</Badge>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-start gap-2 rounded-md border border-violet/20 bg-violet/5 px-2.5 py-2 text-xs">
          <Link2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-violet" />
          <span>Access ends with the project: {timed.length
            ? <><b className="tabular">{inside}</b> of <b className="tabular">{timed.length}</b> active time-bound grants expire on or before <b>{short(p.end_date)}</b>.</>
            : <>new grants will expire on or before <b>{short(p.end_date)}</b>, even if a longer duration is approved.</>}
            {d.standing_grants > 0 && <span className="text-muted-foreground"> {d.standing_grants} standing grant{d.standing_grants > 1 ? "s" : ""} without expiry are not project-bound.</span>}</span>
        </div>
      </CardBody>
    </Card>
  );
}

function barTone(g: any, end: number) {
  if (g.status === "REVOKED") return "bg-critical/70";
  if (g.status === "EXPIRED") return "bg-muted-foreground/40";
  if (g.is_emergency) return "bg-serious";
  return new Date(g.expires_at).getTime() > end ? "bg-warning" : "bg-violet";
}

function TimelineCard({ d }: { d: any }) {
  const p = d.project;
  const start = new Date(p.start_date).getTime();
  const submit = new Date(p.submission_date).getTime();
  const end = new Date(p.end_date).getTime();
  const now = new Date(d.now).getTime();
  const lo = Math.min(start, ...d.grants.map((g: any) => new Date(g.granted_at).getTime())) - 2 * DAY;
  const hi = Math.max(end, ...d.grants.map((g: any) => new Date(g.ended_at || g.expires_at).getTime())) + 3 * DAY;
  const x = (t: number) => `${((t - lo) / (hi - lo)) * 100}%`;
  const marks = [
    { t: start, label: "Start", cls: "bg-success", text: "text-success" },
    { t: submit, label: "Submission", cls: "bg-warning", text: "text-warning" },
    { t: end, label: "End", cls: "bg-critical", text: "text-critical" },
  ];
  return (
    <Card className={BOX}>
      <CardHeader title={<span className="inline-flex items-center gap-1.5"><CalendarClock className="h-4 w-4 text-violet" />Project & access timeline</span>}
        description="Project milestones, and when each grant was given and expires (newest first)" />
      <CardBody className="flex min-h-0 flex-1 flex-col">
        {/* milestone header */}
        <div className="grid grid-cols-[minmax(0,38%)_1fr] gap-3">
          <div />
          <div className="relative h-9">
            {marks.map((m, i) => {
              const pct = (m.t - lo) / (hi - lo);
              return (
                <div key={m.label} className={cn("absolute whitespace-nowrap text-2xs", i === 1 ? "top-4" : "top-0",
                  pct > 0.8 ? "-translate-x-full text-right" : pct < 0.2 ? "" : "-translate-x-1/2 text-center")} style={{ left: x(m.t) }}>
                  <span className={cn("font-medium", m.text)}>{m.label}</span> <span className="text-muted-foreground tabular">{short(new Date(m.t).toISOString())}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="relative min-h-0 flex-1 overflow-y-auto scroll-thin">
          <div className="pointer-events-none absolute inset-y-0 right-0 w-[calc(62%-0.75rem)]">
            <div className="absolute inset-y-0 bg-violet/[0.07]" style={{ left: x(start), width: `calc(${x(end)} - ${x(start)})` }} />
            {marks.map((m) => <div key={m.label} className={cn("absolute inset-y-0 w-px opacity-60", m.cls)} style={{ left: x(m.t) }} />)}
            <div className="absolute inset-y-0 w-px border-l border-dashed border-foreground/50" style={{ left: x(now) }} />
          </div>
          {!d.grants.length ? (
            <div className="relative"><EmptyState title="No time-bound access yet" description="Grants you receive will appear here against the project dates." /></div>
          ) : (
            <div className="relative space-y-2 py-1">
              {d.grants.map((g: any) => {
                const a = new Date(g.granted_at).getTime();
                const b = new Date(g.ended_at || g.expires_at).getTime();
                const tip = `${g.resource.name} · ${g.permissions.join(", ")}\nGranted ${new Date(g.granted_at).toLocaleString()}\n${g.status === "ACTIVE" ? "Expires" : "Ended"} ${new Date(g.ended_at || g.expires_at).toLocaleString()}${g.capped_to_project_end ? "\nExpiry capped at project end" : ""}`;
                return (
                  <div key={g.id} className="grid grid-cols-[minmax(0,38%)_1fr] items-center gap-3" title={tip}>
                    <div className="min-w-0">
                      <div className="truncate text-xs font-medium">{g.resource.name}</div>
                      <div className="truncate text-2xs text-muted-foreground">
                        <span className="font-mono">{g.permissions.join("·")}</span> · {short(g.granted_at)} → {short(g.ended_at || g.expires_at)}
                        {g.is_emergency && <span className="text-serious"> · break-glass</span>}
                      </div>
                    </div>
                    <div className="relative h-5">
                      <div className={cn("absolute top-1 h-3 rounded-sm", barTone(g, end), g.status === "ACTIVE" && "shadow-[0_0_0_1px_hsl(var(--violet)/0.35)]")}
                        style={{ left: x(a), width: `max(4px, calc(${x(b)} - ${x(a)}))` }} />
                      {g.capped_to_project_end && <Flag className="absolute top-0 h-3.5 w-3.5 -translate-x-1/2 text-critical" style={{ left: x(b) }} aria-label="Capped at project end" />}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t pt-2.5 text-2xs text-muted-foreground">
          <span className="inline-flex items-center gap-1"><i className="h-2 w-3 rounded-sm bg-violet" />Active</span>
          <span className="inline-flex items-center gap-1"><i className="h-2 w-3 rounded-sm bg-muted-foreground/40" />Expired</span>
          <span className="inline-flex items-center gap-1"><i className="h-2 w-3 rounded-sm bg-critical/70" />Revoked</span>
          <span className="inline-flex items-center gap-1"><i className="h-2 w-3 rounded-sm bg-serious" />Break-glass</span>
          <span className="inline-flex items-center gap-1"><i className="h-2 w-3 rounded-sm bg-warning" />Runs past project end</span>
          <span className="inline-flex items-center gap-1"><Flag className="h-3 w-3 text-critical" />Capped at project end</span>
          <span className="inline-flex items-center gap-1"><i className="h-2.5 w-0 border-l border-dashed border-foreground/60" />Today</span>
        </div>
      </CardBody>
    </Card>
  );
}

/** Two equal boxes: the current project with its team, and one timeline of project dates plus access grants. */
export function ProjectAccessBoxes({ endpoint, self = true }: { endpoint: string; self?: boolean }) {
  const { data } = useSWR(endpoint, fetcher, { refreshInterval: 60000 });
  if (!data) return <div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-[460px]" /><Skeleton className="h-[460px]" /></div>;
  if (!data.project) return (
    <Card><EmptyState icon={FolderKanban} title="No active project" description={self ? "Access you request is not tied to a project until you join one." : "This employee is not on an active project."} /></Card>
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ProjectCard d={data} self={self} />
      <TimelineCard d={data} />
    </div>
  );
}
