"use client";
import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { PasswordMeter } from "@/components/password-meter";

function Inner() {
  const token = useSearchParams().get("token") || "";
  const [pw, setPw] = useState("");
  const [ok, setOk] = useState(false);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api("/api/auth/reset-password", { json: { token, new_password: pw } }); setDone(true); }
    catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };
  if (done) return <div className="animate-fade-in"><h1 className="text-xl font-semibold">Password updated</h1><p className="mt-1 text-[13px] text-muted-foreground">All existing sessions were signed out.</p><Button asChild className="mt-6 w-full" size="lg"><Link href="/login">Sign in</Link></Button></div>;
  return (
    <div className="animate-fade-in">
      <h1 className="text-xl font-semibold tracking-tight">Choose a new password</h1>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field label="New password"><Input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
        <PasswordMeter password={pw} onChange={setOk} />
        {error && <p className="text-xs text-critical">{error}</p>}
        <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!ok || !token}>Update password</Button>
      </form>
    </div>
  );
}
export default function Page() { return <Suspense><Inner /></Suspense>; }
