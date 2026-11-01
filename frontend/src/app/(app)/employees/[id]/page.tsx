"use client";

import Link from "next/link";
import { use, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { ArrowLeft, ArrowRightLeft, BadgeCheck, Briefcase, CalendarDays, CheckCircle2, MapPin, ShieldAlert, UserX, XCircle } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn, fmtDate, titleCase } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Avatar, EmptyState, ErrorState, KV, Skeleton } from "@/components/ui/misc";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Perms, SensitivityBadge, SeverityBadge, StatusBadge } from "@/components/status";
import { AreaSeries, HBars, StackedBars } from "@/components/charts";
import { StatTile } from "@/components/stat";
import { ProjectAccessBoxes } from "@/components/project-timeline";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";

function AdminActions({ u, onDone }: { u: any; onDone: () => void }) {
  const [mode, setMode] = useState<"deactivate" | "transfer" | null>(null);
  const [reason, setReason] = useState("");
  const [dept, setDept] = useState("");
  const [mgr, setMgr] = useState("");
  const { data: depts } = useSWR(mode === "transfer" ? "/api/departments" : null, fetcher);
  const { data: people } = useSWR(mode === "transfer" ? "/api/employees" : null, fetcher);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      if (mode === "deactivate") {
        const r = await api(`/api/employees/${u.id}/deactivate`, { json: { reason } });
        toast.success(`Deactivated · ${r.grants_revoked} grants and ${r.sessions_revoked} sessions revoked`);
      } else {
        const r = await api(`/api/employees/${u.id}/transfer`, { json: { department_id: dept, manager_id: mgr || null } });
        toast.success(`Transferred · ${r.reviews_created} carried-over grants queued for review`);
      }
      setMode(null); onDone();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  if (u.status !== "ACTIVE") return null;
  return (
    <>
      <Button variant="outline" onClick={() => setMode("transfer")}><ArrowRightLeft />Transfer</Button>
      <Button variant="destructive" onClick={() => setMode("deactivate")}><UserX />Deactivate</Button>
      <Dialog open={!!mode} onOpenChange={(o) => !o && setMode(null)}>
        <DialogContent title={mode === "deactivate" ? `Deactivate ${u.name}` : `Transfer ${u.name}`}
          description={mode === "deactivate" ? "Leaver process: all grants, tokens, sessions and emergency sessions are revoked immediately." : "Mover process: existing access is queued for recertification by the new manager."}>
          <div className="space-y-4">
            {mode === "deactivate" ? <Field label="Reason"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Resignation effective today" /></Field> : <>
              <Field label="New department"><Select value={dept} onChange={(e) => setDept(e.target.value)}><option value="">Select…</option>{depts?.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
              <Field label="New manager"><Select value={mgr} onChange={(e) => setMgr(e.target.value)}><option value="">None</option>{people?.filter((p: any) => p.roles.includes("MANAGER") && p.id !== u.id).map((p: any) => <option key={p.id} value={p.id}>{p.name} · {p.department}</option>)}</Select></Field>
            </>}
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setMode(null)}>Cancel</Button>
              <Button variant={mode === "deactivate" ? "destructive" : "default"} loading={busy} onClick={run} disabled={mode === "deactivate" ? reason.length < 3 : !dept}>Confirm</Button></div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function EmployeeProfile({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useSession();
  const { data: u, error, mutate } = useSWR(`/api/employees/${id}`, fetcher);
  const { data: charts } = useSWR(can("analytics:read") ? `/api/employees/${id}/analytics` : null, fetcher);
  const { data: timeline } = useSWR(can("analytics:read") ? `/api/employees/${id}/timeline` : null, fetcher);
  const { data: evidence } = useSWR(can("analytics:read") ? `/api/employees/${id}/evidence` : null, fetcher);
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (!u) return <div className="space-y-3"><Skeleton className="h-20" /><div className="grid grid-cols-4 gap-3">{[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-24" />)}</div><Skeleton className="h-80" /></div>;
  const w = u.work;
  return (
    <div className="animate-fade-in">
      <Link href="/employees" className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />Employee Intelligence</Link>
      <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <Avatar name={u.name} className="h-14 w-14 text-base" />
          <div>
            <div className="flex items-center gap-2"><h1 className="text-xl font-semibold tracking-tight">{u.name}</h1><StatusBadge status={u.status} /></div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1"><Briefcase className="h-3.5 w-3.5" />{u.designation} · {u.department}</span>
              <span className="font-mono">{u.employee_id}</span>
              <span className="inline-flex items-center gap-1"><CalendarDays className="h-3.5 w-3.5" />Joined {fmtDate(u.joined_at, false)}</span>
              {u.location && <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{u.location}</span>}
              {u.manager && <span>Reports to <Link className="text-foreground hover:text-violet" href={`/employees/${u.manager.id}`}>{u.manager.name}</Link></span>}
            </div>
          </div>
        </div>
        {u.can_manage && <div className="flex gap-2"><AdminActions u={u} onDone={() => mutate()} /></div>}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Verified tasks" value={w.verified_tasks} icon={BadgeCheck} tone="violet" />
        <StatTile label="Pending tasks" value={w.pending_tasks} />
        <StatTile label="On-time delivery" value={`${Math.round(w.on_time_rate * 100)}%`} />
        <StatTile label="Avg quality" value={w.avg_quality || "—"} hint="Verified reviews, out of 5" />
        <StatTile label="Successful operations" value={w.successful_operations} icon={CheckCircle2} tone="success" />
        <StatTile label="Denied attempts" value={w.denied_operations} icon={XCircle} tone={w.denied_operations ? "critical" : "default"} />
      </div>
      <p className="mt-2 text-2xs text-muted-foreground">Work metrics are derived only from recorded, verifiable task events. They are informational and never grant permissions. Security posture is shown separately below.</p>

      <Tabs defaultValue="analytics" className="mt-5">
        <TabsList>
          <TabsTrigger value="analytics">Work analytics</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="evidence">Evidence</TabsTrigger>
          <TabsTrigger value="access">Access & security</TabsTrigger>
          <TabsTrigger value="tasks">Projects & tasks</TabsTrigger>
        </TabsList>

        <TabsContent value="analytics">
          {!charts ? <Skeleton className="h-80" /> : (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card><CardHeader title="Daily work activity" description="Task events per day, last 30 days" /><CardBody><AreaSeries data={charts.daily_activity} x="date" y="events" /></CardBody></Card>
              <Card><CardHeader title="Weekly productivity" description="Verified task completions per week" /><CardBody><StackedBars data={charts.weekly_productivity} x="week" series={[{ key: "completed", label: "Completed", color: "series-1" }]} /></CardBody></Card>
              <div className="lg:col-span-2"><ProjectAccessBoxes endpoint={`/api/employees/${id}/project-timeline`} self={false} /></div>
              <Card><CardHeader title="Monthly task completion" description="Assigned vs completed" /><CardBody><StackedBars data={charts.monthly_completion} x="month" series={[{ key: "assigned", label: "Assigned", color: "series-4" }, { key: "completed", label: "Completed", color: "series-3" }]} /></CardBody></Card>
              <Card><CardHeader title="Project contribution" description="Verified tasks by project" /><CardBody>{charts.project_contribution.length ? <HBars data={charts.project_contribution} label="project" value="tasks" colorKey="series-1" /> : <EmptyState title="No verified work yet" />}</CardBody></Card>
              <Card><CardHeader title="Resource utilization" description="Authorized operations per resource" /><CardBody>{charts.resource_utilization.length ? <HBars data={charts.resource_utilization} label="resource" value="operations" colorKey="series-4" /> : <EmptyState title="No resource usage" />}</CardBody></Card>
              <Card><CardHeader title="Permission usage" description="Authorized operations by permission" /><CardBody>{charts.permission_usage.length ? <HBars data={charts.permission_usage} label="permission" value="count" colorKey="series-3" /> : <EmptyState title="No usage recorded" />}</CardBody></Card>
              <Card><CardHeader title="Access request history" description="Requests per month by outcome" /><CardBody><StackedBars data={charts.access_request_history} x="month" series={[{ key: "approved", label: "Approved", color: "status-good" }, { key: "rejected", label: "Rejected", color: "status-critical" }, { key: "pending", label: "Open/other", color: "series-4" }]} /></CardBody></Card>
              <Card><CardHeader title="Successful vs denied access" description="Gateway decisions per week" /><CardBody><StackedBars data={charts.access_outcomes} x="week" series={[{ key: "allowed", label: "Allowed", color: "status-good" }, { key: "denied", label: "Denied", color: "status-critical" }]} /></CardBody></Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="timeline">
          <Card>
            {!timeline ? <Skeleton className="h-80" /> : (
              <Table>
                <THead><TR><TH>Date</TH><TH>Project</TH><TH>Task</TH><TH>Resource accessed</TH><TH>Action</TH><TH>Outcome</TH></TR></THead>
                <TBody>
                  {timeline.map((t: any) => (
                    <TR key={t.event_id}>
                      <TD className="whitespace-nowrap text-muted-foreground">{fmtDate(t.at)}</TD>
                      <TD>{t.project || <Badge tone="outline">Access</Badge>}</TD>
                      <TD className="max-w-[260px] truncate">{t.task || "—"}</TD>
                      <TD>{t.resource || "—"}</TD>
                      <TD><span className="font-mono text-xs">{t.action}</span></TD>
                      <TD>{["DENIED"].includes(t.outcome) ? <StatusBadge status="DENIED" /> : t.outcome === "ALLOWED" ? <StatusBadge status="ALLOWED" /> : <Badge tone={t.outcome === "VERIFIED" ? "violet" : "neutral"}>{titleCase(t.outcome)}</Badge>}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="evidence">
          <Card>
            <CardHeader title="Underlying evidence" description="Completed tasks in the last 90 days with verification records. This is what the leaderboard and analytics are computed from." />
            {!evidence ? <Skeleton className="h-60" /> : !evidence.length ? <EmptyState title="No completed tasks in this window" /> : (
              <Table>
                <THead><TR><TH>Task</TH><TH>Project</TH><TH>Priority</TH><TH>Completed</TH><TH>On time</TH><TH>Quality</TH><TH>Verified by</TH></TR></THead>
                <TBody>{evidence.map((e: any) => (
                  <TR key={e.task_id}>
                    <TD><span className="mr-2 font-mono text-2xs text-muted-foreground">{e.code}</span>{e.title}</TD>
                    <TD>{e.project}</TD><TD><Badge tone="outline">{e.priority}</Badge></TD>
                    <TD className="whitespace-nowrap text-muted-foreground">{fmtDate(e.completed_at)}</TD>
                    <TD>{e.on_time ? <CheckCircle2 className="h-4 w-4 text-success" /> : <XCircle className="h-4 w-4 text-warning" />}</TD>
                    <TD className="tabular">{e.quality_score ?? "—"}</TD>
                    <TD>{e.verified ? e.verified_by : <Badge tone="warning">Unverified</Badge>}</TD>
                  </TR>))}</TBody>
              </Table>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="access">
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Current permissions" description={`${u.current_permissions.length} active grants`} />
              {!u.current_permissions.length ? <EmptyState title="No active access" /> : (
                <Table>
                  <THead><TR><TH>Resource</TH><TH>Permissions</TH><TH>Source</TH><TH>Purpose</TH><TH>Expires</TH></TR></THead>
                  <TBody>{u.current_permissions.map((g: any) => (
                    <TR key={g.id}><TD><div>{g.resource.name}</div><SensitivityBadge level={g.resource.sensitivity} /></TD><TD><Perms perms={g.permissions} /></TD>
                      <TD><Badge tone={g.source === "LEGACY" ? "warning" : g.is_emergency ? "critical" : "neutral"}>{g.source === "LEGACY" ? "Standing" : titleCase(g.source)}</Badge></TD>
                      <TD className="text-muted-foreground">{g.purpose_label}</TD><TD className="whitespace-nowrap text-muted-foreground">{g.expires_at ? fmtDate(g.expires_at) : "Never"}</TD></TR>))}</TBody>
                </Table>
              )}
              <CardHeader title="Access history" className="border-t" />
              <Table>
                <THead><TR><TH>Resource</TH><TH>Permissions</TH><TH>Status</TH><TH>Granted</TH><TH>Ended</TH></TR></THead>
                <TBody>{u.access_history.map((g: any) => (
                  <TR key={g.id}><TD>{g.resource.name}</TD><TD><Perms perms={g.permissions} /></TD><TD><StatusBadge status={g.status} /></TD>
                    <TD className="text-muted-foreground">{fmtDate(g.granted_at, false)}</TD><TD className="text-muted-foreground">{fmtDate(g.revoked_at, false)}</TD></TR>))}</TBody>
              </Table>
            </Card>
            <Card className="h-fit">
              <CardHeader title={<span className="inline-flex items-center gap-1.5"><ShieldAlert className="h-4 w-4 text-critical" />Security violations</span>} description="Kept separate from performance" />
              <CardBody>
                <KV k="Device trust (simulated)" v={titleCase(u.device_trust)} />
                <KV k="30-day activity" v={u.activity_level_30d} />
                <div className="mt-3 space-y-2">
                  {!u.security_violations.length ? <p className="text-xs text-muted-foreground">No violations recorded.</p> : u.security_violations.map((v: any) => (
                    <div key={v.id} className="rounded-md border p-2"><div className="flex items-center justify-between gap-2"><span className="text-xs font-medium">{v.title}</span><SeverityBadge severity={v.severity} /></div><div className="mt-1 text-2xs text-muted-foreground">{titleCase(v.category)} · {fmtDate(v.at)}</div></div>
                  ))}
                </div>
              </CardBody>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="tasks">
          <div className="grid gap-4 lg:grid-cols-3">
            <Card><CardHeader title="Current projects" /><CardBody className="space-y-2">{u.projects.map((p: any) => <div key={p.id} className="flex items-center justify-between rounded-md border px-3 py-2 text-[13px]"><span>{p.name}</span><Badge tone="outline">{p.role}</Badge></div>)}</CardBody></Card>
            <Card><CardHeader title="Pending tasks" description={`${u.pending_tasks.length} open`} /><CardBody className="space-y-1.5">{u.pending_tasks.slice(0, 12).map((t: any) => <div key={t.id} className="flex justify-between gap-2 text-[13px]"><span className="truncate">{t.title}</span><Badge tone={t.status === "IN_PROGRESS" ? "info" : "neutral"}>{titleCase(t.status)}</Badge></div>)}</CardBody></Card>
            <Card><CardHeader title="Recently completed" /><CardBody className="space-y-1.5">{u.completed_tasks.slice(0, 12).map((t: any) => <div key={t.id} className="flex justify-between gap-2 text-[13px]"><span className="truncate">{t.title}</span>{t.verified ? <BadgeCheck className={cn("h-4 w-4 shrink-0 text-violet")} /> : null}</div>)}</CardBody></Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
