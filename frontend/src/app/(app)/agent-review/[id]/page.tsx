"use client";

import Link from "next/link";
import { use, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, Lock } from "lucide-react";
import { fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { fmtDate } from "@/lib/utils";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status";
import { AgentGraph, NODE_TITLE, NodeDetail, VERDICT } from "@/components/agent-graph";
import { ScoreChoice } from "@/components/agent-review";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can, loading } = useSession();
  const { data, error, mutate } = useSWR(can("risk:decide") ? `/api/requests/${id}/agent-review` : null, fetcher);
  const [sel, setSel] = useState("AGGREGATOR");
  if (!loading && !can("risk:decide")) return <EmptyState icon={Lock} title="Security Manager only" description="Managers see the final score on the request page." />;
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (!data) return <div className="space-y-3"><Skeleton className="h-10 w-80" /><Skeleton className="h-[620px]" /></div>;
  const r = data.request;
  const agent = data.agents.find((a: any) => a.code === sel);
  return (
    <div className="animate-fade-in space-y-4">
      <div>
        <Link href="/agent-review" className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />Agent Review</Link>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2"><h1 className="font-mono text-lg font-semibold">{r.ref}</h1><StatusBadge status={r.status} /></div>
            <p className="mt-1 text-[13px] text-muted-foreground"><span className="text-foreground">{r.requester.name}</span> · {r.resource.name} · {r.purpose_label} · reviewed {fmtDate(data.created_at)}</p>
          </div>
          <Button asChild size="sm" variant="outline"><Link href={`/approvals/${r.id}`}>Open request</Link></Button>
        </div>
      </div>
      <Card className="p-4">
        <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted-foreground">
          <span>Click any node to see how it decided.</span>
          {["OK", "CAUTION", "RISK", "NO_DATA"].map((v) => <span key={v} className="inline-flex items-center gap-1"><span className={`h-2 w-2 rounded-full ${VERDICT[v].dot}`} />{VERDICT[v].label}</span>)}
          <span className="ml-auto">Points on each line = what that agent adds to the rule score</span>
        </div>
        <AgentGraph review={data} selected={sel} onSelect={setSel} />
      </Card>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title={NODE_TITLE[sel] || sel} action={agent ? <Badge tone={(VERDICT[agent.verdict] || VERDICT.OK).tone}>{(VERDICT[agent.verdict] || VERDICT.OK).label}</Badge> : undefined} />
          <CardBody><NodeDetail review={data} k={sel} /></CardBody>
        </Card>
        <div className="space-y-4">
          {data.can_choose ? <ScoreChoice review={data} onDone={() => mutate()} /> : (
            <Card className="p-4">
              <div className="text-[13px] font-medium">Final score: <span className="font-mono">{data.status === "AWAITING_CHOICE" ? "pending" : data.final_score}</span></div>
              <p className="mt-1 text-xs text-muted-foreground">{data.chosen_label}.</p>
              {data.chosen_reason && <p className="mt-2 rounded-md bg-muted/40 p-2 text-xs">“{data.chosen_reason}”</p>}
              {data.status === "AWAITING_CHOICE" && <p className="mt-2 text-2xs text-muted-foreground">You cannot set the score for your own request or one from your own team.</p>}
            </Card>
          )}
          <Card className="p-4 text-xs text-muted-foreground">
            <div className="mb-1 text-[13px] font-medium text-foreground">Guardrails</div>
            <ul className="space-y-1">
              <li>• The rule score decides routing; agents can only add a Security Manager review.</li>
              <li>• Every finding cites a record id; claims without evidence are dropped.</li>
              <li>• Agents read simulated data only and never approve or grant.</li>
              <li>• Same request, same review: no randomness, no external model.</li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
