"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { Gavel, Scale, ShieldCheck, Sparkles, Workflow } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn, fmtDate, relTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/misc";
import { Field, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Perms, RiskBadge, SensitivityBadge } from "@/components/status";
import { BAND, Delta, FINAL_VERDICT, VERDICT } from "@/components/agent-graph";

const risk = (v: number) => (v <= 30 ? "Low" : v <= 60 ? "Medium" : v <= 80 ? "High" : "Critical");

export function AgentDots({ agents }: { agents: any[] }) {
  return (
    <span className="inline-flex items-center gap-1">
      {agents.map((a) => <span key={a.code} title={`${a.name}: ${VERDICT[a.verdict]?.label || a.verdict} (${a.delta > 0 ? "+" : ""}${a.delta})`}
        className={cn("h-2 w-2 rounded-full", VERDICT[a.verdict]?.dot || "bg-muted")} />)}
    </span>
  );
}

function QueueTable({ rows, empty }: { rows: any[]; empty: string }) {
  const router = useRouter();
  if (!rows.length) return <EmptyState icon={Workflow} title={empty} description="Each new access request is reviewed by the agents next to the rule engine." />;
  return (
    <Table>
      <THead><TR><TH>Request</TH><TH>Requester</TH><TH>Resource</TH><TH>Scope</TH><TH>Rule</TH><TH>AI</TH><TH>Agents</TH><TH>Verdict</TH><TH>Final</TH><TH>Age</TH></TR></THead>
      <TBody>
        {rows.map((x) => { const r = x.request; const fv = FINAL_VERDICT[x.verdict] || FINAL_VERDICT.APPROVE; return (
          <TR key={x.request_id} className="cursor-pointer" onClick={() => router.push(`/agent-review/${x.request_id}`)}>
            <TD><span className="font-mono text-xs font-medium text-violet">{r.ref}</span></TD>
            <TD><div className="whitespace-nowrap font-medium">{r.requester.name}</div><div className="text-2xs text-muted-foreground">{r.requester.department}</div></TD>
            <TD><div className="whitespace-nowrap">{r.resource.name}</div><SensitivityBadge level={r.resource.sensitivity} /></TD>
            <TD><Perms perms={r.approved_permissions} /></TD>
            <TD className="font-mono tabular">{x.rule_score}</TD>
            <TD className="font-mono tabular"><span className={cn(x.ai_score > x.rule_score ? "text-critical" : x.ai_score < x.rule_score ? "text-success" : "")}>{x.ai_score}</span></TD>
            <TD><AgentDots agents={x.agents} /></TD>
            <TD><Badge tone={fv.tone}><fv.icon />{fv.label}</Badge></TD>
            <TD>{x.status === "AWAITING_CHOICE" ? <Badge tone="warning">Choose</Badge> : <span className="text-xs"><span className="font-mono font-medium">{x.final_score}</span> <span className="text-muted-foreground">· {x.chosen === "AUTO" ? "auto" : x.chosen?.toLowerCase()}</span></span>}</TD>
            <TD className="whitespace-nowrap text-muted-foreground">{relTime(x.created_at)}</TD>
          </TR>); })}
      </TBody>
    </Table>
  );
}

export function AgentReviewQueue() {
  const { data, error, isLoading, mutate } = useSWR("/api/agent-review/queue", fetcher, { refreshInterval: 20000 });
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (isLoading || !data) return <LoadingRows />;
  return (
    <div className="space-y-4">
      <HowItWorks />
      <div>
        <div className="mb-2 flex items-center gap-2 text-[13px] font-medium">Needs your score <Badge tone="warning">{data.awaiting.length}</Badge></div>
        <Card><QueueTable rows={data.awaiting} empty="No disagreements to settle" /></Card>
      </div>
      <div>
        <div className="mb-2 text-[13px] font-medium">Recent reviews</div>
        <Card><QueueTable rows={data.recent} empty="No reviews yet" /></Card>
      </div>
    </div>
  );
}

