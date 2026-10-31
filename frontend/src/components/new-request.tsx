"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Info } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { SensitivityBadge } from "@/components/status";
import { cn } from "@/lib/utils";

const IMPACT_HELP: Record<string, string> = {
  LOW: "Nice to have. Work can continue without it.",
  MEDIUM: "Normal work. A short delay is acceptable.",
  HIGH: "Important work for a team or customer is blocked.",
  CRITICAL: "Business-critical: an outage, legal or customer deadline depends on it.",
};
function minLocal() {
  const d = new Date(Date.now() + 5 * 60000);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function NewRequestDialog({ open, onOpenChange, onCreated, presetResource }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated?: (r: any) => void; presetResource?: string }) {
  const { data: resources } = useSWR(open ? "/api/resources" : null, fetcher);
  const { data: catalog } = useSWR(open ? "/api/catalog" : null, fetcher);
  const [resourceId, setResourceId] = useState(presetResource || "");
  const [perms, setPerms] = useState<string[]>(["READ"]);
  const [purpose, setPurpose] = useState("");
  const [hours, setHours] = useState(24);
  const [why, setWhy] = useState("");
  const [deadline, setDeadline] = useState("");
  const [impact, setImpact] = useState("MEDIUM");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (presetResource) setResourceId(presetResource); }, [presetResource]);
  const res = useMemo(() => resources?.find((r: any) => r.id === resourceId), [resources, resourceId]);
  useEffect(() => { if (res) { setPerms(["READ"].filter((p) => res.available_permissions.includes(p))); setPurpose(res.allowed_purposes[0]?.code || ""); } }, [res]);
  const purposeInfo = catalog?.purposes.find((p: any) => p.code === purpose);
  const strong = perms.filter((p) => !["READ", "EXECUTE"].includes(p));
  const needsHuman = res && ["CONFIDENTIAL", "RESTRICTED", "CRITICAL"].includes(res.sensitivity)
    ? `${res.name} is ${res.sensitivity.toLowerCase()}.`
    : strong.length ? `${strong.join(", ")} can change or delete data.` : "";

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const deadline_at = deadline ? new Date(deadline).toISOString() : null; // local time -> UTC with timezone
      const r = await api("/api/requests", { json: { resource_id: resourceId, permissions: perms, purpose, justification: why, duration_hours: hours, deadline_at, business_impact: impact } });
      toast.success(r.status === "APPROVED" ? `${r.ref} approved automatically · risk ${r.risk?.score}` : `${r.ref} submitted · risk ${r.risk?.score} (${r.risk?.level}) · sent for approval`);
      onCreated?.(r);
      onOpenChange(false);
      setWhy(""); setDeadline(""); setImpact("MEDIUM");
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Request access" description="Requests are risk-scored and routed for independent approval. Approved access is purpose-bound and time-limited." wide>
        <div className="space-y-4">
          <Field label="Resource">
            <Select value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
              <option value="">Select a resource…</option>
              {resources?.map((r: any) => <option key={r.id} value={r.id}>{r.name} · {r.sensitivity}</option>)}
            </Select>
          </Field>
          {res && (
            <div className="rounded-md border bg-muted/30 p-3 text-xs">
              <div className="flex items-center justify-between"><span className="font-medium">{res.code} · {res.type.replace("_", " ")}</span><SensitivityBadge level={res.sensitivity} /></div>
              <p className="mt-1 text-muted-foreground">{res.description}</p>
              <p className="mt-1 text-muted-foreground">Owner: {res.owner?.name} · Max duration {res.max_duration_hours}h{res.allowed_departments.length ? ` · Restricted to ${res.allowed_departments.join(", ")}` : ""}</p>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Purpose" hint={purposeInfo ? `Least privilege for this purpose: ${purposeInfo.least_privilege.join(", ")}` : undefined}>
              <Select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
                {catalog?.purposes.map((p: any) => <option key={p.code} value={p.code}>{p.label}{res && !res.allowed_purposes.some((a: any) => a.code === p.code) ? " (not standard for this resource)" : ""}</option>)}
              </Select>
            </Field>
            <Field label="Duration">
              <Select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
                {[4, 8, 24, 48, 72, 168, 336, 720].map((h) => <option key={h} value={h}>{h < 48 ? `${h} hours` : `${h / 24} days`}</option>)}
              </Select>
            </Field>
          </div>
          <Field label="Permissions">
            <div className="flex flex-wrap gap-1.5">
              {(res?.available_permissions || ["READ", "EXECUTE", "WRITE", "DELETE", "ADMIN"]).map((p: string) => {
                const on = perms.includes(p);
                return (
                  <button key={p} type="button" disabled={!res} onClick={() => setPerms(on ? perms.filter((x) => x !== p) : [...perms, p])}
                    className={cn("rounded-md border px-2.5 py-1 font-mono text-xs transition-colors disabled:opacity-40",
                      on ? "border-violet bg-violet/10 text-violet" : "text-muted-foreground hover:bg-accent")}>{p}</button>
                );
              })}
            </div>
          </Field>
          <div className="grid gap-4 sm:grid-cols-[1fr_1.4fr]">
            <Field label="Needed by (optional)" hint={deadline && new Date(deadline) <= new Date() ? "The deadline cannot be in the past." : "Your local time. Helps reviewers prioritise; it does not change the risk score."}>
              <Input type="datetime-local" value={deadline} min={minLocal()} onChange={(e) => setDeadline(e.target.value)} />
            </Field>
            <Field label="Business impact" hint={IMPACT_HELP[impact]}>
              <div className="grid grid-cols-4 gap-1 rounded-lg border bg-muted/40 p-1">
                {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((i) => (
                  <button key={i} type="button" onClick={() => setImpact(i)}
                    className={cn("rounded-md px-1.5 py-1.5 text-2xs font-medium transition-all duration-200",
                      impact === i ? "bg-card text-foreground shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-foreground")}>
                    {i[0] + i.slice(1).toLowerCase()}
                  </button>
                ))}
              </div>
            </Field>
          </div>
          <Field label="Business justification" hint="Be specific: ticket, project, dataset scope. Weak justifications raise the risk score.">
            <Textarea value={why} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. Validate the Q3 model build against the audited holdout set for release review REL-482." />
          </Field>
          <div className="flex items-start gap-2 rounded-md bg-violet/[0.06] p-2.5 text-2xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-violet" />
            <span>The AI risk engine explains and recommends. Only deterministic policy and authorized human approvers can grant access.
              {needsHuman && <b className="mt-1 block font-medium text-foreground">{needsHuman} This request will always go to a human approver.</b>}</span>
          </div>
          {error && <p className="rounded-md border border-critical/30 bg-critical/5 px-3 py-2 text-xs text-critical">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button variant="accent" onClick={submit} loading={busy} disabled={!resourceId || !perms.length || why.trim().length < 10}>Submit request</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
