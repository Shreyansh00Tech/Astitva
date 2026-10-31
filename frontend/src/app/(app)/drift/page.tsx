"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { CalendarClock, Eye, MoreHorizontal, Radar, ScissorsLineDashed, ShieldX, TrendingUp } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { relTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Perms, SensitivityBadge, SeverityBadge, StatusBadge } from "@/components/status";
import { StatTile } from "@/components/stat";
import { Select } from "@/components/ui/input";
import { Dropdown, DropdownContent, DropdownItem, DropdownTrigger } from "@/components/ui/dropdown";

export default function Drift() {
  const { can, me } = useSession();
  const [status, setStatus] = useState("OPEN");
  const { data, error, isLoading, mutate } = useSWR(`/api/drift?status=${status}`, fetcher);
  const [scanning, setScanning] = useState(false);
  const scan = async () => {
    setScanning(true);
    try { const r = await api("/api/drift/scan", { method: "POST" }); toast.success(`Scan complete · ${r.created} new, ${r.updated} updated, ${r.resolved} resolved`); mutate(); }
    catch (e) { toast.error(errorMessage(e)); } finally { setScanning(false); }
  };
  const act = async (f: any, action: string) => {
    try {
      await api(`/api/drift/${f.id}/action`, { json: { action, permissions: action === "RESTRICT" ? (f.baseline.length ? f.baseline : ["READ"]) : undefined, comment: `${action} from Permission Drift` } });
      toast.success(action === "RESTRICT" ? `Restricted to ${f.baseline.join(", ") || "READ"}` : action === "REVOKE" ? "Permissions revoked" : action === "SCHEDULE_REVIEW" ? "Access review scheduled" : "Marked as reviewed");
      mutate();
    } catch (e) { toast.error(errorMessage(e)); }
  };
  return (
    <>
      <PageHeader title="Permission drift" description="Effective permissions compared against each employee's approved baseline. Nothing is removed automatically: removal needs the Security Manager."
        actions={can("drift:scan") && <Button variant="accent" onClick={scan} loading={scanning}><Radar />Run drift scan</Button>} />
      {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading ? <LoadingRows /> : <>
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Critical" value={data.summary.CRITICAL} tone="critical" icon={TrendingUp} />
          <StatTile label="High" value={data.summary.HIGH} tone="warning" />
          <StatTile label="Medium" value={data.summary.MEDIUM} />
          <StatTile label="Low" value={data.summary.LOW} />
        </div>
        <div className="mb-3"><Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 w-48 text-xs">
          {["OPEN", "REVIEWED", "REVIEW_SCHEDULED", "REMEDIATED", "ALL"].map((s) => <option key={s} value={s}>{s.replace("_", " ").toLowerCase()}</option>)}
        </Select></div>
        <Card>
          {!data.findings.length ? <EmptyState icon={TrendingUp} title="No drift findings" description="Permissions match approved baselines." /> : (
            <Table>
              <THead><TR><TH>Employee</TH><TH>Resource</TH><TH>Baseline access</TH><TH>Current access</TH><TH>Drift severity</TH><TH>Recommendation</TH><TH>Status</TH><TH /></TR></THead>
              <TBody>
                {data.findings.map((f: any) => (
                  <TR key={f.id}>
                    <TD><Link href={`/employees/${f.user.id}`} className="font-medium hover:text-violet whitespace-nowrap">{f.user.name}</Link><div className="text-2xs text-muted-foreground">{f.user.department}</div></TD>
                    <TD><div className="whitespace-nowrap">{f.resource.name}</div><SensitivityBadge level={f.resource.sensitivity} /></TD>
                    <TD>{f.baseline.length ? <Perms perms={f.baseline} /> : <span className="text-2xs text-muted-foreground">No baseline</span>}</TD>
                    <TD><Perms perms={f.current} strike={[]} /><div className="mt-1 flex flex-wrap gap-1">{f.excess.map((p: string) => <span key={p} className="text-2xs font-medium text-critical">+{p}</span>)}{f.unused.length > 0 && <span className="text-2xs text-muted-foreground">· unused {f.unused.join(", ")}</span>}</div></TD>
                    <TD><SeverityBadge severity={f.severity} /><div className="mt-1 text-2xs tabular text-muted-foreground">score {f.score}</div></TD>
                    <TD className="max-w-[280px] text-xs"><div>{f.recommendation}</div><ul className="mt-1 space-y-0.5 text-2xs text-muted-foreground">{f.issues.map((i: string) => <li key={i}>• {i}</li>)}</ul></TD>
                    <TD><StatusBadge status={f.status} /><div className="mt-1 text-2xs text-muted-foreground">{relTime(f.detected_at)}</div></TD>
                    <TD>
                      {["OPEN", "REVIEW_SCHEDULED"].includes(f.status) && f.user.id !== me?.id && (
                        <Dropdown>
                          <DropdownTrigger asChild><Button size="icon" variant="ghost"><MoreHorizontal /></Button></DropdownTrigger>
                          <DropdownContent>
                            <DropdownItem onSelect={() => act(f, "REVIEW")}><Eye />Review permission</DropdownItem>
                            <DropdownItem onSelect={() => act(f, "RESTRICT")}><ScissorsLineDashed />Restrict to baseline</DropdownItem>
                            <DropdownItem onSelect={() => act(f, "REVOKE")} className="text-critical"><ShieldX className="!text-critical" />Revoke permission</DropdownItem>
                            <DropdownItem onSelect={() => act(f, "SCHEDULE_REVIEW")}><CalendarClock />Schedule review</DropdownItem>
                          </DropdownContent>
                        </Dropdown>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      </>}
    </>
  );
}
