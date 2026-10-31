"use client";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";

export default function ForgotPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [devLink, setDevLink] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true);
    await api("/api/auth/forgot-password", { json: { email } }).catch(() => {});
    setSent(true); setBusy(false);
    api(`/api/auth/dev/outbox?email=${encodeURIComponent(email)}`).then((m: any[]) => {
      const msg = m.find((x) => x.subject.includes("Reset"));
      setDevLink(msg?.body.match(/\/reset-password\?token=\S+/)?.[0] || null);
    }).catch(() => {});
  };
  return (
    <div className="animate-fade-in">
      <h1 className="text-xl font-semibold tracking-tight">Reset your password</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">We'll email a single-use link valid for 30 minutes.</p>
      {sent ? (
        <div className="mt-6 space-y-3">
          <p className="rounded-md border bg-card p-3 text-[13px]">If an account exists for <b>{email}</b>, a reset link is on its way.</p>
          {devLink && <p className="rounded-md border border-dashed border-violet/40 p-3 text-xs text-muted-foreground">Dev mailbox: <Link href={devLink} className="text-violet underline">open reset link</Link></p>}
        </div>
      ) : (
        <form onSubmit={submit} className="mt-6 space-y-4">
          <Field label="Work email"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
          <Button type="submit" size="lg" className="w-full" loading={busy}>Send reset link</Button>
        </form>
      )}
      <p className="mt-6 text-center text-xs"><Link href="/login" className="text-violet hover:underline">Back to sign in</Link></p>
    </div>
  );
}
