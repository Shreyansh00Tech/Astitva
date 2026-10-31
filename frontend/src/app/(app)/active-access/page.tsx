"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Copy, Eye, FlaskConical, KeyRound, LayoutPanelLeft, ShieldX, Timer } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn, duration, fmtDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingRows, Mono, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BreakGlassBadge, Perms, SensitivityBadge, StatusBadge } from "@/components/status";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { ManageAccessDialog } from "@/components/manage-access";

function Countdown({ expires }: { expires: string | null }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  if (!expires) return <Badge tone="warning">Standing</Badge>;
  const s = Math.floor((new Date(expires).getTime() - now) / 1000);
  return <span className={cn("inline-flex items-center gap-1 tabular text-xs", s < 3600 ? "text-critical" : s < 86400 ? "text-warning" : "text-muted-foreground")}><Timer className="h-3.5 w-3.5" />{duration(s)}</span>;
}

function TokenDialog({ grant, onClose }: { grant: any; onClose: () => void }) {
  const [tok, setTok] = useState<any>(null);
  const [action, setAction] = useState(grant.permissions[0]);
  const [purpose, setPurpose] = useState(grant.purpose);
  const [custom, setCustom] = useState("");
  const [result, setResult] = useState<any>(null);
  const { data: catalog } = useSWR("/api/catalog", fetcher);
  useEffect(() => { api(`/api/grants/${grant.id}/token/reveal`, { method: "POST" }).then(setTok).catch((e) => toast.error(errorMessage(e))); }, [grant.id]);
  const test = async () => {
    setResult(null);
    try {
      const r = await api(`/api/gateway/resources/${grant.resource.id}/access`, { json: { action, purpose }, headers: { "X-Access-Token": custom || tok.token } });
      setResult({ ok: true, ...r });
    } catch (e: any) { setResult({ ok: false, ...(e.data?.detail || { message: errorMessage(e) }) }); }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Purpose-bound access token" description={`${grant.resource.name} · ${grant.purpose_label}`} wide>
        {!tok ? <LoadingRows rows={2} /> : (
          <div className="space-y-4">
            <div className="rounded-lg border bg-[#0b0d14] p-4 text-white">
              <div className="flex items-center justify-between"><span className="text-2xs uppercase tracking-wider text-white/50">Simulated token · shown to you only · audited</span>
                <button onClick={() => { navigator.clipboard.writeText(tok.token); toast.success("Copied"); }} className="text-white/60 hover:text-white"><Copy className="h-3.5 w-3.5" /></button></div>
              <div className="mt-2 break-all font-mono text-sm"><span className="text-[#a99bff]">{tok.token_hint}</span><span className="text-white/40">{tok.token.slice(tok.token_hint.length)}</span></div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-2xs text-white/60 sm:grid-cols-4">
                <div>Purpose<div className="text-white">{tok.purpose}</div></div>
                <div>Permissions<div className="text-white">{tok.permissions.join(", ")}</div></div>
                <div>Expires<div className="text-white">{fmtDate(tok.expires_at)}</div></div>
                <div>Approval<div className="truncate text-white">{tok.approval_ref || "—"}</div></div>
              </div>
            </div>
            <div className="rounded-lg border p-3">
              <div className="mb-3 flex items-center gap-1.5 text-[13px] font-medium"><FlaskConical className="h-4 w-4 text-violet" />Call the protected resource</div>
              <p className="mb-3 text-xs text-muted-foreground">The gateway validates identity, resource, purpose, permission, expiry and revocation on every call. Try a different purpose or permission to see it refuse.</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Action"><Select value={action} onChange={(e) => setAction(e.target.value)}>{["READ", "EXECUTE", "WRITE", "DELETE", "ADMIN"].map((p) => <option key={p}>{p}</option>)}</Select></Field>
                <Field label="Declared purpose"><Select value={purpose} onChange={(e) => setPurpose(e.target.value)}>{catalog?.purposes.map((p: any) => <option key={p.code} value={p.code}>{p.label}</option>)}</Select></Field>
              </div>
              <Field label="Token override (optional)" className="mt-3"><Input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Paste another token to test identity/resource binding" className="font-mono text-xs" /></Field>
              <div className="mt-3 flex justify-end"><Button onClick={test}>Send request</Button></div>
              {result && (
                <div className={cn("mt-3 rounded-md border p-3 text-xs animate-fade-in", result.ok ? "border-success/40 bg-success/5" : "border-critical/40 bg-critical/5")}>
                  <div className="flex items-center gap-2 font-medium"><StatusBadge status={result.ok ? "ALLOWED" : "DENIED"} /><Mono>{result.code}</Mono></div>
                  <p className="mt-1">{result.message}</p>
                  {result.data && <pre className="mt-2 max-h-40 overflow-auto rounded bg-muted p-2 font-mono text-2xs scroll-thin">{JSON.stringify(result.data, null, 2)}</pre>}
                </div>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function ActiveAccess() {
  const { can, me } = useSession();
  const [scope, setScope] = useState("mine");
  const [status, setStatus] = useState("ACTIVE");
  const [tokenFor, setTokenFor] = useState<any>(null);
  const [revoke, setRevoke] = useState<any>(null);
  const { data, error, isLoading, mutate } = useSWR(`/api/grants?scope=${scope}&status=${status}`, fetcher);
  return (
    <>
      <PageHeader title="Active access" description="Every grant is bound to a person, resource, purpose, permission set and expiry. Expired or revoked access is rejected immediately." />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tabs value={scope} onValueChange={setScope}>
          <TabsList>
            <TabsTrigger value="mine">My access</TabsTrigger>
            {can("grants:read_team") && <TabsTrigger value="team">My team</TabsTrigger>}
            {can("grants:read_resource") && <TabsTrigger value="owned">My resources</TabsTrigger>}
            {can("grants:read_all") && <TabsTrigger value="all">Organisation</TabsTrigger>}
          </TabsList>
        </Tabs>
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 w-36 text-xs">
          {["ACTIVE", "EXPIRED", "REVOKED", "ALL"].map((s) => <option key={s} value={s}>{s.toLowerCase()}</option>)}
        </Select>
      </div>
      <Card>
        {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading ? <LoadingRows /> : !data.length ? <EmptyState icon={KeyRound} title="No grants" description="Approved requests appear here with their purpose-bound token." /> : (
          <Table>
            <THead><TR>{scope !== "mine" && <TH>Employee</TH>}<TH>Resource</TH><TH>Permissions</TH><TH>Purpose</TH><TH>Token</TH><TH>Remaining</TH><TH>Last used</TH><TH>Status</TH><TH className="text-right">Actions</TH></TR></THead>
            <TBody>
              {data.map((g: any) => (
                <TR key={g.id}>
                  {scope !== "mine" && <TD className="whitespace-nowrap font-medium">{g.user.name}</TD>}
                  <TD><div className="flex items-center gap-1.5 whitespace-nowrap">{g.user.id === me?.id && g.status === "ACTIVE" ? <Link href={`/active-access/${g.resource.id}`} className="font-medium hover:text-violet hover:underline">{g.resource.name}</Link> : g.resource.name}{g.is_emergency && <BreakGlassBadge />}</div><SensitivityBadge level={g.resource.sensitivity} /></TD>
                  <TD><Perms perms={g.permissions} /></TD>
                  <TD className="text-muted-foreground">{g.purpose_label}</TD>
                  <TD>{g.token_hint ? <Mono className="text-violet">{g.token_hint}</Mono> : <span className="text-2xs text-muted-foreground">{g.source === "LEGACY" ? "standing (no token)" : "—"}</span>}</TD>
                  <TD>{g.status === "ACTIVE" ? <Countdown expires={g.expires_at} /> : <span className="text-xs text-muted-foreground">{fmtDate(g.revoked_at || g.expires_at)}</span>}</TD>
                  <TD className="whitespace-nowrap text-xs text-muted-foreground">{fmtDate(g.last_used_at)}</TD>
                  <TD><StatusBadge status={g.status} />{g.status === "REVOKED" && (g.revoked_by || g.revoke_reason) && <div className="mt-1 max-w-[180px] text-2xs text-muted-foreground">{g.revoked_by ? `by ${g.revoked_by.name.split(" ")[0]}` : ""}{g.revoke_reason ? ` · ${g.revoke_reason}` : ""}</div>}</TD>
                  <TD className="text-right">
                    <div className="flex justify-end gap-1">
                      {g.user.id === me?.id && g.status === "ACTIVE" && <Button size="sm" asChild><Link href={`/active-access/${g.resource.id}`}><LayoutPanelLeft />Open</Link></Button>}
                      {g.user.id === me?.id && g.status === "ACTIVE" && g.token_hint && <Button size="sm" variant="outline" onClick={() => setTokenFor(g)}><Eye />Token</Button>}
                      {g.status === "ACTIVE" && g.can_manage && <Button size="sm" variant="outline" className="text-critical" onClick={() => setRevoke(g)}><ShieldX />{g.user.id === me?.id ? "Remove" : "Revoke"}</Button>}
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      {tokenFor && <TokenDialog grant={tokenFor} onClose={() => setTokenFor(null)} />}
      {revoke && <ManageAccessDialog self={revoke.user.id === me?.id} grant={{ id: revoke.id, permissions: revoke.permissions, userName: revoke.user.name, resourceName: revoke.resource.name }}
        onClose={() => setRevoke(null)} onDone={() => { setRevoke(null); mutate(); }} />}
    </>
  );
}
