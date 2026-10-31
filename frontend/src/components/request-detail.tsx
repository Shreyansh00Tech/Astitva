"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowLeft, Ban, Brain, CheckCircle2, CircleSlash, Clock, FileEdit, Scissors, ShieldAlert, ShieldCheck, ShieldX, Sparkles, User, XCircle,
} from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn, fmtDate, hours, titleCase } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Avatar, ErrorState, KV, Skeleton } from "@/components/ui/misc";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Perms, PriorityBadge, RiskBadge, RiskMeter, SensitivityBadge, STAGE_LABEL, StatusBadge } from "@/components/status";
import { AreaSeries } from "@/components/charts";
import { ApprovalStepper, STEP_LABEL } from "@/components/stepper";
import { ManageAccessDialog } from "@/components/manage-access";

const ACTION_META: Record<string, { label: string; icon: any; tone: string }> = {
  APPROVE: { label: "Approved", icon: CheckCircle2, tone: "text-success" },
  NARROW_SCOPE: { label: "Narrowed scope & approved", icon: Scissors, tone: "text-warning" },
  REJECT: { label: "Rejected", icon: XCircle, tone: "text-critical" },
  REQUEST_MODIFICATION: { label: "Requested modification", icon: FileEdit, tone: "text-info" },
};

function ActionPanel({ r, onDone }: { r: any; onDone: () => void }) {
  const [mode, setMode] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [perms, setPerms] = useState<string[]>(r.risk?.recommended_permissions?.filter((p: string) => r.approved_permissions.includes(p)) || r.approved_permissions);
  const [dur, setDur] = useState<number>(Math.min(r.approved_duration_hours, r.risk?.recommended_duration_hours || r.approved_duration_hours));
  const [busy, setBusy] = useState(false);
  const run = async (action: string) => {
    setBusy(true);
    try {
      const body: any = { action, comment: comment || undefined };
      if (action === "NARROW_SCOPE") { body.permissions = perms; body.duration_hours = dur; }
      await api(`/api/approvals/${r.id}/action`, { json: body });
      toast.success(`${titleCase(action)} recorded for ${r.ref}`);
      setMode(null); setComment(""); onDone();
    } catch (e) { toast.error(errorMessage(e)); onDone(); } finally { setBusy(false); }
  };
  return (
    <Card className="border-violet/30">
      <CardHeader title={`Your decision · ${STAGE_LABEL[r.current_stage]}`} description="Every action is recorded on the hash-chained audit trail." />
      <CardBody className="space-y-3">
        {!mode && (
          <div className="grid grid-cols-2 gap-2">
            <Button variant="success" onClick={() => run("APPROVE")} loading={busy}><CheckCircle2 />Approve</Button>
            <Button variant="outline" onClick={() => setMode("NARROW_SCOPE")}><Scissors />Narrow scope</Button>
            <Button variant="outline" onClick={() => setMode("REQUEST_MODIFICATION")}><FileEdit />Request changes</Button>
            <Button variant="outline" className="text-critical hover:text-critical" onClick={() => setMode("REJECT")}><XCircle />Reject</Button>
          </div>
        )}
        {mode === "NARROW_SCOPE" && (
          <div className="space-y-3 animate-fade-in">
            <Field label="Keep permissions" hint="Must be a subset of the current scope.">
              <div className="flex flex-wrap gap-1.5">
                {r.approved_permissions.map((p: string) => { const on = perms.includes(p); return (
                  <button key={p} type="button" onClick={() => setPerms(on ? perms.filter((x) => x !== p) : [...perms, p])}
                    className={cn("rounded-md border px-2.5 py-1 font-mono text-xs", on ? "border-violet bg-violet/10 text-violet" : "text-muted-foreground line-through")}>{p}</button>); })}
              </div>
            </Field>
            <Field label="Duration">
              <Select value={dur} onChange={(e) => setDur(Number(e.target.value))}>
                {[1, 4, 8, 12, 24, 48, 72, 168, 336, 720].filter((h) => h <= r.approved_duration_hours).map((h) => <option key={h} value={h}>{hours(h)}</option>)}
              </Select>
            </Field>
          </div>
        )}
        {mode && (
          <>
            <Field label={mode === "NARROW_SCOPE" ? "Comment (optional)" : "Comment (required)"}>
              <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder={mode === "REJECT" ? "Why is this request rejected?" : "Explain to the requester…"} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setMode(null)}>Back</Button>
              <Button variant={mode === "REJECT" ? "destructive" : "default"} loading={busy} onClick={() => run(mode)}
                disabled={(mode !== "NARROW_SCOPE" && !comment.trim()) || (mode === "NARROW_SCOPE" && !perms.length)}>
                Confirm {titleCase(mode).toLowerCase()}
              </Button>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function IntelligencePanel({ id }: { id: string }) {
  const { data, error } = useSWR(`/api/approvals/${id}/context`, fetcher);
  if (error) return null;
  if (!data) return <Skeleton className="h-72" />;
  const w = data.work, s = data.security;
  return (
    <Card>
      <CardHeader title="Employee intelligence" description="Recorded work and security history. Informational only."
        action={<Link href={`/employees/${data.employee.id}`} className="text-2xs text-violet hover:underline">Full profile</Link>} />
      <CardBody className="space-y-4">
        <div className="flex items-center gap-3">
          <Avatar name={data.employee.name} className="h-9 w-9 text-xs" />
          <div><div className="text-[13px] font-medium">{data.employee.name}</div><div className="text-2xs text-muted-foreground">{data.employee.designation} · {data.employee.department} · {data.employee.employee_id}</div></div>
        </div>
        <div>
          <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Work performance</div>
          <div className="grid grid-cols-2 gap-x-4">
            <KV k="Verified tasks" v={w.verified_tasks} /><KV k="Assigned projects" v={w.assigned_projects} />
            <KV k="On-time delivery" v={`${Math.round(w.on_time_rate * 100)}%`} /><KV k="Avg quality" v={`${w.avg_quality} / 5`} />
            <KV k="Successful operations" v={w.successful_operations} /><KV k="30-day activity" v={<Badge tone={w.activity_level_30d === "High" ? "success" : w.activity_level_30d === "Low" ? "warning" : "neutral"}>{w.activity_level_30d}</Badge>} />
          </div>
        </div>
        <div>
          <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Security posture</div>
          <div className="grid grid-cols-2 gap-x-4">
            <KV k="Policy violations" v={<span className={s.policy_violations ? "text-critical" : ""}>{s.policy_violations}</span>} />
            <KV k="Active grants" v={s.active_grants} />
            <KV k="Denied operations" v={s.denied_operations} />
            <KV k="Device trust" v={titleCase(data.employee.device_trust)} />
          </div>
        </div>
        <div className="rounded-md bg-muted/50 p-2.5">
          <div className="flex items-center gap-1.5 text-xs font-medium"><ShieldCheck className="h-3.5 w-3.5 text-violet" />Recommended access</div>
          <div className="mt-1.5 flex items-center gap-2"><Perms perms={data.recommendation.permissions} /><span className="text-xs text-muted-foreground">for {hours(data.recommendation.duration_hours)}</span></div>
          <p className="mt-1.5 text-2xs text-muted-foreground">{data.recommendation.basis}</p>
        </div>
        <div>
          <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Weekly productivity (verified completions)</div>
          <AreaSeries data={data.weekly_productivity} x="week" y="completed" height={110} colorKey="series-3" />
        </div>
      </CardBody>
    </Card>
  );
}

const IMPACTS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
function toLocalInput(v?: string | null) {
  if (!v) return "";
  const d = new Date(v);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function PriorityCard({ r, mine, onDone }: { r: any; mine: boolean; onDone: () => void }) {
  const p = r.priority;
  const [edit, setEdit] = useState(false);
  const [deadline, setDeadline] = useState(toLocalInput(r.deadline_at));
  const [impact, setImpact] = useState(r.business_impact || "MEDIUM");
  const [busy, setBusy] = useState(false);
  if (!p) return null;
  const save = async () => {
    setBusy(true);
    try {
      await api(`/api/requests/${r.id}/priority-inputs`, { method: "PATCH", json: { deadline_at: deadline ? new Date(deadline).toISOString() : null, business_impact: impact } });
      toast.success("Deadline and impact updated"); setEdit(false); onDone();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  const bar = { LOW: "bg-success", MEDIUM: "bg-warning", HIGH: "bg-serious", CRITICAL: "bg-critical" }[p.level as string] || "bg-success";
  const parts: [string, string, number][] = [["Deadline", "deadline", 0.4], ["Impact", "impact", 0.3], ["Waiting", "waiting", 0.2], ["Urgency", "urgency", 0.1]];
  return (
    <Card className={cn(p.overdue && "border-critical/40")}>
      <CardHeader title={<span className="inline-flex items-center gap-1.5"><Clock className="h-4 w-4 text-violet" />Review priority</span>}
        description="Sets the order reviewers see requests in. It never changes the risk score or who must approve."
        action={mine && !edit ? <Button size="sm" variant="ghost" onClick={() => setEdit(true)}>Edit</Button> : undefined} />
      <CardBody className="space-y-3">
        <div className="flex items-center gap-3">
          <span className="text-3xl font-semibold tabular tracking-tight">{p.score}</span>
          <PriorityBadge p={p} hideScore />
        </div>
        <div className="flex h-1.5 overflow-hidden rounded-full bg-muted">
          <div className={cn("h-full rounded-full transition-[width] duration-700 ease-out", bar)} style={{ width: `${p.score}%` }} />
        </div>
        <div className="grid grid-cols-4 gap-1.5 text-center">
          {parts.map(([label, k, w]) => (
            <div key={k} className="rounded-md bg-muted/50 px-1 py-1.5">
              <div className="text-2xs text-muted-foreground">{label}</div>
              <div className="text-xs font-medium tabular">+{Math.round(p.components[k] * w)}</div>
            </div>
          ))}
        </div>
        <ul className="space-y-1 text-xs text-muted-foreground">{p.reasons.map((x: string) => <li key={x}>• {x}</li>)}</ul>
        <div className="grid grid-cols-2 gap-x-4 border-t pt-2">
          <KV k="Needed by" v={r.deadline_at ? fmtDate(r.deadline_at) : "No deadline"} />
          <KV k="Business impact" v={titleCase(r.business_impact || "MEDIUM")} />
        </div>
        {edit && (
          <div className="space-y-3 border-t pt-3 animate-fade-in">
            <Field label="Needed by (your local time)"><Input type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} /></Field>
            <Field label="Business impact">
              <div className="grid grid-cols-4 gap-1 rounded-lg border bg-muted/40 p-1">
                {IMPACTS.map((i) => <button key={i} type="button" onClick={() => setImpact(i)} className={cn("rounded-md py-1.5 text-2xs font-medium transition-all", impact === i ? "bg-card shadow-sm ring-1 ring-border" : "text-muted-foreground")}>{titleCase(i)}</button>)}
              </div>
            </Field>
            <div className="flex justify-end gap-2"><Button size="sm" variant="ghost" onClick={() => setEdit(false)}>Cancel</Button><Button size="sm" onClick={save} loading={busy}>Save</Button></div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export function RequestDetail({ id, backHref, backLabel }: { id: string; backHref: string; backLabel: string }) {
  const { me, can } = useSession();
  const { data: r, error, mutate } = useSWR(`/api/requests/${id}`, fetcher);
  const [busy, setBusy] = useState(false);
  const [manage, setManage] = useState(false);
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (!r) return <div className="space-y-3"><Skeleton className="h-10 w-80" /><Skeleton className="h-16" /><div className="grid gap-4 lg:grid-cols-3"><Skeleton className="h-96 lg:col-span-2" /><Skeleton className="h-96" /></div></div>;
  const mine = r.requester.id === me?.id;
  const risk = r.risk;
  const cancel = async () => { setBusy(true); try { await api(`/api/requests/${r.id}/cancel`, { method: "POST" }); toast.success("Request cancelled"); mutate(); } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); } };
  const resubmit = async () => {
    setBusy(true);
    try {
      await api(`/api/requests/${r.id}/resubmit`, { json: { permissions: r.approved_permissions, purpose: r.purpose, duration_hours: r.approved_duration_hours, justification: (document.getElementById("resub") as HTMLTextAreaElement).value } });
      toast.success("Resubmitted for review"); mutate();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  return (
    <div className="animate-fade-in">
      <Link href={backHref} className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />{backLabel}</Link>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2"><h1 className="font-mono text-lg font-semibold">{r.ref}</h1><StatusBadge status={r.status} />{risk && <RiskBadge level={risk.level} score={risk.score} />}</div>
          <p className="mt-1 text-[13px] text-muted-foreground"><span className="text-foreground">{r.requester.name}</span> requests access to <span className="text-foreground">{r.resource.name}</span> for {r.purpose_label.toLowerCase()} · {fmtDate(r.created_at)}</p>
        </div>
        {mine && ["PENDING", "CHANGES_REQUESTED"].includes(r.status) && <Button variant="outline" onClick={cancel} loading={busy}><Ban />Cancel request</Button>}
      </div>
      <Card className="mb-4 px-4 pb-3 pt-4"><ApprovalStepper key={`${r.status}-${r.current_stage}-${r.access?.status}-${r.access?.permissions?.length}`} r={r} />
        {r.routing_reasons?.length > 0 ? (
          <div className="mt-3 border-t pt-3 text-xs text-muted-foreground">
            <div className="mb-1 flex items-center justify-center gap-1.5 font-medium text-foreground"><Sparkles className="h-3.5 w-3.5 text-violet" />Why this approval path</div>
            <ul className="mx-auto max-w-2xl space-y-0.5 text-center">{r.routing_reasons.map((x: string) => <li key={x}>{x}</li>)}</ul>
          </div>
        ) : r.auto_approved && <p className="mt-3 flex items-center justify-center gap-1.5 border-t pt-3 text-center text-xs text-muted-foreground"><Sparkles className="h-3.5 w-3.5 text-violet" />Auto-approved by policy: rule-based risk score {risk?.score ?? "–"}/100 is within the low-risk band. Logged on the audit trail and the reporting manager is notified.</p>}
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {mine && r.status === "CHANGES_REQUESTED" && (
            <Card className="border-info/40"><CardHeader title="Changes requested" description={r.approvals.at(-1)?.comment} />
              <CardBody className="space-y-3"><Textarea id="resub" defaultValue={r.justification} /><div className="flex justify-end"><Button onClick={resubmit} loading={busy}>Resubmit</Button></div></CardBody>
            </Card>
          )}
          <Card>
            <CardHeader title="Request" />
            <CardBody className="grid gap-x-8 sm:grid-cols-2">
              <div>
                <KV k="Resource" v={<span className="inline-flex items-center gap-2">{r.resource.name}</span>} />
                <KV k="Sensitivity" v={<SensitivityBadge level={r.resource.sensitivity} />} />
                <KV k="Purpose" v={r.purpose_label} />
              </div>
              <div>
                <KV k="Requested" v={<Perms perms={r.requested_permissions} />} />
                <KV k="Current scope" v={<Perms perms={r.approved_permissions} />} />
                <KV k="Duration" v={r.approved_duration_hours !== r.requested_duration_hours ? <span><s className="text-muted-foreground">{hours(r.requested_duration_hours)}</s> → {hours(r.approved_duration_hours)}</span> : hours(r.approved_duration_hours)} />
              </div>
              <div className="sm:col-span-2 mt-2 rounded-md bg-muted/40 p-3 text-[13px]"><div className="mb-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Business justification</div>{r.justification}</div>
            </CardBody>
          </Card>

          {risk && (
            <Card>
              <CardHeader title={<span className="inline-flex items-center gap-1.5"><Brain className="h-4 w-4 text-violet" />AI risk assessment</span>} description={`Engine: ${risk.engine} · ${fmtDate(risk.assessed_at)}`} />
              <CardBody className="space-y-5">
                <div className="grid gap-6 md:grid-cols-2">
                  <RiskMeter score={risk.score} level={risk.level} />
                  <div className="rounded-md border p-3">
                    <div className="text-2xs font-medium uppercase tracking-wider text-muted-foreground">Recommendation</div>
                    <div className="mt-2 flex items-center gap-2"><Perms perms={risk.recommended_permissions} /><span className="text-xs text-muted-foreground">for {hours(risk.recommended_duration_hours)}</span></div>
                    <div className="mt-2 text-[13px] font-medium">{titleCase(risk.recommended_action)}</div>
                  </div>
                </div>
                <div>
                  <div className="mb-2 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Risk factors</div>
                  <div className="divide-y rounded-md border">
                    {risk.factors.sort((a: any, b: any) => b.points - a.points).map((f: any) => (
                      <div key={f.code + f.detail} className={cn("flex items-start gap-3 px-3 py-2", f.available === false && "bg-muted/30")}>
                        <span className={cn("mt-0.5 w-9 shrink-0 text-right font-mono text-xs tabular", f.available === false ? "text-muted-foreground" : f.points > 0 ? "text-critical" : "text-success")}>{f.available === false ? "n/a" : f.points > 0 ? `+${f.points}` : f.points}</span>
                        <div><div className="text-[13px] font-medium">{f.label}</div><div className="text-xs text-muted-foreground">{f.detail}</div></div>
                      </div>
                    ))}
                  </div>
                </div>
                {risk.anomalies.length > 0 && (
                  <div>
                    <div className="mb-2 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Detected anomalies</div>
                    <ul className="space-y-1.5">{risk.anomalies.map((a: string) => <li key={a} className="flex gap-2 text-[13px]"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />{a}</li>)}</ul>
                  </div>
                )}
                <div className="flex gap-2 rounded-md bg-violet/[0.06] p-3 text-[13px]"><Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-violet" /><p>{risk.explanation}</p></div>
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader title="Approval history" />
            <CardBody>
              {!r.approvals.length ? <p className="text-xs text-muted-foreground">No decisions yet.</p> : (
                <ol className="relative space-y-4 border-l pl-5">
                  {r.approvals.map((a: any) => { const m = ACTION_META[a.action]; return (
                    <li key={a.id} className="relative">
                      <span className="absolute -left-[27px] top-0.5 rounded-full bg-card p-0.5"><m.icon className={cn("h-4 w-4", m.tone)} /></span>
                      <div className="text-[13px]"><span className="font-medium">{a.approver.name}</span> <span className="text-muted-foreground">· {STAGE_LABEL[a.stage]} ·</span> {m.label}</div>
                      {a.action === "NARROW_SCOPE" && <div className="mt-1 flex items-center gap-2 text-xs"><Perms perms={a.previous_scope.permissions} strike={a.previous_scope.permissions.filter((p: string) => !a.new_scope.permissions.includes(p))} /><span className="text-muted-foreground">{hours(a.previous_scope.duration_hours)} → {hours(a.new_scope.duration_hours)}</span></div>}
                      {a.comment && <p className="mt-1 text-xs text-muted-foreground">“{a.comment}”</p>}
                      <div className="text-2xs text-muted-foreground/80">{fmtDate(a.at)}</div>
                    </li>); })}
                </ol>
              )}
            </CardBody>
          </Card>
        </div>

        <div className="space-y-4">
          {r.can_act && <ActionPanel r={r} onDone={() => mutate()} />}
          <PriorityCard key={`${r.deadline_at}-${r.business_impact}`} r={r} mine={mine} onDone={() => mutate()} />
          {r.blocked_reason && (
            <Card className="border-warning/40 bg-warning/[0.04] p-4">
              <div className="flex items-center gap-2 text-[13px] font-medium"><CircleSlash className="h-4 w-4 text-warning" />Separation of duties</div>
              <p className="mt-1 text-xs text-muted-foreground">{r.blocked_reason.message}</p>
              <Badge tone="warning" className="mt-2 font-mono">{r.blocked_reason.rule}</Badge>
            </Card>
          )}
          {r.status === "PENDING" && (
            <Card>
              <CardHeader title="Waiting on" description={STEP_LABEL[r.current_stage] || STAGE_LABEL[r.current_stage]} />
              <CardBody className="space-y-2">
                {r.stage_approvers.map((u: any) => <div key={u.id} className="flex items-center gap-2 text-[13px]"><Avatar name={u.name} className="h-6 w-6" />{u.name}<span className="text-2xs text-muted-foreground">{u.designation}</span></div>)}
                {!r.stage_approvers.length && <p className="text-xs text-muted-foreground">No eligible approver available.</p>}
              </CardBody>
            </Card>
          )}
          {can("approvals:read") && !mine && <IntelligencePanel id={r.id} />}
          {r.status === "APPROVED" && r.access?.status === "ACTIVE" && (
            <Card className="p-4"><div className="flex items-center gap-2 text-[13px] font-medium"><ShieldCheck className="h-4 w-4 text-success" />Access is active</div>
              <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">Current permissions <Perms perms={r.access.permissions} /></div>
              {mine && <p className="mt-2 text-xs text-muted-foreground">Your purpose-bound token is available in Active Access.</p>}
              <div className="mt-3 flex flex-wrap gap-2">
                {mine && <Button asChild size="sm" variant="outline"><Link href="/active-access">View token</Link></Button>}
                {r.can_manage_access && <Button size="sm" variant="outline" className="text-critical" onClick={() => setManage(true)}><ShieldX />{mine ? "Remove my access" : "Remove permissions / revoke"}</Button>}
              </div>
            </Card>
          )}
          {r.status === "APPROVED" && r.access && r.access.status !== "ACTIVE" && (
            <Card className="p-4"><div className="flex items-center gap-2 text-[13px] font-medium"><ShieldX className={cn("h-4 w-4", r.access.status === "REVOKED" ? "text-critical" : "text-muted-foreground")} />Access {r.access.status.toLowerCase()}</div>
              <p className="mt-1 text-xs text-muted-foreground">
                {r.access.status === "REVOKED" ? <>Revoked{r.access.revoked_by ? ` by ${r.access.revoked_by.name}` : ""} · {fmtDate(r.access.revoked_at)}{r.access.revoke_reason ? <> · “{r.access.revoke_reason}”</> : null}</> : <>Expired {fmtDate(r.access.expires_at)}</>}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">The token no longer works. A new request is needed to get access again.</p>
            </Card>
          )}
          {manage && r.access && <ManageAccessDialog self={mine} grant={{ id: r.access.grant_id, permissions: r.access.permissions, userName: r.requester.name, resourceName: r.resource.name }}
            onClose={() => setManage(false)} onDone={() => { setManage(false); mutate(); }} />}
        </div>
      </div>
    </div>
  );
}
