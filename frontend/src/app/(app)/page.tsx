"use client";

import Link from "next/link";
import useSWR from "swr";
import { Activity, AlertTriangle, ArrowUpRight, Bot, CheckCircle2, Clock, Gauge, Hourglass, KeyRound, ScrollText, ShieldAlert, Siren, TrendingUp, Users, XCircle } from "lucide-react";
import { fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { relTime } from "@/lib/utils";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";
import { StatTile } from "@/components/stat";
import { AreaSeries, HBars, LinesChart, StackedBars, STATUS_KEY } from "@/components/charts";
import { Button } from "@/components/ui/button";

const FEED_ICON: Record<string, any> = {
  REQUEST_CREATED: KeyRound, REQUEST_APPROVE: CheckCircle2, REQUEST_REJECT: XCircle, REQUEST_NARROW_SCOPE: ShieldAlert,
  BREAKGLASS_ACTIVATED: Siren, GRANT_EXPIRED: Hourglass, DRIFT_SCAN: TrendingUp, AGENT_ACCESS_DENIED: Bot,
  SOD_VIOLATION_BLOCKED: AlertTriangle, RESOURCE_ACCESS_DENIED: XCircle,
};

function Personal({ data }: { data: any }) {
  const { me } = useSession();
  const m = data.metrics;
  return (
    <>
      <PageHeader title={`Welcome back, ${me?.name.split(" ")[0]}`} description="Your access, requests and recorded work at a glance."
        actions={<Button asChild variant="accent"><Link href="/requests?new=1"><KeyRound />Request access</Link></Button>} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile label="Open requests" value={m.open_requests} icon={Clock} href="/requests" />
        <StatTile label="Approved" value={m.approved_requests} icon={CheckCircle2} tone="success" href="/requests" />
        <StatTile label="Rejected" value={m.rejected_requests} icon={XCircle} href="/requests" />
        <StatTile label="Active grants" value={m.active_grants} icon={KeyRound} tone="violet" href="/active-access" />
        <StatTile label="Expiring < 24h" value={m.expiring_soon} icon={Hourglass} tone={m.expiring_soon ? "warning" : "default"} href="/active-access" />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card><CardHeader title="Daily work activity" description="Recorded task events, last 30 days" /><CardBody><AreaSeries data={data.charts.daily_activity} x="date" y="events" /></CardBody></Card>
        <Card><CardHeader title="Access outcomes" description="Gateway decisions on your purpose-bound tokens" /><CardBody>
          <StackedBars data={data.charts.access_outcomes} x="week" series={[{ key: "allowed", label: "Allowed", color: "status-good" }, { key: "denied", label: "Denied", color: "status-critical" }]} />
        </CardBody></Card>
      </div>
    </>
  );
}

export default function Overview() {
  const { data, error, mutate } = useSWR("/api/dashboard", fetcher, { refreshInterval: 30000 });
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (!data) return <div className="space-y-4"><Skeleton className="h-8 w-64" /><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div><Skeleton className="h-72" /></div>;
  if (data.personal) return <Personal data={data} />;
  const m = data.metrics;
  const c = data.charts;
  return (
    <>
      <PageHeader title="Security overview" description="Live posture of identities, access and AI agents across Nexora Technologies."
        eyebrow={<span className="inline-flex items-center gap-1.5 text-2xs font-medium text-success"><span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse2" />Live · refreshes every 30s</span>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Total employees" value={m.total_employees} icon={Users} hint="Active identities" href="/employees" />
        <StatTile label="Active access grants" value={m.active_grants} icon={KeyRound} tone="violet" href="/active-access" />
        <StatTile label="Pending requests" value={m.pending_requests} icon={Clock} href="/approvals" />
        <StatTile label="High-risk requests" value={m.high_risk_requests} icon={ShieldAlert} tone={m.high_risk_requests ? "critical" : "default"} hint="Pending, score > 60" href="/approvals" />
        <StatTile label="Expiring permissions" value={m.expiring_permissions} icon={Hourglass} tone="warning" hint="Within 72 hours" href="/active-access" />
        <StatTile label="Emergency sessions" value={m.active_emergency_sessions} icon={Siren} tone={m.active_emergency_sessions ? "critical" : "default"} hint="Break-glass active now" href="/emergency" />
        <StatTile label="Permission drift alerts" value={m.drift_alerts} icon={TrendingUp} tone="warning" href="/drift" />
        <StatTile label="Policy violations" value={m.policy_violations} icon={AlertTriangle} tone="critical" hint="Open, last 30 days" href="/audit?tab=alerts" />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardHeader title="Access requests over time" description="New requests per day, last 30 days" /><CardBody><AreaSeries data={c.requests_over_time} x="date" y="requests" height={220} /></CardBody></Card>
        <Card>
          <CardHeader title="Recent activity" description="From the audit trail" action={<Link href="/audit" className="text-2xs text-violet hover:underline">All events</Link>} />
          <div className="max-h-[260px] overflow-y-auto px-4 pb-3 scroll-thin">
            {data.recent_activity.map((a: any) => { const I = FEED_ICON[a.action] || Activity; return (
              <div key={a.seq} className="flex gap-2.5 py-2">
                <span className="mt-0.5 rounded-md border bg-muted/50 p-1"><I className="h-3.5 w-3.5 text-muted-foreground" /></span>
                <div className="min-w-0"><p className="text-[13px] leading-snug">{a.text}</p><p className="text-2xs text-muted-foreground">{relTime(a.at)}</p></div>
              </div>); })}
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card><CardHeader title="Approval vs rejection" description="Decisions per week" /><CardBody>
          <StackedBars data={c.approval_trends} x="week" series={[{ key: "approved", label: "Approved", color: "status-good" }, { key: "rejected", label: "Rejected", color: "status-critical" }]} />
        </CardBody></Card>
        <Card><CardHeader title="Risk distribution" description="Assessments, last 90 days" /><CardBody>
          <HBars data={c.risk_distribution} label="level" value="count" colorFor={(r) => STATUS_KEY[r.level]} height={200} />
        </CardBody></Card>
        <Card><CardHeader title="Department resource usage" description="Authorized operations, 30 days" /><CardBody>
          <HBars data={c.department_usage} label="department" value="operations" colorKey="series-4" height={200} />
        </CardBody></Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card><CardHeader title="Employee activity trends" description="Recorded task events per week" /><CardBody><AreaSeries data={c.activity_trends} x="week" y="events" colorKey="series-3" /></CardBody></Card>
        <Card><CardHeader title="Permission drift trends" description="New findings per week by severity" /><CardBody>
          <StackedBars data={c.drift_trends} x="week" series={[{ key: "LOW", label: "Low", color: "status-good" }, { key: "MEDIUM", label: "Medium", color: "status-warning" }, { key: "HIGH", label: "High", color: "status-serious" }, { key: "CRITICAL", label: "Critical", color: "status-critical" }]} />
        </CardBody></Card>
        <Card><CardHeader title="Emergency access history" description="Break-glass sessions per week" /><CardBody><StackedBars data={c.emergency_history} x="week" series={[{ key: "sessions", label: "Sessions", color: "series-2" }]} /></CardBody></Card>
        <Card><CardHeader title="Access expiry timeline" description="Active grants expiring per day, next 14 days" /><CardBody><StackedBars data={c.expiry_timeline} x="date" series={[{ key: "expiring", label: "Expiring", color: "series-1" }]} /></CardBody></Card>
      </div>
    </>
  );
}
