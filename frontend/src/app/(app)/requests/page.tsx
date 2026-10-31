"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Plus } from "lucide-react";
import { fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { fmtDate, hours } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Perms, RiskBadge, SensitivityBadge } from "@/components/status";
import { MiniStepper } from "@/components/stepper";
import { NewRequestDialog } from "@/components/new-request";
import { Select } from "@/components/ui/input";

function RequestsInner() {
  const params = useSearchParams();
  const { can } = useSession();
  const [open, setOpen] = useState(params.get("new") === "1");
  const [scope, setScope] = useState("mine");
  const [status, setStatus] = useState("");
  const { data, error, isLoading, mutate } = useSWR(`/api/requests?scope=${scope}${status ? `&status=${status}` : ""}`, fetcher);
  return (
    <>
      <PageHeader title="Access requests" description="Request purpose-bound, time-limited access. Track risk, approval stage and outcome."
        actions={<Button variant="accent" onClick={() => setOpen(true)}><Plus />New request</Button>} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tabs value={scope} onValueChange={setScope}>
          <TabsList><TabsTrigger value="mine">My requests</TabsTrigger>{can("requests:read_all") && <TabsTrigger value="all">All requests</TabsTrigger>}</TabsList>
        </Tabs>
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 w-44 text-xs">
          <option value="">All statuses</option>
          {["PENDING", "CHANGES_REQUESTED", "APPROVED", "REJECTED", "CANCELLED"].map((s) => <option key={s} value={s}>{s.replace("_", " ").toLowerCase()}</option>)}
        </Select>
      </div>
      <Card>
        {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading ? <LoadingRows /> : !data?.length ? (
          <EmptyState title="No requests yet" description="Request access to a resource to get started." action={<Button size="sm" variant="outline" onClick={() => setOpen(true)}>New request</Button>} />
        ) : (
          <Table>
            <THead><TR><TH>Request</TH>{scope === "all" && <TH>Requester</TH>}<TH>Resource</TH><TH>Permissions</TH><TH>Purpose</TH><TH>Duration</TH><TH>Risk</TH><TH>Needed by</TH><TH>Progress</TH><TH>Submitted</TH></TR></THead>
            <TBody>
              {data.map((r: any) => (
                <TR key={r.id}>
                  <TD><Link href={`/requests/${r.id}`} className="font-mono text-xs font-medium text-violet hover:underline">{r.ref}</Link></TD>
                  {scope === "all" && <TD className="whitespace-nowrap">{r.requester.name}</TD>}
                  <TD><div className="font-medium">{r.resource.name}</div><div className="mt-0.5"><SensitivityBadge level={r.resource.sensitivity} /></div></TD>
                  <TD><Perms perms={r.requested_permissions} strike={r.requested_permissions.filter((p: string) => !(r.access?.status === "ACTIVE" ? r.access.permissions : r.approved_permissions).includes(p))} /></TD>
                  <TD className="text-muted-foreground">{r.purpose_label}</TD>
                  <TD className="tabular">{hours(r.approved_duration_hours)}</TD>
                  <TD><RiskBadge level={r.risk?.level} score={r.risk?.score} /></TD>
                  <TD className="whitespace-nowrap text-xs">{r.deadline_at ? <span className={r.priority?.overdue ? "font-medium text-critical" : "text-muted-foreground"}>{fmtDate(r.deadline_at)}{r.priority?.overdue && <div className="text-2xs">Overdue</div>}</span> : <span className="text-muted-foreground">—</span>}</TD>
                  <TD><MiniStepper key={`${r.status}-${r.current_stage}`} r={r} /></TD>
                  <TD className="whitespace-nowrap text-muted-foreground">{fmtDate(r.created_at)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      <NewRequestDialog open={open} onOpenChange={setOpen} onCreated={() => mutate()} />
    </>
  );
}

export default function RequestsPage() { return <Suspense><RequestsInner /></Suspense>; }
