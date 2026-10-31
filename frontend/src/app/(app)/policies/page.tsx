"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { FileClock, Gauge, Lock, Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { ROLE_LABEL } from "@/lib/session";
import { fmtDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingRows, Mono, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { SensitivityBadge } from "@/components/status";

const KINDS: Record<string, string> = {
  ROLE_CONFLICT: "Role conflict: holders of all listed roles may not act on the listed stages",
  STAGE_CONFLICT: "Stage conflict: one person may not approve both stages in the pair",
  DEPARTMENT_CONFLICT: "Department conflict: reviewer must be outside the requester's department",
  RESOURCE_SENSITIVITY_DUAL_CONTROL: "Dual control: owner stage needs the primary owner for listed sensitivities",
};
const STAGES = ["MANAGER", "RISK", "OWNER"];
const ROLES = ["REQUESTER", "MANAGER", "RISK_REVIEWER", "RESOURCE_OWNER", "SECURITY_ADMIN"];
const SENS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "CRITICAL"];

function Chips({ options, value, onChange, label = (x: string) => x }: { options: string[]; value: string[]; onChange: (v: string[]) => void; label?: (x: string) => string }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button type="button" key={o} onClick={() => onChange(on ? value.filter((v) => v !== o) : [...value, o])}
            className={`rounded-md border px-2 py-1 text-xs transition-colors ${on ? "border-violet bg-violet/10 text-violet" : "text-muted-foreground hover:bg-accent"}`}>
            {label(o)}
          </button>
        );
      })}
    </div>
  );
}

