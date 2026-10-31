"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Activity, ClipboardList, Copy, OctagonX, Siren, Timer } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn, duration, fmtDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingRows, Mono, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { BreakGlassBadge, Perms, StatusBadge } from "@/components/status";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function Live({ expires }: { expires: string }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  const s = Math.floor((new Date(expires).getTime() - Date.now()) / 1000);
  return <span className={cn("inline-flex items-center gap-1 font-mono text-xs tabular", s < 600 ? "text-critical" : "text-warning")}><Timer className="h-3.5 w-3.5" />{duration(s)}</span>;
}

function Activate({ resources, onDone }: { resources: any[]; onDone: () => void }) {
  const [rid, setRid] = useState(resources[0]?.id || "");
  const res = resources.find((r) => r.id === rid);
  const [perms, setPerms] = useState<string[]>(["READ"]);
  const [inc, setInc] = useState("INC-");
  const [why, setWhy] = useState("");
  const [mins, setMins] = useState(60);
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const go = async () => {
    setBusy(true);
    try {
      const r = await api("/api/emergency", { json: { resource_id: rid, permissions: perms, incident_ref: inc, justification: why, duration_minutes: mins } });
      setToken(r.token); toast.error("BREAK-GLASS activated. Security has been notified."); onDone();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  return (
    <Card className="overflow-hidden border-critical/40">
      <div className="flex items-center gap-2 border-b border-critical/30 bg-critical/[0.06] px-4 py-3">
        <Siren className="h-4 w-4 text-critical" /><span className="text-[13px] font-semibold uppercase tracking-wider text-critical">Break-glass access</span>
      </div>
      <CardBody className="space-y-4 pt-4">
        <p className="text-xs text-muted-foreground">For production incidents only. Access starts immediately, is fully monitored, expires automatically and requires a post-incident review. Misuse is a policy violation.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Resource"><Select value={rid} onChange={(e) => setRid(e.target.value)}>{resources.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select></Field>
          <Field label="Incident reference"><Input value={inc} onChange={(e) => setInc(e.target.value.toUpperCase())} placeholder="INC-12345" className="font-mono" /></Field>
          <Field label="Duration"><Select value={mins} onChange={(e) => setMins(Number(e.target.value))}>{[15, 30, 60, 90, 120, 240].map((m) => <option key={m} value={m}>{m} minutes</option>)}</Select></Field>
          <Field label="Elevated permissions"><div className="flex flex-wrap gap-1.5 pt-1">{res?.available_permissions.map((p: string) => { const on = perms.includes(p); return (
            <button key={p} type="button" onClick={() => setPerms(on ? perms.filter((x) => x !== p) : [...perms, p])} className={cn("rounded-md border px-2 py-1 font-mono text-xs", on ? "border-critical bg-critical/10 text-critical" : "text-muted-foreground")}>{p}</button>); })}</div></Field>
        </div>
        <Field label="Mandatory justification" hint="At least 30 characters. Describe the outage and exactly what you need to do."><Textarea value={why} onChange={(e) => setWhy(e.target.value)} /></Field>
        <div className="flex justify-end"><Button variant="destructive" loading={busy} onClick={go} disabled={why.trim().length < 30 || !/^INC-\d{3,8}$/.test(inc) || !perms.length}><Siren />Activate break-glass</Button></div>
        {token && (
          <div className="rounded-md border border-critical/40 bg-[#0b0d14] p-3 text-white animate-fade-in">
            <div className="flex items-center justify-between text-2xs uppercase tracking-wider text-white/50">Emergency token · monitored<button onClick={() => { navigator.clipboard.writeText(token); toast.success("Copied"); }}><Copy className="h-3.5 w-3.5" /></button></div>
            <div className="mt-1 break-all font-mono text-xs">{token}</div>
            <p className="mt-1 text-2xs text-white/50">Use purpose INCIDENT_RESPONSE at the resource gateway (Active Access → Token).</p>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function ActionsDialog({ s, onClose }: { s: any; onClose: () => void }) {
  const { data } = useSWR(`/api/emergency/${s.id}/actions`, fetcher, { refreshInterval: 5000 });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`Activity · ${s.ref}`} description={`${s.user.name} on ${s.resource.name}`} wide>
        {!data ? <LoadingRows rows={3} /> : !data.length ? <EmptyState title="No actions yet" /> : (
          <Table><THead><TR><TH>When</TH><TH>Action</TH><TH>Outcome</TH><TH>IP</TH></TR></THead>
            <TBody>{data.map((a: any, i: number) => <TR key={i}><TD className="text-muted-foreground">{fmtDate(a.at)}</TD><TD className="font-mono text-xs">{a.action}</TD><TD><StatusBadge status={a.outcome} /></TD><TD className="font-mono text-xs text-muted-foreground">{a.ip}</TD></TR>)}</TBody></Table>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function Emergency() {
  const { can, me } = useSession();
  const monitor = can("emergency:monitor");
  const { data, error, isLoading, mutate } = useSWR(`/api/emergency?scope=${monitor ? "all" : "mine"}`, fetcher, { refreshInterval: 10000 });
  const [actions, setActions] = useState<any>(null);
  const [revoke, setRevoke] = useState<any>(null);
  const [review, setReview] = useState<any>(null);
  const [text, setText] = useState("");
  const [outcome, setOutcome] = useState("JUSTIFIED");
  const doRevoke = async () => { try { await api(`/api/emergency/${revoke.id}/revoke`, { json: { reason: text || "Revoked by security" } }); toast.success("Session revoked; token invalidated"); setRevoke(null); setText(""); mutate(); } catch (e) { toast.error(errorMessage(e)); } };
  const doReview = async () => { try { await api(`/api/emergency/${review.id}/review`, { json: { outcome, notes: text } }); toast.success("Post-incident review recorded"); setReview(null); setText(""); mutate(); } catch (e) { toast.error(errorMessage(e)); } };
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (isLoading) return <LoadingRows />;
  const active = data.sessions.filter((s: any) => s.status === "ACTIVE");
  const past = data.sessions.filter((s: any) => s.status !== "ACTIVE");
  return (
    <>
      <PageHeader title="Emergency Access Center" description="Break-glass access for outages: immediate, short-lived, loudly announced and fully audited." />
      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <div className="space-y-4">
          <Card>
            <CardHeader title={<span className="inline-flex items-center gap-2"><span className={cn("h-2 w-2 rounded-full", active.length ? "bg-critical animate-pulse2" : "bg-success")} />Active emergency sessions</span>} description={monitor ? "Organisation-wide live monitoring" : "Your sessions"} />
            {!active.length ? <EmptyState icon={Siren} title="No active break-glass sessions" /> : (
              <Table>
                <THead><TR><TH>Session</TH><TH>Employee</TH><TH>Resource</TH><TH>Reason</TH><TH>Started</TH><TH>Remaining</TH><TH className="text-right">Actions</TH><TH /></TR></THead>
                <TBody>{active.map((s: any) => (
                  <TR key={s.id} className="bg-critical/[0.03]">
                    <TD><BreakGlassBadge /><div className="mt-1 font-mono text-2xs text-muted-foreground">{s.ref} · {s.incident_ref}</div></TD>
                    <TD className="whitespace-nowrap font-medium">{s.user.name}<div className="text-2xs font-normal text-muted-foreground">{s.user.department}</div></TD>
                    <TD><div className="whitespace-nowrap">{s.resource.name}</div><Perms perms={s.permissions} /></TD>
                    <TD className="max-w-[240px] text-xs text-muted-foreground">{s.justification}</TD>
                    <TD className="whitespace-nowrap text-xs text-muted-foreground">{fmtDate(s.started_at)}</TD>
                    <TD><Live expires={s.expires_at} /></TD>
                    <TD className="text-right"><button onClick={() => setActions(s)} className="inline-flex items-center gap-1 text-xs text-violet hover:underline"><Activity className="h-3.5 w-3.5" />{s.actions_performed}</button></TD>
                    <TD>{(monitor || s.user.id === me?.id) && <Button size="sm" variant="destructive" onClick={() => setRevoke(s)}><OctagonX />Revoke</Button>}</TD>
                  </TR>))}</TBody>
              </Table>
            )}
          </Card>
          <Card>
            <CardHeader title="History & post-incident reviews" />
            {!past.length ? <EmptyState title="No past sessions" /> : (
              <Table>
                <THead><TR><TH>Session</TH><TH>Employee</TH><TH>Resource</TH><TH>Window</TH><TH>Actions</TH><TH>Status</TH><TH>Review</TH></TR></THead>
                <TBody>{past.map((s: any) => (
                  <TR key={s.id}>
                    <TD className="font-mono text-xs">{s.ref}<div className="text-2xs text-muted-foreground">{s.incident_ref}</div></TD>
                    <TD className="whitespace-nowrap">{s.user.name}</TD>
                    <TD className="whitespace-nowrap">{s.resource.name}</TD>
                    <TD className="whitespace-nowrap text-xs text-muted-foreground">{fmtDate(s.started_at)} → {fmtDate(s.ended_at)}</TD>
                    <TD><button onClick={() => setActions(s)} className="text-xs text-violet hover:underline tabular">{s.actions_performed}</button></TD>
                    <TD><StatusBadge status={s.status} /></TD>
                    <TD>{s.review_status === "COMPLETED" ? <Badge tone={s.review_outcome === "MISUSE" ? "critical" : s.review_outcome === "JUSTIFIED" ? "success" : "warning"}>{s.review_outcome}</Badge>
                      : can("emergency:review") && s.user.id !== me?.id ? <Button size="sm" variant="outline" onClick={() => setReview(s)}><ClipboardList />Review</Button> : <Badge tone="warning">Pending review</Badge>}</TD>
                  </TR>))}</TBody>
              </Table>
            )}
          </Card>
        </div>
        <div>
          {data.user_eligible ? <Activate resources={data.eligible_resources} onDone={() => mutate()} /> : (
            <Card className="p-4 text-xs text-muted-foreground"><div className="mb-1 flex items-center gap-1.5 text-[13px] font-medium text-foreground"><Siren className="h-4 w-4" />Break-glass eligibility</div>Only on-call Engineering and Security staff can activate break-glass access. Use a normal access request instead.</Card>
          )}
        </div>
      </div>
      {actions && <ActionsDialog s={actions} onClose={() => setActions(null)} />}
      <Dialog open={!!revoke} onOpenChange={(o) => !o && setRevoke(null)}>
        {revoke && <DialogContent title={`Revoke ${revoke.ref}`} description="Ends the session and invalidates the emergency token immediately.">
          <div className="space-y-4"><Field label="Reason"><Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Incident resolved" /></Field><div className="flex justify-end"><Button variant="destructive" onClick={doRevoke}>Revoke now</Button></div></div>
        </DialogContent>}
      </Dialog>
      <Dialog open={!!review} onOpenChange={(o) => !o && setReview(null)}>
        {review && <DialogContent title={`Post-incident review · ${review.ref}`} description={review.justification}>
          <div className="space-y-4">
            <Field label="Outcome"><Select value={outcome} onChange={(e) => setOutcome(e.target.value)}><option value="JUSTIFIED">Justified</option><option value="INCONCLUSIVE">Inconclusive</option><option value="MISUSE">Misuse</option></Select></Field>
            <Field label="Review notes"><Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Were all actions within the incident scope?" /></Field>
            <div className="flex justify-end"><Button onClick={doReview} disabled={text.length < 10}>Submit review</Button></div>
          </div>
        </DialogContent>}
      </Dialog>
    </>
  );
}
