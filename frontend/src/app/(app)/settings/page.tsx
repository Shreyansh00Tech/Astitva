"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Copy, KeyRound, Laptop, LogOut, QrCode, RefreshCw, ShieldCheck, Smartphone } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { ROLE_LABEL, useSession } from "@/lib/session";
import { cn, fmtDate, relTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, ErrorState, KV, LoadingRows, Mono, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { PasswordMeter } from "@/components/password-meter";

const ROLES = ["REQUESTER", "MANAGER", "RISK_REVIEWER", "RESOURCE_OWNER", "SECURITY_ADMIN"];

function CodesBox({ codes }: { codes: string[] }) {
  return (
    <div className="rounded-lg border bg-muted/40 p-3">
      <div className="grid grid-cols-2 gap-1.5 font-mono text-sm">{codes.map((c) => <span key={c}>{c}</span>)}</div>
      <div className="mt-3 flex items-center justify-between">
        <p className="text-2xs text-muted-foreground">Each code works once. Store them somewhere safe. They won&apos;t be shown again.</p>
        <Button size="sm" variant="outline" onClick={() => { navigator.clipboard.writeText(codes.join("\n")); toast.success("Copied"); }}><Copy />Copy</Button>
      </div>
    </div>
  );
}

function Profile() {
  const { me } = useSession();
  if (!me) return <LoadingRows />;
  return (
    <Card>
      <CardBody className="pt-4">
        <div className="mb-4 flex items-center gap-3"><Avatar name={me.name} className="h-11 w-11 text-sm" />
          <div><div className="font-semibold">{me.name}</div><div className="text-xs text-muted-foreground">{me.designation} · {me.department}</div></div></div>
        <div className="grid gap-x-6 sm:grid-cols-2">
          <KV k="Email" v={me.email} /><KV k="Employee ID" v={<Mono>{me.employee_id}</Mono>} />
          <KV k="Manager" v={me.manager?.name || "—"} /><KV k="MFA" v={me.mfa_enabled ? <Badge tone="success">Authenticator app</Badge> : <Badge tone="info">Email code</Badge>} />
          <KV k="Roles" v={<div className="flex flex-wrap justify-end gap-1">{me.roles.map((r) => <Badge key={r} tone="violet">{ROLE_LABEL[r] || r}</Badge>)}</div>} />
          <KV k="Effective permissions" v={<span className="tabular">{me.permissions.length}</span>} />
        </div>
        <p className="mt-4 text-xs text-muted-foreground">Profile details come from the HR directory (simulated). Role changes are made by a Security Manager and force re-authentication.</p>
      </CardBody>
    </Card>
  );
}

function Security() {
  const { me } = useSession();
  const { data: mfa, mutate: refreshMfa } = useSWR("/api/auth/mfa", fetcher);
  const { data: sessions, mutate: refreshSessions } = useSWR("/api/auth/sessions", fetcher);
  const [setup, setSetup] = useState<any>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [pwOk, setPwOk] = useState(false);

  const startTotp = async () => { try { setSetup(await api("/api/auth/mfa/totp/setup", { method: "POST" })); setCode(""); } catch (e) { toast.error(errorMessage(e)); } };
  const confirmTotp = async () => {
    try { const r = await api("/api/auth/mfa/totp/confirm", { json: { code } }); setSetup(null); setCodes(r.backup_codes); refreshMfa(); toast.success("Authenticator app enabled"); }
    catch (e) { toast.error(errorMessage(e)); }
  };
  const regen = async () => {
    if (!confirm("Generate new backup codes? Existing unused codes stop working.")) return;
    try { const r = await api("/api/auth/mfa/backup-codes", { method: "POST" }); setCodes(r.backup_codes); refreshMfa(); } catch (e) { toast.error(errorMessage(e)); }
  };
  const revoke = async (id: string) => { try { await api(`/api/auth/sessions/${id}`, { method: "DELETE" }); refreshSessions(); toast.success("Session signed out"); } catch (e) { toast.error(errorMessage(e)); } };
  const changePw = async () => {
    if (pw.next !== pw.confirm) { toast.error("Passwords don't match"); return; }
    try {
      const r = await api("/api/auth/password/change", { json: { current_password: pw.current, new_password: pw.next } });
      toast.success(`Password changed. ${r.other_sessions_revoked} other session(s) signed out.`); setPw({ current: "", next: "", confirm: "" }); refreshSessions();
    } catch (e) { toast.error(errorMessage(e)); }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Multi-factor authentication" description="Required for every sign-in." />
        <CardBody className="space-y-3">
          {!mfa ? <LoadingRows rows={3} /> : <>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div className="flex items-center gap-2.5"><Smartphone className="h-4 w-4 text-violet" /><div><div className="text-sm font-medium">Authenticator app (TOTP)</div><div className="text-xs text-muted-foreground">Google Authenticator, 1Password, Authy…</div></div></div>
              {mfa.totp_enabled ? <div className="flex items-center gap-2"><Badge tone="success">On</Badge><Button size="sm" variant="ghost" onClick={startTotp}>Replace</Button></div> : <Button size="sm" onClick={startTotp}><QrCode />Set up</Button>}
            </div>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div className="flex items-center gap-2.5"><KeyRound className="h-4 w-4 text-violet" /><div><div className="text-sm font-medium">Backup codes</div><div className="text-xs text-muted-foreground"><span className="tabular">{mfa.backup_codes_remaining}</span> unused</div></div></div>
              <Button size="sm" variant="outline" onClick={regen}><RefreshCw />Regenerate</Button>
            </div>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div className="flex items-center gap-2.5"><ShieldCheck className="h-4 w-4 text-violet" /><div><div className="text-sm font-medium">Email one-time code</div><div className="text-xs text-muted-foreground">Fallback sent to {me?.email}</div></div></div>
              <Badge tone="success">Available</Badge>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-dashed p-3 opacity-70">
              <div className="text-sm">SMS code</div><span className="text-2xs text-muted-foreground">{mfa.sms.note}</span>
            </div>
            {codes && <CodesBox codes={codes} />}
          </>}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Change password" description="Other sessions are signed out after a change." />
        <CardBody className="space-y-3">
          <Field label="Current password"><Input type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></Field>
          <Field label="New password"><Input type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} /></Field>
          <PasswordMeter password={pw.next} email={me?.email} name={me?.name} onChange={setPwOk} />
          <Field label="Confirm new password"><Input type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></Field>
          <div className="flex justify-end"><Button onClick={changePw} disabled={!pw.current || !pwOk || pw.next !== pw.confirm}>Update password</Button></div>
        </CardBody>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader title="Active sessions" description="Each session has its own rotating refresh token. Reuse of an old token revokes the session." />
        {!sessions ? <LoadingRows rows={2} /> : (
          <Table>
            <THead><TR><TH>Device</TH><TH>IP</TH><TH>MFA</TH><TH>Signed in</TH><TH>Last active</TH><TH className="text-right" /></TR></THead>
            <TBody>
              {sessions.map((s: any) => (
                <TR key={s.id}>
                  <TD><div className="flex items-center gap-2"><Laptop className="h-4 w-4 text-muted-foreground" /><span className="max-w-xs truncate text-xs">{s.user_agent || "Unknown client"}</span>{s.current && <Badge tone="violet">This device</Badge>}</div></TD>
                  <TD><Mono className="text-xs">{s.ip || "—"}</Mono></TD>
                  <TD className="text-xs">{s.mfa_method}</TD>
                  <TD className="whitespace-nowrap text-xs text-muted-foreground">{fmtDate(s.created_at)}</TD>
                  <TD className="whitespace-nowrap text-xs text-muted-foreground">{relTime(s.last_seen_at)}</TD>
                  <TD className="text-right">{!s.current && <Button size="sm" variant="ghost" className="text-critical" onClick={() => revoke(s.id)}><LogOut />Sign out</Button>}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Dialog open={!!setup} onOpenChange={(o) => !o && setSetup(null)}>
        {setup && <DialogContent title="Set up authenticator app" description="Scan the QR code, then enter the 6-digit code to confirm.">
          <div className="space-y-4">
            <div className="flex justify-center"><img src={setup.qr_svg} alt="TOTP QR code" className="h-48 w-48 rounded-lg border bg-white p-2" /></div>
            <div className="text-center"><p className="text-2xs text-muted-foreground">Or enter this key manually</p><Mono className="break-all text-xs">{setup.secret}</Mono></div>
            <Field label="Verification code"><Input inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} className="text-center font-mono tracking-[0.4em]" /></Field>
            <div className="flex justify-end"><Button onClick={confirmTotp} disabled={code.length !== 6}>Confirm and enable</Button></div>
          </div>
        </DialogContent>}
      </Dialog>
    </div>
  );
}

function SecurityConfig() {
  const { data, error } = useSWR("/api/settings/security", fetcher);
  if (error) return <Card><ErrorState error={error} /></Card>;
  if (!data) return <Card><LoadingRows /></Card>;
  const a = data.auth, b = data.brute_force, g = data.governance;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader title="Authentication" /><CardBody>
        <KV k="Password hashing" v={a.password_hashing} /><KV k="Access token lifetime" v={`${a.access_token_ttl_seconds / 60} min`} />
        <KV k="Refresh token lifetime" v={`${Math.round(a.refresh_token_ttl_seconds / 86400)} days`} /><KV k="Refresh rotation / reuse detection" v="On / On" />
        <KV k="MFA methods" v={a.mfa_methods.join(", ")} /><KV k="Cookies" v={`HttpOnly · ${a.cookies.secure ? "Secure" : "Secure off (dev)"} · SameSite=${a.cookies.samesite}`} />
        <KV k="CSRF" v={a.csrf} /><KV k="Environment" v={<Badge tone={data.app_env === "production" ? "success" : "warning"}>{data.app_env}</Badge>} />
      </CardBody></Card>
      <Card><CardHeader title="Brute-force protection" description="Redis token buckets plus progressive, temporary lockout." /><CardBody>
        <KV k="Failures before lockout" v={`${b.max_failures} in ${b.window_seconds / 60} min`} />
        <KV k="Lockout" v={`${b.lockout_base_seconds}s, doubling, max ${b.lockout_max_seconds / 60} min`} />
        <KV k="Per-IP bucket" v={`${b.ip_bucket.capacity} tokens, ${b.ip_bucket.refill_per_minute}/min`} />
        <KV k="Per-account bucket" v={`${b.account_bucket.capacity} tokens, ${b.account_bucket.refill_per_minute}/min`} />
        <KV k="CAPTCHA" v={b.captcha} />
      </CardBody></Card>
      <Card><CardHeader title="Governance" /><CardBody>
        <KV k="Recertification interval" v={`${g.recertification_interval_days} days`} />
        <KV k="Break-glass default / max" v={`${g.breakglass_default_minutes} / ${g.breakglass_max_minutes} min`} />
        <KV k="AI provider" v={data.ai.provider === "none" ? "Rule engine + anomaly model (no LLM)" : `${data.ai.provider} · ${data.ai.model}`} />
        <p className="mt-2 text-xs text-muted-foreground">{data.ai.note}</p>
      </CardBody></Card>
      <Card><CardHeader title="Roles" description="Permissions enforced by the API on every request." /><CardBody className="space-y-3">
        {data.roles.map((r: any) => (
          <div key={r.name}><div className="flex items-center gap-2"><Badge tone="violet">{ROLE_LABEL[r.name]}</Badge><span className="text-xs text-muted-foreground">{r.description}</span></div>
            <div className="mt-1.5 flex flex-wrap gap-1">{r.permissions.map((p: string) => <Mono key={p} className="rounded bg-muted px-1 py-0.5 text-2xs">{p}</Mono>)}</div></div>
        ))}
      </CardBody></Card>
    </div>
  );
}

function Users() {
  const { me } = useSession();
  const { data, error, mutate } = useSWR("/api/admin/users", fetcher);
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<any>(null);
  const [roles, setRoles] = useState<string[]>([]);
  const save = async () => {
    try { await api(`/api/admin/users/${edit.id}/roles`, { method: "PUT", json: { roles } }); toast.success("Roles updated. The user's sessions were revoked."); setEdit(null); mutate(); }
    catch (e) { toast.error(errorMessage(e)); }
  };
  if (error) return <Card><ErrorState error={error} /></Card>;
  const rows = (data || []).filter((u: any) => !q || `${u.name} ${u.email} ${u.department}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <Card>
      <div className="flex items-center justify-between gap-2 p-3"><Input placeholder="Filter users…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 max-w-xs" /><span className="text-xs text-muted-foreground tabular">{rows.length} users</span></div>
      {!data ? <LoadingRows /> : (
        <Table>
          <THead><TR><TH>User</TH><TH>Department</TH><TH>Roles</TH><TH>MFA</TH><TH>Status</TH><TH className="text-right" /></TR></THead>
          <TBody>
            {rows.map((u: any) => {
              const locked = u.locked_until && new Date(u.locked_until) > new Date();
              return (
                <TR key={u.id}>
                  <TD><div className="flex items-center gap-2"><Avatar name={u.name} /><div><div className="font-medium">{u.name}</div><div className="text-2xs text-muted-foreground">{u.email}</div></div></div></TD>
                  <TD className="text-xs">{u.department}</TD>
                  <TD><div className="flex flex-wrap gap-1">{u.roles.filter((r: string) => r !== "REQUESTER").map((r: string) => <Badge key={r} tone="violet">{ROLE_LABEL[r]}</Badge>)}{u.roles.length === 1 && <span className="text-2xs text-muted-foreground">Requester</span>}</div></TD>
                  <TD>{u.mfa_enabled ? <Badge tone="success">TOTP</Badge> : <Badge tone="outline">Email</Badge>}</TD>
                  <TD>{u.status !== "ACTIVE" ? <Badge tone="outline">{u.status.toLowerCase()}</Badge> : locked ? <Badge tone="critical">Locked</Badge> : <Badge tone="success">Active</Badge>}</TD>
                  <TD className="text-right"><Button size="sm" variant="ghost" onClick={() => { setEdit(u); setRoles(u.roles); }}>Edit roles</Button></TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}
      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        {edit && <DialogContent title="Edit roles" description={`${edit.name} · changes are audited and force re-authentication`}>
          <div className="space-y-2">
            {ROLES.map((r) => (
              <label key={r} className={cn("flex items-center gap-2 rounded-md border p-2 text-sm", r === "REQUESTER" && "opacity-60")}>
                <input type="checkbox" disabled={r === "REQUESTER" || (edit.id === me?.id && r === "SECURITY_ADMIN")} checked={roles.includes(r)}
                  onChange={(e) => setRoles(e.target.checked ? [...roles, r] : roles.filter((x) => x !== r))} />{ROLE_LABEL[r]}
                {r === "REQUESTER" && <span className="ml-auto text-2xs text-muted-foreground">Baseline for everyone</span>}
              </label>
            ))}
            <div className="flex justify-end pt-2"><Button onClick={save}>Save roles</Button></div>
          </div>
        </DialogContent>}
      </Dialog>
    </Card>
  );
}

function LoginAttempts() {
  const { data, error } = useSWR("/api/admin/login-attempts", fetcher, { refreshInterval: 15000 });
  if (error) return <Card><ErrorState error={error} /></Card>;
  return (
    <Card>
      {!data ? <LoadingRows /> : (
        <Table>
          <THead><TR><TH>When</TH><TH>Email</TH><TH>IP</TH><TH>Stage</TH><TH>Result</TH><TH>Reason</TH></TR></THead>
          <TBody>
            {data.map((r: any, i: number) => (
              <TR key={i}>
                <TD className="whitespace-nowrap text-xs text-muted-foreground" title={fmtDate(r.at)}>{relTime(r.at)}</TD>
                <TD className="text-xs">{r.email}</TD>
                <TD><Mono className="text-xs">{r.ip}</Mono></TD>
                <TD className="text-xs">{r.stage}</TD>
                <TD>{r.success ? <Badge tone="success">Success</Badge> : <Badge tone="critical">Failed</Badge>}</TD>
                <TD className="text-xs text-muted-foreground">{r.reason || "—"}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </Card>
  );
}

export default function SettingsPage() {
  const { can } = useSession();
  const admin = can("users:manage");
  return (
    <>
      <PageHeader title="Settings" description="Your profile, sign-in security and platform configuration." />
      <Tabs defaultValue="security">
        <TabsList>
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="security">Sign-in &amp; security</TabsTrigger>
          <TabsTrigger value="config">Security configuration</TabsTrigger>
          {admin && <TabsTrigger value="users">Users &amp; roles</TabsTrigger>}
          {admin && <TabsTrigger value="attempts">Login attempts</TabsTrigger>}
        </TabsList>
        <TabsContent value="profile"><Profile /></TabsContent>
        <TabsContent value="security"><Security /></TabsContent>
        <TabsContent value="config"><SecurityConfig /></TabsContent>
        {admin && <TabsContent value="users"><Users /></TabsContent>}
        {admin && <TabsContent value="attempts"><LoginAttempts /></TabsContent>}
      </Tabs>
    </>
  );
}
