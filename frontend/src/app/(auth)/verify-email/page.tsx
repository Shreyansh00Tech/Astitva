"use client";
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Mail } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";

function Inner() {
  const params = useSearchParams();
  const [email, setEmail] = useState(params.get("email") || "");
  const [code, setCode] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dev, setDev] = useState<string | null>(null);
  useEffect(() => {
    if (!email) return;
    api(`/api/auth/dev/outbox?email=${encodeURIComponent(email)}`).then((m: any[]) => setDev(m.find((x) => x.subject.includes("Verify"))?.body.match(/\d{6}/)?.[0] || null)).catch(() => {});
  }, [email, busy]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api("/api/auth/verify-email", { json: { email, code } }); setDone(true); }
    catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };
  if (done) return (
    <div className="animate-fade-in text-center">
      <CheckCircle2 className="mx-auto h-10 w-10 text-success" />
      <h1 className="mt-4 text-xl font-semibold">Email verified</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">You can now sign in. You'll complete MFA on every sign-in.</p>
      <Button asChild className="mt-6 w-full" size="lg"><Link href="/login">Go to sign in</Link></Button>
    </div>
  );
  return (
    <div className="animate-fade-in">
      <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-lg bg-violet/10"><Mail className="h-5 w-5 text-violet" /></div>
      <h1 className="text-xl font-semibold tracking-tight">Verify your email</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">Enter the 6-digit code we sent you.</p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field label="Email"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
        <Field label="Verification code"><Input value={code} onChange={(e) => setCode(e.target.value)} maxLength={6} className="text-center font-mono text-lg tracking-[0.4em]" /></Field>
        {error && <p className="text-xs text-critical">{error}</p>}
        <Button type="submit" size="lg" className="w-full" loading={busy} disabled={code.length !== 6}>Verify email</Button>
        <button type="button" className="w-full text-xs text-muted-foreground hover:text-foreground" onClick={() => api("/api/auth/verify-email/resend", { json: { email } }).then(() => setBusy((b) => !b))}>Resend code</button>
      </form>
      {dev && <p className="mt-4 rounded-md border border-dashed border-violet/40 p-2 text-xs text-muted-foreground">Dev mailbox: <span className="font-mono font-semibold text-foreground">{dev}</span></p>}
    </div>
  );
}
export default function Page() { return <Suspense><Inner /></Suspense>; }
