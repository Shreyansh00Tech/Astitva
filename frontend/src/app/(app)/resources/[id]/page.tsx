"use client";

import Link from "next/link";
import { use, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { ArrowLeft, Settings2 } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { fmtDate, titleCase } from "@/lib/utils";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, KV, Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BreakGlassBadge, Perms, SensitivityBadge, StatusBadge } from "@/components/status";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/input";
import { cn } from "@/lib/utils";

function PolicyEditor({ r, onSaved }: { r: any; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const { data: catalog } = useSWR(open ? "/api/catalog" : null, fetcher);
  const [f, setF] = useState({ max_duration_hours: r.max_duration_hours, allowed_purposes: r.allowed_purposes.map((p: any) => p.code), allowed_departments: r.allowed_departments, available_permissions: r.available_permissions, breakglass_allowed: r.breakglass_allowed, requires_risk_review: r.requires_risk_review });
  const toggle = (k: "allowed_purposes" | "allowed_departments" | "available_permissions", v: string) => setF({ ...f, [k]: f[k].includes(v) ? f[k].filter((x: string) => x !== v) : [...f[k], v] });
  const save = async () => { try { await api(`/api/resources/${r.id}`, { method: "PATCH", json: f }); toast.success("Policy updated"); setOpen(false); onSaved(); } catch (e) { toast.error(errorMessage(e)); } };
  const chip = (on: boolean) => cn("rounded-md border px-2 py-1 text-2xs", on ? "border-violet bg-violet/10 text-violet" : "text-muted-foreground");
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}><Settings2 />Edit access policy</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Resource access policy" description="Enforced by the backend on requests and on every gateway call." wide>
          <div className="space-y-4">
            <Field label="Maximum grant duration"><Select value={f.max_duration_hours} onChange={(e) => setF({ ...f, max_duration_hours: Number(e.target.value) })}>{[8, 24, 48, 72, 168, 336, 720].map((h) => <option key={h} value={h}>{h}h</option>)}</Select></Field>
            <Field label="Available permissions"><div className="flex flex-wrap gap-1.5">{["READ", "EXECUTE", "WRITE", "DELETE", "ADMIN"].map((p) => <button key={p} className={chip(f.available_permissions.includes(p))} onClick={() => toggle("available_permissions", p)}>{p}</button>)}</div></Field>
            <Field label="Approved purposes"><div className="flex flex-wrap gap-1.5">{catalog?.purposes.map((p: any) => <button key={p.code} className={chip(f.allowed_purposes.includes(p.code))} onClick={() => toggle("allowed_purposes", p.code)}>{p.label}</button>)}</div></Field>
            <Field label="Restrict to departments (empty = any)"><div className="flex flex-wrap gap-1.5">{["ENG", "FIN", "HR", "SEC", "DS"].map((d) => <button key={d} className={chip(f.allowed_departments.includes(d))} onClick={() => toggle("allowed_departments", d)}>{d}</button>)}</div></Field>
            <div className="flex gap-6 text-[13px]">
              <label className="flex items-center gap-2"><input type="checkbox" checked={f.requires_risk_review} onChange={(e) => setF({ ...f, requires_risk_review: e.target.checked })} />Always require risk review</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={f.breakglass_allowed} onChange={(e) => setF({ ...f, breakglass_allowed: e.target.checked })} />Allow break-glass</label>
            </div>
            <div className="flex justify-end"><Button onClick={save}>Save policy</Button></div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function ResourceDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: r, error, mutate } = useSWR(`/api/resources/${id}`, fetcher);
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (!r) return <Skeleton className="h-96" />;
  return (
    <div className="animate-fade-in">
      <Link href="/resources" className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />Resource registry</Link>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2"><h1 className="text-xl font-semibold tracking-tight">{r.name}</h1><SensitivityBadge level={r.sensitivity} /></div>
          <p className="mt-1 text-[13px] text-muted-foreground"><span className="font-mono">{r.code}</span> · {titleCase(r.type)} · {r.department} · {r.description}</p>
        </div>
        {r.can_manage && <PolicyEditor r={r} onSaved={() => mutate()} />}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="h-fit">
          <CardHeader title="Access policy" />
          <CardBody>
            <KV k="Owner" v={r.owner.name} />
            <KV k="Available permissions" v={<Perms perms={r.available_permissions} />} />
            <KV k="Max duration" v={`${r.max_duration_hours}h`} />
            <KV k="Departments" v={r.allowed_departments.length ? r.allowed_departments.join(", ") : "Any"} />
            <KV k="Security review" v="Always (after the Manager)" />
            <KV k="Break-glass" v={r.breakglass_allowed ? "Allowed" : "Not allowed"} />
            <div className="mt-2 border-t pt-2"><div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Approved purposes</div><div className="flex flex-wrap gap-1">{r.allowed_purposes.map((p: any) => <Badge key={p.code} tone="outline">{p.label}</Badge>)}</div></div>
            {r.policies?.length > 0 && <div className="mt-3 border-t pt-2"><div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Attached policies</div>{r.policies.map((p: any) => <div key={p.id} className="text-xs">{p.name}</div>)}</div>}
          </CardBody>
        </Card>
        <Card className="lg:col-span-2">
          {!r.grants ? <EmptyState title={`${r.active_grants} active grants`} description="Grant details and access history are visible to the Security Manager." /> : (
            <Tabs defaultValue="grants" className="p-4">
              <TabsList><TabsTrigger value="grants">Grants ({r.grants.length})</TabsTrigger><TabsTrigger value="history">Access history</TabsTrigger></TabsList>
              <TabsContent value="grants">
                <Table><THead><TR><TH>Employee</TH><TH>Permissions</TH><TH>Purpose</TH><TH>Expires</TH><TH>Status</TH></TR></THead>
                  <TBody>{r.grants.map((g: any) => <TR key={g.id}><TD className="whitespace-nowrap">{g.user.name}{g.is_emergency && <span className="ml-1.5"><BreakGlassBadge /></span>}</TD><TD><Perms perms={g.permissions} /></TD><TD className="text-muted-foreground">{g.purpose_label}</TD><TD className="whitespace-nowrap text-muted-foreground">{g.expires_at ? fmtDate(g.expires_at) : "Never"}</TD><TD><StatusBadge status={g.status} /></TD></TR>)}</TBody></Table>
              </TabsContent>
              <TabsContent value="history">
                <Table><THead><TR><TH>When</TH><TH>Identity</TH><TH>Action</TH><TH>Purpose</TH><TH>Outcome</TH><TH>Reason</TH></TR></THead>
                  <TBody>{r.access_history.map((e: any, i: number) => <TR key={i}><TD className="whitespace-nowrap text-muted-foreground">{fmtDate(e.at)}</TD><TD className="whitespace-nowrap">{e.who}{e.agent && <Badge tone="violet" className="ml-1.5">Agent</Badge>}</TD><TD className="font-mono text-xs">{e.action}</TD><TD className="text-muted-foreground">{titleCase(e.purpose)}</TD><TD><StatusBadge status={e.outcome} /></TD><TD className="max-w-[240px] truncate text-xs text-muted-foreground">{e.reason}</TD></TR>)}</TBody></Table>
              </TabsContent>
            </Tabs>
          )}
        </Card>
      </div>
    </div>
  );
}
