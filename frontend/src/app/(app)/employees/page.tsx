"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { Info, Medal, Search, Trophy } from "lucide-react";
import { fetcher } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Avatar, EmptyState, ErrorState, LoadingRows, PageHeader, Tip } from "@/components/ui/misc";
import { Input, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function Filters({ dept, setDept, project, setProject, q, setQ, days, setDays }: any) {
  const { data: depts } = useSWR("/api/departments", fetcher);
  const { data: projects } = useSWR("/api/projects", fetcher);
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      {setQ && <div className="relative w-full sm:w-64"><Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, email, ID" className="h-8 pl-8 text-xs" /></div>}
      <Select value={dept} onChange={(e) => setDept(e.target.value)} className="h-8 w-44 text-xs"><option value="">All departments</option>{depts?.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select>
      <Select value={project} onChange={(e) => setProject(e.target.value)} className="h-8 w-52 text-xs"><option value="">All projects</option>{projects?.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
      {setDays && <Select value={days} onChange={(e) => setDays(Number(e.target.value))} className="h-8 w-36 text-xs">{[30, 90, 180, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}</Select>}
    </div>
  );
}

function Directory() {
  const [dept, setDept] = useState(""); const [project, setProject] = useState(""); const [q, setQ] = useState("");
  const qs = new URLSearchParams({ ...(dept && { department_id: dept }), ...(project && { project_id: project }), ...(q && { q }) }).toString();
  const { data, error, isLoading, mutate } = useSWR(`/api/employees?${qs}`, fetcher, { keepPreviousData: true });
  return (
    <>
      <Filters {...{ dept, setDept, project, setProject, q, setQ }} />
      <Card>
        {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading && !data ? <LoadingRows /> : !data.length ? <EmptyState title="No employees match" /> : (
          <Table>
            <THead><TR><TH>Employee</TH><TH>Department</TH><TH>Designation</TH><TH className="text-right">Verified tasks</TH><TH className="text-right">Active grants</TH><TH className="text-right">Violations</TH><TH>Status</TH></TR></THead>
            <TBody>
              {data.map((u: any) => (
                <TR key={u.id}>
                  <TD><Link href={`/employees/${u.id}`} className="flex items-center gap-2.5"><Avatar name={u.name} /><div><div className="font-medium hover:text-violet">{u.name}</div><div className="text-2xs text-muted-foreground">{u.employee_id} · {u.email}</div></div></Link></TD>
                  <TD>{u.department}</TD><TD className="text-muted-foreground">{u.designation}</TD>
                  <TD className="text-right tabular">{u.verified_tasks}</TD><TD className="text-right tabular">{u.active_grants}</TD>
                  <TD className={cn("text-right tabular", u.violations && "text-critical font-medium")}>{u.violations}</TD>
                  <TD><StatusBadge status={u.status} /></TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}

function Leaderboard() {
  const [dept, setDept] = useState(""); const [project, setProject] = useState(""); const [days, setDays] = useState(90);
  const qs = new URLSearchParams({ days: String(days), ...(dept && { department_id: dept }), ...(project && { project_id: project }) }).toString();
  const { data, error, isLoading, mutate } = useSWR(`/api/leaderboard?${qs}`, fetcher, { keepPreviousData: true });
  const medal = (rank: number) => rank === 1 ? "text-[#d4a72c]" : rank === 2 ? "text-[#9aa3ad]" : rank === 3 ? "text-[#b87333]" : "";
  return (
    <>
      <Filters {...{ dept, setDept, project, setProject, days, setDays }} />
      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <Card>
          {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading && !data ? <LoadingRows /> : !data.rows.length ? <EmptyState title="No ranked employees" /> : (
            <Table>
              <THead><TR><TH className="w-12">#</TH><TH>Employee</TH><TH>Score</TH><TH className="text-right">Verified tasks</TH><TH className="text-right">On-time</TH><TH className="text-right">Quality</TH><TH className="text-right">Projects</TH><TH className="text-right">Auth. ops</TH></TR></THead>
              <TBody>
                {data.rows.map((r: any) => (
                  <TR key={r.user_id}>
                    <TD className="tabular font-semibold">{r.rank <= 3 ? <Medal className={cn("h-4 w-4", medal(r.rank))} /> : r.rank}</TD>
                    <TD><Link href={`/employees/${r.user_id}`} className="flex items-center gap-2"><Avatar name={r.name} className="h-6 w-6" /><div><div className="font-medium hover:text-violet">{r.name}</div><div className="text-2xs text-muted-foreground">{r.department}</div></div></Link></TD>
                    <TD>
                      <Tip content={<div className="space-y-0.5">{Object.entries(r.breakdown).map(([k, v]: any) => <div key={k} className="flex justify-between gap-4"><span className="capitalize">{k.replace(/_/g, " ")}</span><span className="tabular">{v}</span></div>)}</div>}>
                        <div className="flex w-36 cursor-help items-center gap-2">
                          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-violet" style={{ width: `${r.score}%` }} /></div>
                          <span className="w-9 text-right font-medium tabular">{r.score}</span>
                        </div>
                      </Tip>
                    </TD>
                    <TD className="text-right tabular">{r.verified_tasks}</TD>
                    <TD className="text-right tabular">{Math.round(r.on_time_rate * 100)}%</TD>
                    <TD className="text-right tabular">{r.avg_quality || "—"}</TD>
                    <TD className="text-right tabular">{r.projects}</TD>
                    <TD className="text-right tabular text-muted-foreground">{r.successful_operations}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
        {data && (
          <Card className="h-fit">
            <CardHeader title={<span className="inline-flex items-center gap-1.5"><Info className="h-4 w-4 text-violet" />Methodology</span>} />
            <CardBody className="space-y-3 text-xs">
              <div className="space-y-1">{Object.entries(data.methodology.weights).map(([k, v]: any) => <div key={k} className="flex justify-between"><span className="capitalize text-muted-foreground">{k.replace(/_/g, " ")}</span><span className="font-medium tabular">{v}%</span></div>)}</div>
              <ul className="space-y-1.5 border-t pt-3 text-muted-foreground">{data.methodology.rules.map((r: string) => <li key={r}>• {r}</li>)}</ul>
            </CardBody>
          </Card>
        )}
      </div>
    </>
  );
}

export default function EmployeesPage() {
  return (
    <>
      <PageHeader title="Employee Intelligence" description="Understand what people have actually worked on before deciding whether more access is justified. Performance is shown separately from security risk." />
      <Tabs defaultValue="directory">
        <TabsList><TabsTrigger value="directory">Directory</TabsTrigger><TabsTrigger value="leaderboard"><Trophy className="h-3.5 w-3.5" />Leaderboard</TabsTrigger></TabsList>
        <TabsContent value="directory"><Directory /></TabsContent>
        <TabsContent value="leaderboard"><Leaderboard /></TabsContent>
      </Tabs>
    </>
  );
}
