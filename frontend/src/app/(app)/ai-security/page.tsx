"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Bot, KeyRound, Pause, Play, Send, ShieldCheck, Terminal, Wrench } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn, fmtDate, relTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ErrorState, LoadingRows, Mono, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Perms, SensitivityBadge, StatusBadge } from "@/components/status";
import { Field, Select } from "@/components/ui/input";
import { Dialog, DialogContent } from "@/components/ui/dialog";

function Simulator({ agents, resources, onRun }: { agents: any[]; resources: any[]; onRun: () => void }) {
  const [agentId, setAgentId] = useState(agents[1]?.id || agents[0]?.id);
  const agent = agents.find((a) => a.id === agentId);
  const [resourceId, setResourceId] = useState(resources.find((r) => r.code === "RES-FIN-003")?.id || resources[0]?.id);
  const [action, setAction] = useState("READ");
  const [tool, setTool] = useState(agent?.allowed_tools[0] || "");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setResult(await api(`/api/agents/${agentId}/simulate`, { json: { resource_id: resourceId, action, tool } })); onRun(); }
    catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-1.5"><Terminal className="h-4 w-4 text-violet" />Authorization gateway test</span>} description="Runs an agent action through the same policy every real agent call passes. Denials raise an alert and an audit event." />
      <CardBody className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Agent"><Select value={agentId} onChange={(e) => { setAgentId(e.target.value); const a = agents.find((x) => x.id === e.target.value); setTool(a?.allowed_tools[0] || ""); }}>{agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
          <Field label="Target resource"><Select value={resourceId} onChange={(e) => setResourceId(e.target.value)}>{resources.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select></Field>
          <Field label="Action"><Select value={action} onChange={(e) => setAction(e.target.value)}>{["READ", "EXECUTE", "WRITE", "DELETE", "ADMIN"].map((p) => <option key={p}>{p}</option>)}</Select></Field>
          <Field label="Tool"><Select value={tool} onChange={(e) => setTool(e.target.value)}>{Array.from(new Set([...(agent?.allowed_tools || []), "sql.write", "shell.exec", "email.send"])).map((t) => <option key={t} value={t}>{t}{agent?.allowed_tools.includes(t) ? "" : " (not allowed)"}</option>)}</Select></Field>
        </div>
        <div className="flex justify-end"><Button onClick={run} loading={busy}><Send />Invoke via gateway</Button></div>
        {result && (
          <div className={cn("rounded-md border p-3 text-xs animate-fade-in", result.decision === "ALLOWED" ? "border-success/40 bg-success/5" : "border-critical/40 bg-critical/5")}>
            <div className="flex items-center gap-2"><span className={cn("text-sm font-semibold tracking-wide", result.decision === "ALLOWED" ? "text-success" : "text-critical")}>ACCESS {result.decision}</span><Mono className="text-muted-foreground">{result.code}</Mono></div>
            <p className="mt-1">Reason: {result.message}</p>
            {result.decision === "DENIED" && <p className="mt-1 text-muted-foreground">Security alert generated · audit event recorded · agent owner notified</p>}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export default function AiSecurity() {
  const { can } = useSession();
  const { data, error, isLoading, mutate } = useSWR("/api/agents", fetcher, { refreshInterval: 20000 });
  const [key, setKey] = useState<any>(null);
  const setStatus = async (a: any, status: string) => {
    try { await api(`/api/agents/${a.id}/status`, { json: { status, reason: status === "SUSPENDED" ? "Suspended from AI Security Center" : "Reactivated" } }); toast.success(`${a.name} ${status.toLowerCase()}`); mutate(); }
    catch (e) { toast.error(errorMessage(e)); }
  };
  const rotate = async (a: any) => { try { setKey({ agent: a, ...(await api(`/api/agents/${a.id}/rotate-key`, { method: "POST" })) }); } catch (e) { toast.error(errorMessage(e)); } };
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (isLoading) return <LoadingRows />;
  return (
    <>
      <PageHeader title="AI Security Center" description="Every AI agent has its own identity, purpose, allow-listed tools and scoped, expiring permissions. All calls pass through the authorization gateway." />
      <div className="grid gap-3 md:grid-cols-2">
        {data.agents.map((a: any) => (
          <Card key={a.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <span className="rounded-lg bg-violet/10 p-2"><Bot className="h-5 w-5 text-violet" /></span>
                <div><div className="text-[13px] font-semibold">{a.name}</div><div className="font-mono text-2xs text-muted-foreground">{a.code} · owner {a.owner.name}</div></div>
              </div>
              <div className="flex items-center gap-1.5"><Badge tone={a.risk_score > 40 ? "warning" : "neutral"}>Risk {a.risk_score}</Badge><StatusBadge status={a.status} /></div>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">{a.purpose}</p>
            <div className="mt-3 space-y-1.5">
              {a.permissions.map((p: any) => (
                <div key={p.id} className="flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-xs">
                  <span className="flex items-center gap-1.5 truncate">{p.resource.name}<SensitivityBadge level={p.resource.sensitivity} /></span><Perms perms={p.permissions} />
                </div>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-1"><Wrench className="h-3.5 w-3.5 text-muted-foreground" />{a.allowed_tools.map((t: string) => <Badge key={t} tone="outline" className="font-mono">{t}</Badge>)}</div>
            <div className="mt-3 flex items-center justify-between border-t pt-3 text-xs text-muted-foreground">
              <span>Expires {fmtDate(a.expires_at, false)} ({relTime(a.expires_at)})</span>
              <span className="tabular"><span className="text-success">{a.stats_7d.ALLOWED}</span> allowed · <span className="text-critical">{a.stats_7d.DENIED}</span> denied (7d)</span>
            </div>
            {can("agents:manage") && (
              <div className="mt-3 flex gap-2">
                {a.status === "ACTIVE" ? <Button size="sm" variant="outline" onClick={() => setStatus(a, "SUSPENDED")}><Pause />Suspend</Button> : <Button size="sm" variant="outline" onClick={() => setStatus(a, "ACTIVE")}><Play />Reactivate</Button>}
                <Button size="sm" variant="ghost" onClick={() => rotate(a)}><KeyRound />Rotate key</Button>
              </div>
            )}
          </Card>
        ))}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[420px_1fr]">
        <Simulator agents={data.agents} resources={data.resources} onRun={() => mutate()} />
        <Card>
          <CardHeader title="Gateway decisions" description="Most recent agent calls" />
          <Table>
            <THead><TR><TH>When</TH><TH>Agent</TH><TH>Resource</TH><TH>Action</TH><TH>Tool</TH><TH>Decision</TH></TR></THead>
            <TBody>{data.recent_events.map((e: any, i: number) => (
              <TR key={i}><TD className="whitespace-nowrap text-muted-foreground">{relTime(e.at)}</TD><TD className="whitespace-nowrap">{e.agent}</TD><TD className="whitespace-nowrap">{e.resource}</TD><TD className="font-mono text-xs">{e.action}</TD><TD className="font-mono text-xs text-muted-foreground">{e.tool}</TD>
                <TD title={e.reason}><StatusBadge status={e.outcome} /></TD></TR>))}</TBody>
          </Table>
        </Card>
      </div>
      <Card className="mt-4 p-4 text-xs">
        <div className="mb-2 flex items-center gap-1.5 font-medium"><ShieldCheck className="h-4 w-4 text-violet" />Agent integration</div>
        <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-2xs scroll-thin">{`curl -X POST /api/agent-gateway/invoke \\
  -H "X-Agent-Id: AGT-SUP-01" -H "X-Agent-Key: $AGENT_KEY" \\
  -d '{"resource":"RES-FIN-003","action":"READ","tool":"kb.search"}'
# -> 403 {"decision":"DENIED","code":"RESOURCE_NOT_ALLOWED","message":"Agent is not authorized to access this resource."}`}</pre>
      </Card>
      <Dialog open={!!key} onOpenChange={(o) => !o && setKey(null)}>
        {key && <DialogContent title={`New key for ${key.agent.name}`} description={key.note}><Mono className="block break-all rounded-md bg-muted p-3">{key.api_key}</Mono></DialogContent>}
      </Dialog>
    </>
  );
}
