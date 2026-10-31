"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { Bot, Database, Network, Plus, Siren, Table2 } from "lucide-react";
import { fetcher } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingRows, PageHeader } from "@/components/ui/misc";
import { Perms, SensitivityBadge } from "@/components/status";
import { NewRequestDialog } from "@/components/new-request";

const TYPE_ICON: Record<string, any> = { AI_MODEL: Bot, DATASET: Table2, DATABASE: Database, API: Network };

export default function Resources() {
  const { data, error, isLoading, mutate } = useSWR("/api/resources", fetcher);
  const [req, setReq] = useState<string | undefined>();
  return (
    <>
      <PageHeader title="Resource registry" description="Sensitive models, datasets, databases and APIs, each with an owner, classification and access policy." />
      {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading ? <LoadingRows /> : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.map((r: any) => { const I = TYPE_ICON[r.type] || Database; return (
            <Card key={r.id} className="group flex flex-col p-4 transition-colors hover:border-violet/40">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <span className="rounded-md border bg-muted/50 p-2"><I className="h-4 w-4 text-violet" /></span>
                  <div><Link href={`/resources/${r.id}`} className="text-[13px] font-semibold hover:text-violet">{r.name}</Link><div className="font-mono text-2xs text-muted-foreground">{r.code} · {r.type.replace("_", " ")}</div></div>
                </div>
                <SensitivityBadge level={r.sensitivity} />
              </div>
              <p className="mt-3 line-clamp-2 text-xs text-muted-foreground">{r.description}</p>
              <div className="mt-3 flex flex-wrap items-center gap-1.5"><Perms perms={r.available_permissions} />{r.breakglass_allowed && <Badge tone="critical"><Siren />Break-glass</Badge>}</div>
              <div className="mt-4 flex items-center justify-between border-t pt-3 text-xs">
                <span className="text-muted-foreground">Owner <span className="text-foreground">{r.owner.name}</span> · {r.department}</span>
                <span className="tabular text-muted-foreground"><span className="font-medium text-foreground">{r.active_grants}</span> active</span>
              </div>
              <div className="mt-3 flex gap-2">
                <Button size="sm" variant="outline" asChild className="flex-1"><Link href={`/resources/${r.id}`}>Details</Link></Button>
                <Button size="sm" variant="subtle" className="flex-1" onClick={() => setReq(r.id)}><Plus />Request</Button>
              </div>
            </Card>); })}
        </div>
      )}
      <NewRequestDialog open={!!req} onOpenChange={(o) => !o && setReq(undefined)} presetResource={req} />
    </>
  );
}
