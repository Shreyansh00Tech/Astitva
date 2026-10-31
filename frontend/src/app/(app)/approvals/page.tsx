"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { CalendarClock, ClipboardCheck, RotateCcw } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn, fmtDate, hours, relTime, titleCase } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Perms, PriorityBadge, RiskBadge, SensitivityBadge, StatusBadge } from "@/components/status";
import { Select } from "@/components/ui/input";
import { MiniStepper } from "@/components/stepper";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";

function RequestTable({ rows, empty, showPriority }: { rows: any[]; empty: string; showPriority?: boolean }) {
  const router = useRouter();
  if (!rows.length) return <EmptyState icon={ClipboardCheck} title={empty} />;
  return (
    <Table>
      <THead><TR><TH>Request</TH>{showPriority && <TH>Priority</TH>}{showPriority && <TH>Needed by</TH>}<TH>Requester</TH><TH>Resource</TH><TH>Purpose</TH><TH>Scope</TH><TH>Duration</TH><TH>Risk</TH><TH>Stage</TH><TH>Required reviewers</TH><TH>Age</TH></TR></THead>
      <TBody>
        {rows.map((r) => (
          <TR key={r.id} className="cursor-pointer" onClick={() => router.push(`/approvals/${r.id}`)}>
            <TD><span className="font-mono text-xs font-medium text-violet">{r.ref}</span></TD>
            {showPriority && <TD title={r.priority?.reasons?.join("\n")}><PriorityBadge p={r.priority} /></TD>}
            {showPriority && <TD className={cn("whitespace-nowrap text-xs", r.priority?.overdue ? "font-medium text-critical" : "text-muted-foreground")}>
              {r.deadline_at ? <>{fmtDate(r.deadline_at)}<div className="text-2xs">{relTime(r.deadline_at)}</div></> : "—"}
              <div className="text-2xs text-muted-foreground">{r.business_impact && `${titleCase(r.business_impact)} impact`}</div></TD>}
            <TD><div className="font-medium whitespace-nowrap">{r.requester.name}</div><div className="text-2xs text-muted-foreground">{r.requester.designation} · {r.requester.department}</div></TD>
            <TD><div className="whitespace-nowrap">{r.resource.name}</div><SensitivityBadge level={r.resource.sensitivity} /></TD>
            <TD className="text-muted-foreground">{r.purpose_label}</TD>
            <TD><Perms perms={r.approved_permissions} /></TD>
            <TD className="tabular">{hours(r.approved_duration_hours)}</TD>
            <TD><RiskBadge level={r.risk?.level} score={r.risk?.score} /></TD>
            <TD><MiniStepper key={`${r.status}-${r.current_stage}`} r={r} /></TD>
            <TD className="text-xs text-muted-foreground">{r.stage_approvers?.join(", ") || "—"}</TD>
            <TD className="whitespace-nowrap text-muted-foreground">{relTime(r.created_at)}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function Reviews() {
  const { can } = useSession();
  const { data, error, isLoading, mutate } = useSWR("/api/reviews?scope=mine", fetcher);
  const [restrict, setRestrict] = useState<any>(null);
  const [keep, setKeep] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const decide = async (id: string, decision: string, permissions?: string[], c?: string) => {
    try { await api(`/api/reviews/${id}/decide`, { json: { decision, permissions, comment: c } }); toast.success(`Access ${decision.toLowerCase()}ed`); mutate(); setRestrict(null); }
    catch (e) { toast.error(errorMessage(e)); }
  };
  const start = async () => {
    try { const r = await api("/api/reviews/campaigns", { json: {} }); toast.success(`Campaign started · ${r.items} review item(s)`); mutate(); }
    catch (e) { toast.error(errorMessage(e)); }
  };
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (isLoading) return <LoadingRows />;
  const pending = data.reviews.filter((r: any) => r.status === "PENDING");
  const overdue = pending.filter((r: any) => r.overdue);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-2 text-xs">
          <Badge tone="warning">{pending.length} pending</Badge>
          {overdue.length > 0 && <Badge tone="critical">{overdue.length} overdue</Badge>}
          <Badge tone="neutral">{data.reviews.length - pending.length} decided</Badge>
        </div>
        {can("reviews:initiate") && <Button size="sm" variant="outline" onClick={start}><RotateCcw />Start access review</Button>}
      </div>
      <Card>
        {!data.reviews.length ? <EmptyState icon={CalendarClock} title="No access reviews assigned" description="Reviews are generated every 30 days and when employees change departments." /> : (
          <Table>
            <THead><TR><TH>Employee</TH><TH>Resource</TH><TH>Permissions</TH><TH>Last used</TH><TH>Due</TH><TH>Status</TH><TH className="text-right">Decision</TH></TR></THead>
            <TBody>
              {data.reviews.map((r: any) => (
                <TR key={r.id}>
                  <TD className="font-medium whitespace-nowrap">{r.user?.name}<div className="text-2xs font-normal text-muted-foreground">{r.user?.department}</div></TD>
                  <TD className="whitespace-nowrap">{r.resource?.name}</TD>
                  <TD><Perms perms={r.permissions} /></TD>
                  <TD className="text-xs">{r.unused ? <Badge tone="warning">Unused 30d</Badge> : <span className="text-muted-foreground">{relTime(r.last_used_at)}</span>}</TD>
                  <TD className="whitespace-nowrap text-xs">{r.overdue ? <Badge tone="critical">Overdue · {fmtDate(r.due_at, false)}</Badge> : <span className="text-muted-foreground">{fmtDate(r.due_at, false)}</span>}</TD>
                  <TD><StatusBadge status={r.status} /></TD>
                  <TD className="text-right">
                    {r.status === "PENDING" && r.grant_status === "ACTIVE" ? (
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="outline" onClick={() => decide(r.id, "RETAIN", undefined, "Still required")}>Retain</Button>
                        <Button size="sm" variant="outline" disabled={r.permissions.length < 2} onClick={() => { setRestrict(r); setKeep(r.permissions.slice(0, 1)); setComment(""); }}>Restrict</Button>
                        <Button size="sm" variant="outline" className="text-critical" onClick={() => decide(r.id, "REVOKE", undefined, "No longer required")}>Revoke</Button>
                      </div>
                    ) : r.status === "PENDING" ? <span className="text-2xs text-muted-foreground">Grant {r.grant_status?.toLowerCase()}</span> : <span className="text-2xs text-muted-foreground">{fmtDate(r.decided_at)}</span>}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      <Dialog open={!!restrict} onOpenChange={(o) => !o && setRestrict(null)}>
        {restrict && <DialogContent title="Restrict access" description={`${restrict.user?.name} · ${restrict.resource?.name}`}>
          <div className="space-y-4">
            <Field label="Permissions to keep">
              <div className="flex flex-wrap gap-1.5">{restrict.permissions.map((p: string) => { const on = keep.includes(p); return (
                <button key={p} onClick={() => setKeep(on ? keep.filter((x) => x !== p) : [...keep, p])} className={`rounded-md border px-2.5 py-1 font-mono text-xs ${on ? "border-violet bg-violet/10 text-violet" : "text-muted-foreground line-through"}`}>{p}</button>); })}</div>
            </Field>
            <Field label="Comment"><Textarea value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
            <div className="flex justify-end"><Button onClick={() => decide(restrict.id, "RESTRICT", keep, comment)} disabled={!keep.length || keep.length === restrict.permissions.length}>Restrict</Button></div>
          </div>
        </DialogContent>}
      </Dialog>
    </div>
  );
}

const FILTERS = [["", "All"], ["overdue", "Overdue"], ["approaching", "Due in 24h"], ["CRITICAL", "Critical"], ["HIGH", "High"], ["MEDIUM", "Medium"], ["LOW", "Low"]];

function QueueToolbar({ sort, setSort, filter, setFilter, data }: any) {
  const all = data ? [...data.actionable, ...data.watching] : [];
  const overdue = all.filter((r: any) => r.priority?.overdue).length;
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <div className="flex flex-wrap gap-1 rounded-lg border bg-muted/40 p-1">
        {FILTERS.map(([v, l]) => (
          <button key={v} onClick={() => setFilter(v)}
            className={cn("rounded-md px-2.5 py-1 text-xs font-medium transition-all duration-200",
              filter === v ? "bg-card text-foreground shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-foreground")}>
            {l}{v === "overdue" && overdue > 0 && filter !== "overdue" && <span className="ml-1 rounded bg-critical/15 px-1 text-critical tabular">{overdue}</span>}
          </button>
        ))}
      </div>
      <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
        Sort by
        <Select value={sort} onChange={(e) => setSort(e.target.value)} className="h-8 w-44 text-xs">
          <option value="priority">Highest priority</option>
          <option value="deadline">Earliest deadline</option>
          <option value="waiting">Waiting longest</option>
        </Select>
      </div>
      <p className="w-full text-2xs text-muted-foreground">Priority = 40% deadline + 30% business impact + 20% waiting time + 10% urgency. It only sets the order; it never changes the risk score or who must approve.</p>
    </div>
  );
}

function Inner() {
  const params = useSearchParams();
  const { can } = useSession();
  const [sort, setSort] = useState("priority");
  const [filter, setFilter] = useState("");
  const qs = `sort=${sort}${filter ? `&filter=${filter}` : ""}`;
  const { data, error, isLoading, mutate } = useSWR(`/api/approvals/queue?${qs}`, fetcher, { refreshInterval: 20000, keepPreviousData: true });
  return (
    <>
      <PageHeader title="Approval Center" description="Independent, staged approvals enforced by the separation-of-duties engine. You only see actions you're eligible to take." />
      <Tabs defaultValue={params.get("tab") || "queue"}>
        <TabsList>
          <TabsTrigger value="queue">Needs my decision {data && <Badge tone="violet" className="ml-1">{data.actionable.length}</Badge>}</TabsTrigger>
          <TabsTrigger value="watching">In flight</TabsTrigger>
          <TabsTrigger value="history">My decisions</TabsTrigger>
          {can("reviews:read") && <TabsTrigger value="reviews">Access reviews</TabsTrigger>}
        </TabsList>
        {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading ? <LoadingRows /> : <>
          <TabsContent value="queue"><QueueToolbar {...{ sort, setSort, filter, setFilter, data }} /><Card><RequestTable showPriority rows={data.actionable} empty={filter ? "Nothing matches this filter" : "Nothing waiting on you"} /></Card></TabsContent>
          <TabsContent value="watching"><QueueToolbar {...{ sort, setSort, filter, setFilter, data }} /><Card><RequestTable showPriority rows={data.watching} empty={filter ? "Nothing matches this filter" : "No other requests in flight"} /></Card></TabsContent>
          <TabsContent value="history"><Card><RequestTable rows={data.history} empty="You haven't decided on any requests yet" /></Card></TabsContent>
        </>}
        <TabsContent value="reviews"><Reviews /></TabsContent>
      </Tabs>
    </>
  );
}

export default function ApprovalsPage() { return <Suspense><Inner /></Suspense>; }
