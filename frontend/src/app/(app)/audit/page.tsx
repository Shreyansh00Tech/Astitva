"use client";

import { Fragment, Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { CheckCircle2, ChevronDown, ChevronRight, Download, Link2, Search, ShieldCheck, ShieldX, XCircle } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn, fmtDate, relTime, titleCase } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingRows, Mono, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input, Select } from "@/components/ui/input";
import { SeverityBadge, StatusBadge } from "@/components/status";

function Events() {
  const { can } = useSession();
  const [q, setQ] = useState(""); const [action, setAction] = useState(""); const [resource, setResource] = useState("");
  const [from, setFrom] = useState(""); const [to, setTo] = useState(""); const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const { data: resources } = useSWR("/api/resources", fetcher);
  const params = new URLSearchParams({ page: String(page), page_size: "40", ...(q && { q }), ...(action && { action }), ...(resource && { resource_id: resource }),
    ...(from && { date_from: new Date(from).toISOString() }), ...(to && { date_to: new Date(to + "T23:59:59").toISOString() }) });
  const { data, error, isLoading, mutate } = useSWR(`/api/audit/events?${params}`, fetcher, { keepPreviousData: true });
  const exportParams = new URLSearchParams(params); exportParams.delete("page"); exportParams.delete("page_size");
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-60"><Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="Actor, action, target, reason" className="h-8 pl-8 text-xs" /></div>
        <Select value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} className="h-8 w-56 text-xs"><option value="">All actions</option>{data?.actions.map((a: string) => <option key={a} value={a}>{a}</option>)}</Select>
        <Select value={resource} onChange={(e) => { setResource(e.target.value); setPage(1); }} className="h-8 w-56 text-xs"><option value="">All resources</option>{resources?.map((r: any) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select>
        <Input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} className="h-8 w-36 text-xs" aria-label="From date" />
        <Input type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} className="h-8 w-36 text-xs" aria-label="To date" />
        {can("audit:export") && <Button size="sm" variant="outline" asChild className="ml-auto"><a href={`/api/audit/export.csv?${exportParams}`}><Download />Export CSV</a></Button>}
      </div>
      <Card>
        {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading && !data ? <LoadingRows /> : !data.events.length ? <EmptyState title="No events match" /> : (
          <>
            <Table>
              <THead><TR><TH className="w-8" /><TH>#</TH><TH>Time</TH><TH>Actor</TH><TH>Action</TH><TH>Resource</TH><TH>Target</TH><TH>Hash</TH></TR></THead>
              <TBody>
                {data.events.map((e: any) => (
                  <Fragment key={e.seq}>
                    <TR className="cursor-pointer" onClick={() => setOpen(open === e.seq ? null : e.seq)}>
                      <TD>{open === e.seq ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}</TD>
                      <TD className="font-mono text-xs text-muted-foreground tabular">{e.seq}</TD>
                      <TD className="whitespace-nowrap text-xs text-muted-foreground">{fmtDate(e.occurred_at)}</TD>
                      <TD className="whitespace-nowrap"><span className="font-medium">{e.actor_name}</span>{e.actor_type !== "USER" && <Badge tone={e.actor_type === "AGENT" ? "violet" : "outline"} className="ml-1.5">{e.actor_type}</Badge>}</TD>
                      <TD><Mono className={cn(e.action.includes("DENIED") || e.action.includes("VIOLATION") ? "text-critical" : e.action.includes("BREAKGLASS") ? "text-serious" : "")}>{e.action}</Mono></TD>
                      <TD className="whitespace-nowrap text-xs">{e.resource || "—"}</TD>
                      <TD className="max-w-[160px] truncate font-mono text-2xs text-muted-foreground">{e.target_id || "—"}</TD>
                      <TD><Mono className="text-2xs text-muted-foreground">{e.hash.slice(0, 10)}…</Mono></TD>
                    </TR>
                    {open === e.seq && (
                      <tr className="bg-muted/30"><td colSpan={8} className="px-4 py-3">
                        <div className="grid gap-3 text-xs md:grid-cols-2">
                          <div className="space-y-1">
                            <div><span className="text-muted-foreground">Actor role:</span> {e.actor_role || "—"}</div>
                            <div><span className="text-muted-foreground">Request:</span> <Mono>{e.request_id || "—"}</Mono></div>
                            <div><span className="text-muted-foreground">Reason:</span> {e.reason || "—"}</div>
                            <div><span className="text-muted-foreground">IP / device:</span> <Mono>{e.ip || "—"}</Mono> {e.user_agent && <span className="text-muted-foreground">· {e.user_agent}</span>}</div>
                            <div className="pt-1"><span className="text-muted-foreground">Previous hash:</span> <Mono className="break-all text-2xs">{e.prev_hash}</Mono></div>
                            <div><span className="text-muted-foreground">Event hash:</span> <Mono className="break-all text-2xs">{e.hash}</Mono></div>
                          </div>
                          <div className="grid gap-2 sm:grid-cols-2">
                            <div><div className="mb-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Previous state</div><pre className="max-h-40 overflow-auto rounded bg-card p-2 font-mono text-2xs hairline scroll-thin">{e.previous_state ? JSON.stringify(e.previous_state, null, 2) : "—"}</pre></div>
                            <div><div className="mb-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground">New state</div><pre className="max-h-40 overflow-auto rounded bg-card p-2 font-mono text-2xs hairline scroll-thin">{e.new_state ? JSON.stringify(e.new_state, null, 2) : "—"}</pre></div>
                          </div>
                        </div>
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </TBody>
            </Table>
            <div className="flex items-center justify-between border-t px-4 py-2.5 text-xs text-muted-foreground">
              <span className="tabular">{data.total.toLocaleString()} events</span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
                <span className="tabular">Page {page} of {Math.max(1, Math.ceil(data.total / data.page_size))}</span>
                <Button size="sm" variant="outline" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}

function Verify() {
  const { can } = useSession();
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setRes(await api("/api/audit/verify")); } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); } };
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <Card>
        <CardHeader title="Hash-chain verification" description="Recalculates every event's SHA-256 hash and checks each link to the previous event." action={can("audit:verify") && <Button variant="accent" onClick={run} loading={busy}><ShieldCheck />Verify chain</Button>} />
        <CardBody>
          {!res ? <EmptyState icon={Link2} title="Run a verification" description={can("audit:verify") ? "Takes a moment for large trails." : "Requires the Security Manager role."} /> : res.valid ? (
            <div className="flex items-start gap-3 rounded-lg border border-success/40 bg-success/5 p-4 animate-fade-in">
              <CheckCircle2 className="h-6 w-6 shrink-0 text-success" />
              <div><div className="text-sm font-semibold">Chain intact</div><p className="mt-0.5 text-xs text-muted-foreground">{res.checked.toLocaleString()} events verified · {fmtDate(res.verified_at)}</p><p className="mt-2 text-2xs text-muted-foreground">Head hash</p><Mono className="break-all text-2xs">{res.head_hash}</Mono></div>
            </div>
          ) : (
            <div className="flex items-start gap-3 rounded-lg border border-critical/40 bg-critical/5 p-4 animate-fade-in">
              <XCircle className="h-6 w-6 shrink-0 text-critical" />
              <div><div className="text-sm font-semibold text-critical">Tampering detected</div>
                <p className="mt-1 text-xs">First invalid event: <span className="font-mono font-semibold">#{res.first_invalid_seq}</span>{res.action && <> ({res.action})</>}</p>
                <p className="mt-0.5 text-xs">{res.problem}</p>
                <p className="mt-1 text-2xs text-muted-foreground">{res.checked.toLocaleString()} events verified before the break.</p></div>
            </div>
          )}
        </CardBody>
      </Card>
      <Card className="h-fit p-4 text-xs text-muted-foreground">
        <div className="mb-2 text-[13px] font-medium text-foreground">How this works</div>
        <p>Each event stores the hash of the event before it. Its own hash covers every field (actor, action, states, reason, IP) plus that previous hash.</p>
        <p className="mt-2">Editing, deleting or reordering any historical record changes its hash and breaks every link after it, so verification pinpoints the first altered record.</p>
        <p className="mt-2 font-medium text-foreground">This makes unauthorized modification detectable. It does not make the database itself immutable; pair it with WORM storage or external anchoring for that.</p>
      </Card>
    </div>
  );
}

function Alerts() {
  const { can } = useSession();
  const [status, setStatus] = useState("OPEN");
  const { data, error, isLoading, mutate } = useSWR(`/api/alerts?${status ? `status=${status}` : ""}`, fetcher, { refreshInterval: 20000 });
  const set = async (id: string, s: string, resolution?: string) => {
    try { await api(`/api/alerts/${id}/status`, { json: { status: s, resolution } }); mutate(); if (resolution) toast.success(resolution === "CONFIRMED" ? "Marked as a confirmed violation. It now counts in this person's risk history." : "Marked as a false positive. It will not affect anyone's risk score."); }
    catch (e) { toast.error(errorMessage(e)); }
  };
  return (
    <>
      <div className="mb-3"><Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 w-44 text-xs"><option value="OPEN">Open</option><option value="ACKNOWLEDGED">Acknowledged</option><option value="RESOLVED">Resolved</option><option value="">All</option></Select></div>
      <Card>
        {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading ? <LoadingRows /> : !data.length ? <EmptyState icon={ShieldCheck} title="No alerts" /> : (
          <Table>
            <THead><TR><TH>Severity</TH><TH>Alert</TH><TH>Category</TH><TH>Subject</TH><TH>Raised</TH><TH>Status</TH><TH /></TR></THead>
            <TBody>{data.map((a: any) => (
              <TR key={a.id}>
                <TD><SeverityBadge severity={a.severity} /></TD>
                <TD className="max-w-[380px]"><div className="font-medium">{a.title}</div><div className="text-xs text-muted-foreground">{a.description}</div></TD>
                <TD><Badge tone="outline">{titleCase(a.category)}</Badge></TD>
                <TD className="whitespace-nowrap text-xs">{a.user?.name || a.agent || "—"}{a.resource && <div className="text-2xs text-muted-foreground">{a.resource.name}</div>}</TD>
                <TD className="whitespace-nowrap text-xs text-muted-foreground">{relTime(a.created_at)}</TD>
                <TD><StatusBadge status={a.status} />{a.resolution && <div className="mt-1"><Badge tone={a.resolution === "CONFIRMED" ? "critical" : "neutral"}>{a.resolution === "CONFIRMED" ? "Confirmed" : "False positive"}</Badge></div>}</TD>
                <TD>{can("alerts:manage") && a.status !== "RESOLVED" && <div className="flex flex-wrap justify-end gap-1">
                  {a.status === "OPEN" && <Button size="sm" variant="ghost" onClick={() => set(a.id, "ACKNOWLEDGED")}>Ack</Button>}
                  <Button size="sm" variant="outline" className="text-critical" title="A real violation: counts in the person's risk history" onClick={() => set(a.id, "RESOLVED", "CONFIRMED")}>Confirm</Button>
                  <Button size="sm" variant="outline" title="Not a real problem: never counts against anyone" onClick={() => set(a.id, "RESOLVED", "FALSE_POSITIVE")}>False positive</Button></div>}</TD>
              </TR>))}</TBody>
          </Table>
        )}
      </Card>
    </>
  );
}

function Inner() {
  const { can, loading } = useSession();
  const tab = useSearchParams().get("tab") || (can("audit:read") ? "events" : "alerts");
  const header = <PageHeader title="Audit & Compliance" description="Tamper-evident record of every important action, plus security alerts raised by the platform." />;
  if (loading) return <>{header}<Card><LoadingRows /></Card></>;
  if (!can("audit:read") && !can("alerts:read")) return <>{header}<Card><ErrorState error={{ status: 403 }} /></Card></>;
  return (
    <>
      <PageHeader title="Audit & Compliance" description="Tamper-evident record of every important action, plus security alerts raised by the platform." />
      <Tabs defaultValue={tab}>
        <TabsList>
          {can("audit:read") && <TabsTrigger value="events">Audit trail</TabsTrigger>}
          {can("audit:read") && <TabsTrigger value="verify"><ShieldX className="h-3.5 w-3.5" />Integrity</TabsTrigger>}
          {can("alerts:read") && <TabsTrigger value="alerts">Security alerts</TabsTrigger>}
        </TabsList>
        <TabsContent value="events"><Events /></TabsContent>
        <TabsContent value="verify"><Verify /></TabsContent>
        <TabsContent value="alerts"><Alerts /></TabsContent>
      </Tabs>
    </>
  );
}

export default function AuditPage() { return <Suspense><Inner /></Suspense>; }