function PolicyDialog({ initial, resources, onClose, onSaved }: { initial: any; resources: any[]; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(initial?.name || "");
  const [type, setType] = useState(initial?.policy_type || "SOD");
  const [description, setDescription] = useState(initial?.description || "");
  const [resourceId, setResourceId] = useState(initial?.resource?.id || "");
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const r = initial?.rules || {};
  const [kind, setKind] = useState(r.kind || "ROLE_CONFLICT");
  const [roles, setRoles] = useState<string[]>(r.roles || []);
  const [stages, setStages] = useState<string[]>(r.stages || []);
  const [pair, setPair] = useState<string[]>(r.pair || []);
  const [sens, setSens] = useState<string[]>(r.sensitivities || []);
  const [message, setMessage] = useState(r.message || "");
  const [raw, setRaw] = useState(type !== "SOD" ? JSON.stringify(r, null, 2) : "{}");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    let rules: any;
    if (type === "SOD") {
      rules = { kind, ...(message ? { message } : {}) };
      if (kind === "ROLE_CONFLICT") Object.assign(rules, { roles, stages });
      if (kind === "STAGE_CONFLICT") Object.assign(rules, { pair });
      if (kind === "DEPARTMENT_CONFLICT") Object.assign(rules, { stages });
      if (kind === "RESOURCE_SENSITIVITY_DUAL_CONTROL") Object.assign(rules, { sensitivities: sens });
    } else {
      try { rules = JSON.parse(raw || "{}"); } catch { toast.error("Rules must be valid JSON"); return; }
    }
    setBusy(true);
    try {
      const body = { name, policy_type: type, description: description || null, resource_id: resourceId || null, rules, enabled };
      if (initial?.id) await api(`/api/policies/${initial.id}`, { method: "PUT", json: body });
      else await api("/api/policies", { json: body });
      toast.success("Policy saved and audited");
      onSaved();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={initial?.id ? "Edit policy" : "New policy"} description="Policies are evaluated on the server on every approval action." wide>
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Type"><Select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="SOD">Separation of duties</option><option value="ABAC">Attribute-based (ABAC)</option><option value="GLOBAL">Global</option>
            </Select></Field>
          </div>
          <Field label="Description"><Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
          {type === "SOD" ? (
            <div className="space-y-3 rounded-lg border p-3">
              <Field label="Rule kind"><Select value={kind} onChange={(e) => setKind(e.target.value)}>
                {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select></Field>
              {kind === "ROLE_CONFLICT" && <Field label="Conflicting roles (held together)"><Chips options={ROLES} value={roles} onChange={setRoles} label={(x) => ROLE_LABEL[x] || x} /></Field>}
              {(kind === "ROLE_CONFLICT" || kind === "DEPARTMENT_CONFLICT") && <Field label="Applies to stages" hint="None selected means all stages"><Chips options={STAGES} value={stages} onChange={setStages} /></Field>}
              {kind === "STAGE_CONFLICT" && <Field label="Stage pair"><Chips options={STAGES} value={pair} onChange={setPair} /></Field>}
              {kind === "RESOURCE_SENSITIVITY_DUAL_CONTROL" && <Field label="Sensitivities"><Chips options={SENS} value={sens} onChange={setSens} /></Field>}
              <Field label="Message shown when blocked (optional)"><Input value={message} onChange={(e) => setMessage(e.target.value)} /></Field>
            </div>
          ) : (
            <Field label="Rules (JSON)"><Textarea rows={6} value={raw} onChange={(e) => setRaw(e.target.value)} className="font-mono text-xs" /></Field>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Scope to resource (optional)"><Select value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
              <option value="">All resources</option>{resources.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </Select></Field>
            <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />Enabled</label>
          </div>
          <div className="flex justify-end gap-2"><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={save} disabled={busy || name.length < 3}>Save policy</Button></div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function describeRules(p: any) {
  const r = p.rules || {};
  if (p.policy_type !== "SOD") return <Mono className="text-2xs break-all">{JSON.stringify(r)}</Mono>;
  const bits = [r.kind?.replaceAll("_", " ").toLowerCase()];
  if (r.roles?.length) bits.push(`roles: ${r.roles.map((x: string) => ROLE_LABEL[x] || x).join(" + ")}`);
  if (r.stages?.length) bits.push(`stages: ${r.stages.join(", ")}`);
  if (r.pair?.length) bits.push(`pair: ${r.pair.join(" / ")}`);
  if (r.sensitivities?.length) bits.push(`sensitivities: ${r.sensitivities.join(", ")}`);
  return <span className="text-xs text-muted-foreground">{bits.join(" · ")}</span>;
}

function RoutingCard({ policy, canManage, onSaved }: { policy: any; canManage: boolean; onSaved: () => void }) {
  const r = policy?.rules || {};
  const [auto, setAuto] = useState<number>(r.auto_approve_max_score ?? 30);
  const [mgr, setMgr] = useState<number>(r.manager_only_max_score ?? 60);
  const [busy, setBusy] = useState(false);
  const enabled = !!policy?.enabled;
  const dirty = auto !== (r.auto_approve_max_score ?? 30) || mgr !== (r.manager_only_max_score ?? 60);
  const invalid = auto < -1 || mgr > 100 || auto > mgr;
  const save = async () => {
    setBusy(true);
    try {
      await api(`/api/policies/${policy.id}`, { method: "PUT", json: { name: policy.name, policy_type: policy.policy_type, description: policy.description, resource_id: policy.resource?.id || null, rules: { ...r, auto_approve_max_score: auto, manager_only_max_score: mgr }, enabled: policy.enabled } });
      toast.success("Routing thresholds saved and audited"); onSaved();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  const pct = (n: number) => `${Math.max(0, Math.min(100, n + 1))}%`;
  const bands = [
    { label: "Auto-approved by policy", range: auto < 0 ? "off" : `0–${auto}`, cls: "bg-success", w: pct(auto) },
    { label: "Manager only", range: mgr <= auto ? "–" : `${auto + 1}–${mgr}`, cls: "bg-violet", w: `${Math.max(0, mgr - auto)}%` },
    { label: "Manager + Security Manager", range: mgr >= 100 ? "–" : `${mgr + 1}–100`, cls: "bg-critical", w: `${Math.max(0, 100 - mgr)}%` },
  ];
  if (!policy) return (
    <Card className="mb-4 p-4"><div className="flex items-center gap-2 text-[13px] font-medium"><Gauge className="h-4 w-4 text-violet" />Risk-based routing is not configured</div>
      <p className="mt-1 text-xs text-muted-foreground">Every request needs both Manager and Security Manager approval. Reseed or add a GLOBAL policy with auto_approve_max_score and manager_only_max_score.</p></Card>
  );
  return (
    <Card className="mb-4">
      <CardHeader title={<span className="flex items-center gap-2"><Gauge className="h-4 w-4 text-violet" />Risk-based approval routing {enabled ? <Badge tone="success">Enabled</Badge> : <Badge tone="outline">Disabled</Badge>}</span>}
        description="Decided on the server from the rule-based risk score. The AI model never grants access. Auto-approvals are audited as 'auto-approved by policy' and the manager is notified." />
      <div className="space-y-4 border-t px-4 py-4">
        <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted">
          {bands.map((b) => <span key={b.label} className={`${b.cls} h-full transition-[width] duration-500 ease-out motion-reduce:transition-none`} style={{ width: b.w }} />)}
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {bands.map((b) => (
            <div key={b.label} className="flex items-center gap-2 text-xs"><span className={`h-2.5 w-2.5 shrink-0 rounded-full ${b.cls}`} /><span className="text-foreground">{b.label}</span><span className="tabular ml-auto text-muted-foreground">{b.range}</span></div>
          ))}
        </div>
        {canManage && (
          <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <Field label="Auto-approve up to score" hint="-1 turns auto-approval off"><Input type="number" min={-1} max={100} value={auto} onChange={(e) => setAuto(parseInt(e.target.value || "0", 10))} /></Field>
            <Field label="Manager only up to score" hint="Above this, both approvals"><Input type="number" min={0} max={100} value={mgr} onChange={(e) => setMgr(parseInt(e.target.value || "0", 10))} /></Field>
            <Button onClick={save} loading={busy} disabled={!dirty || invalid}>Save thresholds</Button>
          </div>
        )}
        {invalid && <p className="text-xs text-critical">Auto-approve threshold must be lower than or equal to the manager-only threshold (range -1 to 100).</p>}
        <div className="rounded-md border border-violet/25 bg-violet/[0.05] p-3">
          <div className="flex items-center gap-1.5 text-xs font-medium"><ShieldCheck className="h-3.5 w-3.5 text-violet" />Always a human decision, whatever the score (cannot be turned off)</div>
          <ul className="mt-1.5 grid gap-1 text-xs text-muted-foreground sm:grid-cols-3">
            <li>• {(r.auto_approve_excluded_sensitivities || ["CONFIDENTIAL", "RESTRICTED", "CRITICAL"]).map((x: string) => x[0] + x.slice(1).toLowerCase()).join(", ")} resources</li>
            <li>• WRITE, DELETE or ADMIN permissions</li>
            <li>• Unusual behaviour: also needs the Security Manager</li>
          </ul>
        </div>
      </div>
    </Card>
  );
}

export default function Policies() {
  const { data, error, isLoading, mutate } = useSWR("/api/policies", fetcher);
  const [edit, setEdit] = useState<any>(null);
  const toggle = async (p: any) => {
    try { await api(`/api/policies/${p.id}`, { method: "PUT", json: { name: p.name, policy_type: p.policy_type, description: p.description, resource_id: p.resource?.id || null, rules: p.rules, enabled: !p.enabled } }); mutate(); toast.success(p.enabled ? "Policy disabled" : "Policy enabled"); }
    catch (e) { toast.error(errorMessage(e)); }
  };
  const remove = async (p: any) => {
    if (!confirm(`Delete policy "${p.name}"? This is audited.`)) return;
    try { await api(`/api/policies/${p.id}`, { method: "DELETE" }); mutate(); toast.success("Policy deleted"); } catch (e) { toast.error(errorMessage(e)); }
  };
  const routing = data?.policies?.find((p: any) => p.policy_type === "GLOBAL" && p.rules && "auto_approve_max_score" in p.rules);
  if (error) return <><PageHeader title="Policies" /><Card><ErrorState error={error} onRetry={() => mutate()} /></Card></>;
  return (
    <>
      <PageHeader title="Policies" description="Separation of duties, attribute-based rules and per-resource constraints. All enforcement happens in the backend."
        actions={data?.can_manage && <Button onClick={() => setEdit({})}><Plus />New policy</Button>} />
      {isLoading ? <Card><LoadingRows /></Card> : (<>
        <RoutingCard key={routing?.updated_at || "none"} policy={routing} canManage={!!data.can_manage} onSaved={() => mutate()} />
        <Tabs defaultValue="custom">
          <TabsList>
            <TabsTrigger value="custom">Admin policies ({data.policies.length})</TabsTrigger>
            <TabsTrigger value="builtin">Built-in SoD rules</TabsTrigger>
            <TabsTrigger value="resources">Resource constraints</TabsTrigger>
          </TabsList>
          <TabsContent value="custom">
            <Card>
              {!data.policies.length ? <EmptyState icon={FileClock} title="No custom policies" /> : (
                <Table>
                  <THead><TR><TH>Policy</TH><TH>Type</TH><TH>Rule</TH><TH>Scope</TH><TH>Updated</TH><TH>Status</TH>{data.can_manage && <TH className="text-right">Actions</TH>}</TR></THead>
                  <TBody>
                    {data.policies.map((p: any) => (
                      <TR key={p.id}>
                        <TD><div className="font-medium">{p.name}</div>{p.description && <div className="max-w-sm text-xs text-muted-foreground">{p.description}</div>}</TD>
                        <TD><Badge tone={p.policy_type === "SOD" ? "violet" : "info"}>{p.policy_type}</Badge></TD>
                        <TD className="max-w-xs">{describeRules(p)}</TD>
                        <TD className="text-xs text-muted-foreground">{p.resource?.name || "All resources"}</TD>
                        <TD className="whitespace-nowrap text-xs text-muted-foreground">{fmtDate(p.updated_at)}</TD>
                        <TD>{p.enabled ? <Badge tone="success">Enabled</Badge> : <Badge tone="outline">Disabled</Badge>}</TD>
                        {data.can_manage && <TD className="text-right"><div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => toggle(p)}>{p.enabled ? "Disable" : "Enable"}</Button>
                          <Button size="icon" variant="ghost" aria-label="Edit" onClick={() => setEdit(p)}><Pencil /></Button>
                          <Button size="icon" variant="ghost" aria-label="Delete" className="text-critical" onClick={() => remove(p)}><Trash2 /></Button>
                        </div></TD>}
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </Card>
          </TabsContent>
          <TabsContent value="builtin">
            <Card>
              <CardHeader title="Always-on rules" description="These cannot be disabled. They run before any admin-defined policy." />
              <div className="divide-y border-t">
                {data.builtin_sod_rules.map((r: any) => (
                  <div key={r.code} className="flex items-start gap-3 px-4 py-3"><Lock className="mt-0.5 h-4 w-4 shrink-0 text-violet" />
                    <div><Mono className="text-xs">{r.code}</Mono><p className="mt-0.5 text-sm text-muted-foreground">{r.description}</p></div></div>
                ))}
              </div>
            </Card>
          </TabsContent>
          <TabsContent value="resources">
            <Card>
              <Table>
                <THead><TR><TH>Resource</TH><TH>Sensitivity</TH><TH>Max duration</TH><TH>Departments (ABAC)</TH><TH>Purposes</TH><TH>Security review</TH><TH>Break-glass</TH></TR></THead>
                <TBody>
                  {data.resources.map((r: any) => (
                    <TR key={r.id}>
                      <TD><div className="font-medium">{r.name}</div><Mono className="text-2xs text-muted-foreground">{r.code}</Mono></TD>
                      <TD><SensitivityBadge level={r.sensitivity} /></TD>
                      <TD className="tabular text-xs">{r.max_duration_hours}h</TD>
                      <TD className="text-xs">{r.allowed_departments?.length ? r.allowed_departments.join(", ") : <span className="text-muted-foreground">Any</span>}</TD>
                      <TD className="max-w-[220px] text-xs text-muted-foreground">{r.allowed_purposes?.length ? r.allowed_purposes.join(", ") : "Any"}</TD>
                      <TD>{!routing?.enabled ? <Badge tone="warning">Always</Badge> : <Badge tone="warning">Risk &gt; {routing.rules.manager_only_max_score}</Badge>}</TD>
                      <TD>{r.breakglass_allowed ? <Badge tone="serious">Allowed</Badge> : <Badge tone="outline">No</Badge>}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </Card>
          </TabsContent>
        </Tabs>
      </>)}
      {edit && <PolicyDialog initial={edit.id ? edit : null} resources={data?.resources || []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); mutate(); }} />}
    </>
  );
}