export function HowItWorks() {
  const step = (n: number, t: string, d: string) => (
    <div className="flex gap-2.5"><span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-violet/10 font-mono text-2xs font-semibold text-violet">{n}</span><div><div className="text-xs font-medium">{t}</div><div className="text-2xs text-muted-foreground">{d}</div></div></div>
  );
  return (
    <Card className="p-4">
      <div className="grid gap-3 md:grid-cols-4">
        {step(1, "Rule engine scores", "Deterministic score decides who must approve.")}
        {step(2, "Agents review", "History, data impact, purpose and policy search, each citing evidence.")}
        {step(3, "Challenger + Aggregator", "Double counting removed, then fixed rules give the AI score and verdict.")}
        {step(4, "You set the final score", "Only when they disagree. Agents can add a reviewer, never remove one.")}
      </div>
      <p className="mt-3 border-t pt-2 text-2xs text-muted-foreground">Runs inside ASTITVA on simulated data. No external AI service or API key; an optional local model may only phrase the summary.</p>
    </Card>
  );
}

export function ScoreChoice({ review, onDone }: { review: any; onDone: () => void }) {
  const [pick, setPick] = useState<"RULE" | "AI" | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const agg = review.aggregator || {};
  const lower = pick && (pick === "RULE" ? review.rule_score < review.ai_score : review.ai_score < review.rule_score);
  const submit = async () => {
    setBusy(true);
    try {
      await api(`/api/agent-review/${review.request_id}/choose`, { json: { choice: pick, reason: reason || undefined } });
      toast.success(`Final score set: ${pick === "AI" ? review.ai_score : review.rule_score}`);
      onDone();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  const option = (k: "RULE" | "AI", title: string, score: number, level: string, bandKey: string, icon: any, note: string) => {
    const Icon = icon;
    return (
      <button type="button" onClick={() => setPick(k)}
        className={cn("rounded-lg border p-3 text-left transition-all", pick === k ? "border-violet bg-violet/[.06] ring-2 ring-violet/20" : "hover:border-violet/40")}>
        <div className="flex items-center gap-1.5 text-xs font-medium"><Icon className="h-3.5 w-3.5 text-violet" />{title}</div>
        <div className="mt-1.5 flex items-baseline gap-2"><span className="text-3xl font-semibold tabular">{score}</span><RiskBadge level={level} /></div>
        <div className="mt-1 text-2xs text-muted-foreground">{BAND[bandKey]} · {note}</div>
      </button>
    );
  };
  return (
    <Card className="border-warning/40">
      <CardHeader title={<span className="inline-flex items-center gap-1.5"><Gavel className="h-4 w-4 text-warning" />Choose the final score</span>}
        description="The rule engine and the agents disagree. Your choice is the score of record the Manager sees, and it is audited." />
      <CardBody className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          {option("RULE", "Rule engine", review.rule_score, agg.rule_level, agg.rule_band, Scale, "deterministic")}
          {option("AI", "AI agents", review.ai_score, agg.ai_level, agg.ai_band, Sparkles, `${agg.confidence?.toLowerCase() || "medium"} confidence`)}
        </div>
        {pick && (
          <div className="space-y-3 animate-fade-in">
            <Field label={lower ? "Reason (required for the lower score)" : "Reason (optional)"}>
              <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder={lower ? "Why is the lower score right here?" : "Anything the Manager should know"} />
            </Field>
            {pick === "RULE" && review.stages_added?.length > 0 && <p className="text-2xs text-muted-foreground">The Security Manager review added by the agents stays. Choosing a score never removes a reviewer.</p>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setPick(null)}>Back</Button>
              <Button onClick={submit} loading={busy} disabled={!!lower && reason.trim().length < 10}>Use {pick === "AI" ? "AI" : "rule"} score</Button>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

/** Request detail card. Security Manager: compact view with a link to the agent graph. Manager: the final record. */
export function AgentReviewCard({ requestId }: { requestId: string }) {
  const { can } = useSession();
  const { data, error } = useSWR(`/api/requests/${requestId}/agent-review`, fetcher, { shouldRetryOnError: false });
  if (error || !data) return null;
  const awaiting = data.status === "AWAITING_CHOICE";
  const fv = FINAL_VERDICT[data.verdict] || FINAL_VERDICT.APPROVE;
  if (data.view === "full") {
    return (
      <Card className={cn(awaiting && "border-warning/40")}>
        <CardHeader title={<span className="inline-flex items-center gap-1.5"><Workflow className="h-4 w-4 text-violet" />Agent review</span>}
          description="Security Manager only. Five agents next to the rule engine."
          action={<Button asChild size="sm" variant={awaiting ? "default" : "outline"}><Link href={`/agent-review/${requestId}`}>{awaiting ? "Choose score" : "Open graph"}</Link></Button>} />
        <CardBody className="space-y-3">
          <div className="grid grid-cols-3 gap-2 text-center">
            <ScoreBox label="Rule" v={data.rule_score} />
            <ScoreBox label="AI agents" v={data.ai_score} delta={data.ai_score - data.rule_score} />
            <ScoreBox label="Final" v={awaiting ? null : data.final_score} />
          </div>
          <div className="flex items-center gap-2"><AgentDots agents={data.agents} /><Badge tone={fv.tone} className="ml-auto"><fv.icon />{fv.label}</Badge></div>
          <p className="text-xs text-muted-foreground">{awaiting ? "The scores disagree: set the final score before the security approval." : data.chosen_label + "."}</p>
        </CardBody>
      </Card>
    );
  }
  if (!can("approvals:read")) return null;
  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-4 w-4 text-violet" />Final risk score</span>}
        description="The score of record for this request and who set it." />
      <CardBody className="space-y-3">
        <div className="flex items-center gap-3">
          <span className={cn("text-4xl font-semibold tabular tracking-tight", awaiting && "text-muted-foreground")}>{awaiting ? "—" : data.final_score}</span>
          {!awaiting && <RiskBadge level={data.final_level} />}
        </div>
        <div className="rounded-md bg-muted/50 p-2.5 text-xs">
          <div className="font-medium">{awaiting ? "Waiting for the Security Manager" : data.chosen === "AUTO" ? "Automatic" : data.chosen === "AI" ? "AI agents' score, chosen by the Security Manager" : "Rule-based score, chosen by the Security Manager"}</div>
          <div className="mt-0.5 text-muted-foreground">{data.chosen_label}{data.chosen_at ? ` · ${fmtDate(data.chosen_at)}` : ""}</div>
          {data.chosen_reason && <div className="mt-1.5 text-foreground">“{data.chosen_reason}”</div>}
        </div>
        <div className="grid grid-cols-2 gap-2 text-center">
          <ScoreBox label="Rule engine" v={data.rule_score} />
          <ScoreBox label="AI agents" v={data.ai_score} delta={data.ai_score - data.rule_score} />
        </div>
        {data.stages_added?.length > 0 && <p className="text-xs text-muted-foreground">A Security Manager review was added because the agents rated it higher.</p>}
        <p className="text-2xs text-muted-foreground">How each agent decided is visible to the Security Manager only.</p>
      </CardBody>
    </Card>
  );
}

function ScoreBox({ label, v, delta }: { label: string; v: number | null; delta?: number }) {
  return (
    <div className="rounded-md bg-muted/50 px-2 py-2">
      <div className="text-2xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 flex items-center justify-center gap-1.5"><span className="text-lg font-semibold tabular">{v ?? "?"}</span>{delta != null && delta !== 0 && <Delta v={delta} />}</div>
      {v != null && <div className="text-2xs text-muted-foreground">{risk(v)}</div>}
    </div>
  );
}
