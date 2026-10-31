"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, KeyRound, Lock, Mail, MessageSquare, ShieldCheck, Smartphone, Eye, EyeOff } from "lucide-react";
import { api, ApiError, errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Step = { mfa_token: string; methods: string[]; destination: string | null; email: string };
const METHOD_META: Record<string, { label: string; icon: any; hint: string }> = {
  TOTP: { label: "Authenticator", icon: Smartphone, hint: "Enter the 6-digit code from your authenticator app." },
  EMAIL: { label: "Email code", icon: Mail, hint: "We sent a 6-digit code to your email." },
  SMS: { label: "SMS", icon: MessageSquare, hint: "We sent a code by SMS." },
  BACKUP_CODE: { label: "Recovery code", icon: KeyRound, hint: "Use one of your one-time recovery codes." },
};

const DEMO = [
  ["Employee · Rahul", "rahul.sharma@nexora.example", "Engineering"], ["Employee · Neha", "neha.gupta@nexora.example", "Finance"],
  ["Employee · Kavya", "kavya.reddy@nexora.example", "HR"], ["Manager · Priya", "priya.desai@nexora.example", "Approves her team"],
  ["Security Manager · Meera", "admin@nexora.example", "Risk Reviewer · Admin"],
];

const NAMOID_ERRORS: Record<string, string> = {
  NAMOID_DENIED: "Sign-in was cancelled on NamoID.",
  NAMOID_STATE: "Your NamoID sign-in expired or was started in another tab. Please try again.",
  NAMOID_EMAIL: "Your NamoID account needs a verified email address.",
  NAMOID_NOT_LINKED: "No ASTITVA account is linked to this NamoID identity.",
  NAMOID_ACCOUNT_INACTIVE: "This account cannot sign in.",
  NAMOID_DISABLED: "NamoID sign-in is not configured on this server.",
  NAMOID_UNAVAILABLE: "NamoID could not be reached. Please try again.",
};

function DevMailbox({ email, tick }: { email: string; tick: number }) {
  const [msgs, setMsgs] = useState<any[] | null>(null);
  useEffect(() => {
    api(`/api/auth/dev/outbox?email=${encodeURIComponent(email)}`).then(setMsgs).catch(() => setMsgs(null));
  }, [email, tick]);
  if (!msgs) return null;
  const latest = msgs.find((m) => /\b\d{6}\b/.test(m.body));
  return (
    <div className="mt-5 rounded-lg border border-dashed border-violet/40 bg-violet/[0.04] p-3 text-xs">
      <div className="mb-1 flex items-center gap-1.5 font-medium text-violet"><Mail className="h-3.5 w-3.5" />Development mailbox (simulated delivery)</div>
      {latest ? <p className="text-muted-foreground">{latest.subject}: <span className="font-mono text-sm font-semibold tracking-widest text-foreground">{latest.body.match(/\b\d{6}\b/)?.[0]}</span></p>
        : <p className="text-muted-foreground">No code delivered yet.</p>}
      <p className="mt-1 text-2xs text-muted-foreground/80">Shown only when APP_ENV=development. Production sends real email/SMS via the delivery adapter.</p>
    </div>
  );
}

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<Step | null>(null);
  const [method, setMethod] = useState("EMAIL");
  const [code, setCode] = useState("");
  const [tick, setTick] = useState(0);
  const [retryAfter, setRetryAfter] = useState(0);
  const [namoid, setNamoid] = useState(true);

  useEffect(() => {
    api("/api/auth/namoid/config").then((r) => setNamoid(!!r?.enabled)).catch(() => setNamoid(true));
    const code = params.get("namoid_error");
    if (code) setError(NAMOID_ERRORS[code] ?? "NamoID sign-in did not complete. Please try again.");
  }, [params]);

  useEffect(() => {
    if (retryAfter <= 0) return;
    const t = setTimeout(() => setRetryAfter((r) => r - 1), 1000);
    return () => clearTimeout(t);
  }, [retryAfter]);

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await api("/api/auth/login", { json: { email, password } });
      setStep({ ...r, email });
      setMethod(r.methods.includes("TOTP") ? "TOTP" : "EMAIL");
      setTick((t) => t + 1);
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.data?.retry_after) setRetryAfter(err.data.retry_after);
    } finally { setBusy(false); }
  };

  const chooseMethod = async (m: string) => {
    setMethod(m); setCode(""); setError(null);
    if ((m === "EMAIL" || m === "SMS") && step) {
      try { await api("/api/auth/mfa/resend", { json: { mfa_token: step.mfa_token, channel: m } }); setTick((t) => t + 1); }
      catch (err) { setError(errorMessage(err)); }
    }
  };

  const submitCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!step) return;
    setBusy(true); setError(null);
    try {
      await api("/api/auth/mfa/verify", { json: { mfa_token: step.mfa_token, method, code } });
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.data?.code === "MFA_EXPIRED") setStep(null);
      if (err instanceof ApiError && err.data?.retry_after) { setRetryAfter(err.data.retry_after); setStep(null); }
    } finally { setBusy(false); }
  };

  if (step) {
    const meta = METHOD_META[method];
    return (
      <div className="auth-rise">
        <button onClick={() => { setStep(null); setCode(""); }} className="mb-6 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />Back</button>
        <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-lg bg-violet/10"><ShieldCheck className="h-5 w-5 text-violet" /></div>
        <h1 className="text-xl font-semibold tracking-tight">Verify it's you</h1>
        <p className="mt-1 text-[13px] text-muted-foreground">Multi-factor authentication is required. Your session starts only after this step.</p>
        <div className="mt-5 grid grid-cols-2 gap-1.5">
          {step.methods.filter((m) => m !== "SMS").map((m) => {
            const M = METHOD_META[m];
            return (
              <button key={m} type="button" onClick={() => chooseMethod(m)}
                className={cn("flex items-center gap-2 rounded-md border px-2.5 py-2 text-left text-xs transition-colors",
                  method === m ? "border-violet bg-violet/5 text-foreground" : "text-muted-foreground hover:bg-accent")}>
                <M.icon className="h-3.5 w-3.5" />{M.label}
              </button>
            );
          })}
        </div>
        <form onSubmit={submitCode} className="mt-5 space-y-4">
          <Field label={meta.label} hint={method === "EMAIL" && step.destination ? `Code sent to ${step.destination}` : meta.hint}>
            <Input value={code} onChange={(e) => setCode(e.target.value)} autoFocus inputMode={method === "BACKUP_CODE" ? "text" : "numeric"}
              autoComplete="one-time-code" placeholder={method === "BACKUP_CODE" ? "XXXXX-XXXXX" : "000000"}
              className="h-11 text-center font-mono text-lg tracking-[0.4em]" maxLength={method === "BACKUP_CODE" ? 11 : 6} />
          </Field>
          {error && <p className="rounded-md border border-critical/30 bg-critical/5 px-3 py-2 text-xs text-critical">{error}</p>}
          <Button type="submit" variant="default" size="lg" className="w-full" loading={busy} disabled={code.length < 6}>Verify and sign in</Button>
          {(method === "EMAIL") && <button type="button" onClick={() => chooseMethod("EMAIL")} className="w-full text-center text-xs text-muted-foreground hover:text-foreground">Resend code</button>}
        </form>
        {(method === "EMAIL") && <DevMailbox email={step.email} tick={tick} />}
      </div>
    );
  }

  return (
    <div>
      <h1 className="auth-rise text-xl font-semibold tracking-tight">Sign in to ASTITVA</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">Nexora Technologies workforce identity</p>
      {namoid && (
        <div className="auth-rise mt-6">
          <a href={`/api/auth/namoid/login${params.get("next") ? `?next=${encodeURIComponent(params.get("next")!)}` : ""}`}
            className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-violet text-sm font-medium text-white shadow-sm transition-colors hover:bg-violet/90">
            <ShieldCheck className="h-4 w-4" />Continue with NamoID
          </a>
          <p className="mt-2 text-center text-2xs text-muted-foreground">Secure sign-in through NamoID Hosted Auth</p>
          <div className="my-5 flex items-center gap-3 text-2xs uppercase tracking-wider text-muted-foreground">
            <span className="h-px flex-1 bg-border" />or demo password sign-in<span className="h-px flex-1 bg-border" />
          </div>
        </div>
      )}
      <form onSubmit={submitPassword} className={cn("space-y-4", !namoid && "mt-6")}>
        <Field label="Work email">
          <Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="name@nexora.example" />
        </Field>
        <Field label="Password">
          <div className="relative">
            <Input type={show ? "text" : "password"} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required className="pr-9" />
            <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground" aria-label="Toggle password visibility">
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </Field>
        <div className="flex justify-end -mt-1"><Link href="/forgot-password" className="text-xs text-violet hover:underline">Forgot password?</Link></div>
        {error && (
          <div className="flex items-start gap-2 rounded-md border border-critical/30 bg-critical/5 px-3 py-2 text-xs text-critical">
            <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{error}{retryAfter > 0 && <> Try again in <span className="font-semibold tabular">{retryAfter}s</span>.</>}</span>
          </div>
        )}
        <Button type="submit" size="lg" className="w-full" loading={busy} disabled={retryAfter > 0}>Continue</Button>
      </form>
      <p className="mt-6 text-center text-xs text-muted-foreground">New to Nexora? <Link href="/register" className="text-violet hover:underline">Create an account</Link></p>

      <div className="mt-8 rounded-lg border bg-card p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-medium">Demo accounts</span>
          <span className="font-mono text-2xs text-muted-foreground">Nexora@Demo2026</span>
        </div>
        <div className="grid grid-cols-2 gap-1">
          {DEMO.map(([role, mail, sub], i) => (
            <button key={mail} type="button" onClick={() => { setEmail(mail); setPassword("Nexora@Demo2026"); }}
              className={cn("auth-rise rounded-md px-2 py-1.5 text-left text-2xs transition-colors duration-200 hover:bg-accent", email === mail && "bg-violet/[0.07] ring-1 ring-violet/30")}
              style={{ animationDelay: `${450 + i * 50}ms` }}>
              <div className="font-medium text-foreground">{role}</div>
              <div className="truncate text-muted-foreground">{mail.split("@")[0]} · {sub}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return <Suspense><LoginInner /></Suspense>;
}
