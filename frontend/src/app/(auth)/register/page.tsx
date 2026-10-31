"use client";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { PasswordMeter } from "@/components/password-meter";

export default function RegisterPage() {
  const router = useRouter();
  const [f, setF] = useState({ full_name: "", email: "", password: "", confirm: "" });
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (f.password !== f.confirm) return setError("Passwords do not match.");
    setBusy(true); setError(null);
    try {
      await api("/api/auth/register", { json: { full_name: f.full_name, email: f.email, password: f.password } });
      router.push(`/verify-email?email=${encodeURIComponent(f.email)}`);
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };
  return (
    <div className="animate-fade-in">
      <h1 className="text-xl font-semibold tracking-tight">Create your account</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">New accounts start with the Employee role. Elevated roles are assigned by a Security Manager.</p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field label="Full name"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required /></Field>
        <Field label="Work email"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required /></Field>
        <Field label="Password">
          <Input type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />
        </Field>
        <PasswordMeter password={f.password} email={f.email} name={f.full_name} onChange={setOk} />
        <Field label="Confirm password"><Input type="password" autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} required /></Field>
        {error && <p className="rounded-md border border-critical/30 bg-critical/5 px-3 py-2 text-xs text-critical">{error}</p>}
        <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!ok}>Create account</Button>
      </form>
      <p className="mt-6 text-center text-xs text-muted-foreground">Already have an account? <Link href="/login" className="text-violet hover:underline">Sign in</Link></p>
    </div>
  );
}
