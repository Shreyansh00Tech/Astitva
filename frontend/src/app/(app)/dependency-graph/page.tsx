"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR, { mutate as globalMutate } from "swr";
import { toast } from "sonner";
import { Bot, Network, Plug, RotateCcw, ShieldX, Undo2, Users, Waypoints, KeyRound } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn, relTime } from "@/lib/utils";
import { Card, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { Field, Textarea } from "@/components/ui/input";
import { SensitivityBadge } from "@/components/status";
import { DependencyGraph, downstreamOf, GraphLegend, type GNode, type Graph } from "@/components/dependency-graph";

function Tile({ icon: Icon, label, value, sub, tone }: { icon: any; label: string; value: number; sub?: string; tone?: string }) {
  return (
    <div className="rounded-lg border bg-card px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wider text-muted-foreground"><Icon className={cn("h-3.5 w-3.5", tone)} />{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums transition-all duration-500">{value}</div>
      {sub && <div className="text-2xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

type Scope = { users: boolean; agents: boolean; services: boolean };

function GraphPanel({ resourceId }: { resourceId: string }) {
  const { data: live, error, mutate } = useSWR<Graph>(`/api/resources/${resourceId}/dependency-graph`, fetcher, { refreshInterval: 5000 });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [revoking, setRevoking] = useState(false);
  const [scope, setScope] = useState<Scope>({ users: true, agents: false, services: false });
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [snap, setSnap] = useState<{ before: Graph; after: Graph; revoked: any } | null>(null);
  const [view, setView] = useState<"before" | "after">("after");
  useEffect(() => { setSelected(new Set()); setRevoking(false); setSnap(null); setReason(""); }, [resourceId]);

  const full = !!live?.viewer?.full_view;
  const graph = snap && view === "before" ? snap.before : live;

  // What would go dark if confirmed: chosen nodes plus everything that depends on them.
  const targets = useMemo(() => {
    if (!live || !revoking) return new Set<string>();
    if (selected.size) return new Set(selected);
    return new Set(live.nodes.filter((n) => n.can_revoke && (
      ((n.type === "USER") && scope.users) || (n.type === "AGENT" && scope.agents) ||
      ((n.type === "API" || n.type === "RESOURCE") && n.depth === 1 && scope.services))).map((n) => n.id));
  }, [live, revoking, selected, scope]);
  const preview = useMemo(() => (live && revoking ? downstreamOf(live, targets) : undefined), [live, revoking, targets]);
  const changed = useMemo(() => {
    if (!snap || view !== "after") return undefined;
    const prev = Object.fromEntries(snap.before.nodes.map((n) => [n.id, n.status]));
    return new Set(snap.after.nodes.filter((n) => prev[n.id] && prev[n.id] !== n.status).map((n) => n.id));
  }, [snap, view]);

  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (!live || !graph) return <Skeleton className="h-[480px]" />;

  const toggle = (n: GNode) => {
    const s = new Set(selected);
    s.has(n.id) ? s.delete(n.id) : s.add(n.id);
    setSelected(s);
    setRevoking(true);
  };
  const tcount = (pred: (n: GNode) => boolean) => live.nodes.filter((n) => targets.has(n.id) && pred(n)).reduce((a, n) => a + (n.count || 1), 0);
  const tokens = live.edges.filter((e) => targets.has(e.target) && e.status === "ACTIVE").reduce((a, e) => a + (e.tokens || 0), 0);
  const degraded = preview ? [...preview].filter((id) => !targets.has(id)).length : 0;

  const confirm = async () => {
    const pickedTypes = new Set(live.nodes.filter((n) => selected.has(n.id)).map((n) => n.type));
    const flags = selected.size
      ? { users: pickedTypes.has("USER"), agents: pickedTypes.has("AGENT"), services: pickedTypes.has("API") || pickedTypes.has("RESOURCE") }
      : scope;
    setBusy(true);
    try {
      const r = await api(`/api/resources/${resourceId}/revoke-access`, { json: { reason, ...flags, node_ids: selected.size ? [...selected] : undefined } });
      setSnap({ before: live, after: r.graph, revoked: r.revoked });
      setView("after");
      mutate(r.graph, { revalidate: false });
      globalMutate("/api/dependency-graph/resources");
      setRevoking(false); setSelected(new Set()); setReason("");
      const v = r.revoked;
      toast.success(`Revoked ${v.grants} grant(s), ${v.tokens} token(s), ${v.agents.length} agent(s), ${v.services.length} API link(s)`);
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  const restore = async (n: GNode) => {
    try { const g = await api(`/api/dependencies/${n.dependency_id}/restore`, { json: { reason: "Restored from the dependency graph" } }); mutate(g, { revalidate: false }); toast.success(`${n.label} reconnected`); }
    catch (e) { toast.error(errorMessage(e)); }
  };
  const s = graph.summary;
  const cutOff = live.nodes.filter((n) => n.can_restore);
  const anyRevocable = live.nodes.some((n) => n.can_revoke);

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link href={`/resources/${live.resource.id}`} className="truncate text-sm font-semibold hover:underline">{live.resource.name}</Link>
            <SensitivityBadge level={live.resource.sensitivity} />
            <span className="inline-flex items-center gap-1 text-2xs text-success"><span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse2" />Live</span>
          </div>
          <div className="mt-0.5 text-2xs text-muted-foreground">{live.resource.code} · Owner {live.resource.owner} · {full ? "Organisation-wide view" : "Your team by name, other teams grouped"}</div>
        </div>
        <div className="flex items-center gap-2">
          {snap && (
            <div className="inline-flex rounded-md border p-0.5 text-xs">
              {(["before", "after"] as const).map((v) => (
                <button key={v} onClick={() => setView(v)} className={cn("rounded px-2.5 py-1 capitalize transition-colors", view === v ? "bg-secondary font-medium" : "text-muted-foreground hover:text-foreground")}>{v}</button>
              ))}
            </div>
          )}
          {!revoking && anyRevocable && <Button variant="destructive" size="sm" onClick={() => setRevoking(true)}><ShieldX />Revoke access…</Button>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 border-b p-4 sm:grid-cols-5">
        <Tile icon={Users} label="Users" value={s.users} tone="text-info" />
        <Tile icon={Bot} label="AI agents" value={s.agents} tone="text-violet" />
        <Tile icon={Plug} label="APIs" value={s.apis} tone="text-success" />
        <Tile icon={Waypoints} label="Indirect" value={s.indirect_users + s.indirect_agents + s.indirect_apis} sub={`${s.indirect_users} users · ${s.indirect_agents} agents · ${s.indirect_apis} APIs`} />
        <Tile icon={KeyRound} label="Live tokens" value={s.active_tokens} sub={s.emergency_sessions ? `${s.emergency_sessions} break-glass` : undefined} tone="text-warning" />
      </div>

      {revoking && (
        <div className="animate-fade-in border-b bg-critical/[.03] p-4">
          <div className="flex flex-col gap-4 lg:flex-row">
            <div className="flex-1 space-y-3">
              <div className="text-[13px] font-medium">Before you confirm: this is what goes dark</div>
              {selected.size ? (
                <p className="text-xs text-muted-foreground">{selected.size} selected in the graph. Click more nodes with a checkbox to add or remove them.</p>
              ) : (
                <div className="flex flex-wrap gap-2 text-xs">
                  {([["users", "Users' grants and tokens", true], ["agents", "AI agents", live.viewer.can_revoke_agents], ["services", "API / service links", live.viewer.can_revoke_services]] as const).map(([k, label, ok]) => (
                    <label key={k} className={cn("flex items-center gap-1.5 rounded-md border px-2 py-1", !ok && "opacity-50")}>
                      <input type="checkbox" disabled={!ok} checked={scope[k]} onChange={(e) => setScope({ ...scope, [k]: e.target.checked })} />{label}
                    </label>
                  ))}
                  {!full && <span className="self-center text-2xs text-muted-foreground">Agents and APIs can only be cut by the Security Manager.</span>}
                </div>
              )}
              <div className="flex flex-wrap gap-1.5 text-xs">
                <Badge tone="critical">{tcount((n) => n.type === "USER")} users</Badge>
                <Badge tone="critical">{tokens} tokens</Badge>
                <Badge tone="critical">{tcount((n) => n.type === "AGENT")} agents</Badge>
                <Badge tone="critical">{tcount((n) => n.type === "API" || n.type === "RESOURCE")} APIs</Badge>
                <Badge tone="warning">{degraded} indirectly degraded</Badge>
              </div>
            </div>
            <div className="w-full space-y-2 lg:w-80">
              <Field label="Reason (sent to the people affected and the audit log)"><Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Model being retrained after drift" /></Field>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => { setRevoking(false); setSelected(new Set()); }}>Cancel</Button>
                <Button variant="destructive" size="sm" loading={busy} disabled={reason.trim().length < 3 || targets.size === 0} onClick={confirm}><ShieldX />Confirm revoke</Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {snap && view === "after" && !revoking && (
        <div className="animate-fade-in border-b bg-success/[.04] px-4 py-2.5 text-xs">
          <span className="font-medium">Done.</span> Revoked {snap.revoked.grants} grant(s) and {snap.revoked.tokens} token(s)
          {snap.revoked.users.length > 0 && <> for {snap.revoked.users.join(", ")}</>}
          {snap.revoked.agents.length > 0 && <>, agents: {snap.revoked.agents.join(", ")}</>}
          {snap.revoked.services.length > 0 && <>, APIs cut: {snap.revoked.services.join(", ")}</>}
          {snap.revoked.emergency_sessions > 0 && <>, {snap.revoked.emergency_sessions} break-glass session(s) ended</>}
          {snap.revoked.skipped > 0 && <span className="text-muted-foreground"> · {snap.revoked.skipped} outside your team left untouched</span>}.
          <span className="text-muted-foreground"> Switch to Before to compare.</span>
        </div>
      )}

      <CardBody className="space-y-3">
        {graph.nodes.length <= 1 ? (
          <EmptyState icon={Network} title="Nothing depends on this resource" description="No active users, agents or API links. Revoking it would affect no one." />
        ) : (
          <DependencyGraph graph={graph} selected={selected} onToggle={view === "before" && snap ? undefined : toggle}
            preview={revoking ? preview : undefined} highlightChanged={changed} />
        )}
        <div className="flex flex-col gap-2 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
          <GraphLegend />
          <span className="text-2xs text-muted-foreground">Simulated APIs · updated {relTime((live as any).generated_at)}</span>
        </div>
        {cutOff.length > 0 && (
          <div className="rounded-lg border border-warning/30 bg-warning/[.04] p-3">
            <div className="mb-2 text-xs font-medium">API links cut off from this resource</div>
            <div className="flex flex-wrap gap-2">{cutOff.map((n) => (
              <Button key={n.id} variant="outline" size="sm" onClick={() => restore(n)}><Undo2 />Reconnect {n.label}</Button>
            ))}</div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function GraphPage() {
  const { can, loading } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const { data: list, error, mutate } = useSWR(can("graph:read") ? "/api/dependency-graph/resources" : null, fetcher, { refreshInterval: 10000 });
  const current = params.get("resource") || list?.find((r: any) => r.code === "RES-DS-001")?.id || list?.[0]?.id;
  if (!loading && !can("graph:read")) return <EmptyState icon={ShieldX} title="Not available for your role" description="The access dependency graph is visible to Managers and the Security Manager only." />;
  return (
    <div className="animate-fade-in">
      <PageHeader title="Access Dependency Graph" eyebrow={<Badge tone="violet"><Network />Blast radius</Badge>}
        description="Pick a model or resource to see every user, AI agent and API that depends on it. Revoke from here and watch the impact before and after."
        actions={<Button variant="outline" size="sm" onClick={() => mutate()}><RotateCcw />Refresh</Button>} />
      <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card className="h-fit">
          <div className="border-b px-3 py-2 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Resources</div>
          {error ? <ErrorState error={error} onRetry={() => mutate()} /> : !list ? <div className="p-3"><Skeleton className="h-64" /></div> : (
            <div className="max-h-[70vh] divide-y overflow-y-auto scroll-thin">
              {list.map((r: any) => (
                <button key={r.id} onClick={() => router.replace(`/dependency-graph?resource=${r.id}`)}
                  className={cn("block w-full px-3 py-2.5 text-left transition-colors hover:bg-accent", r.id === current && "bg-violet/[.06] shadow-[inset_2px_0_0] shadow-violet")}>
                  <div className="flex items-center justify-between gap-2"><span className="truncate text-[13px] font-medium">{r.name}</span><SensitivityBadge level={r.sensitivity} /></div>
                  <div className="mt-0.5 flex gap-3 text-2xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1"><Users className="h-3 w-3" />{r.active_grants}</span>
                    <span className="inline-flex items-center gap-1"><Bot className="h-3 w-3" />{r.agents}</span>
                    <span className="inline-flex items-center gap-1"><Plug className="h-3 w-3" />{r.apis}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Card>
        {current ? <GraphPanel resourceId={current} /> : <Skeleton className="h-[480px]" />}
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<Skeleton className="h-96" />}><GraphPage /></Suspense>;
}
