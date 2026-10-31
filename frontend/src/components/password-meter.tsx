"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export function PasswordMeter({ password, email, name, onChange }: { password: string; email?: string; name?: string; onChange?: (ok: boolean) => void }) {
  const [res, setRes] = useState<{ score: number; ok: boolean; problems: string[] } | null>(null);
  useEffect(() => {
    if (!password) { setRes(null); onChange?.(false); return; }
    const t = setTimeout(() => api("/api/auth/password-strength", { json: { password, email, name } })
      .then((r) => { setRes(r); onChange?.(r.ok); }).catch(() => {}), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [password, email, name]);
  if (!res) return <p className="text-2xs text-muted-foreground">12+ characters with a mix of upper, lower, digits and symbols.</p>;
  const colors = ["bg-critical", "bg-critical", "bg-warning", "bg-success", "bg-success"];
  return (
    <div className="space-y-1.5">
      <div className="flex gap-1">{[0, 1, 2, 3].map((i) => <span key={i} className={cn("h-1 flex-1 rounded-full", i < Math.max(1, res.score) ? colors[res.score] : "bg-muted")} />)}</div>
      {res.ok ? <p className="text-2xs text-success">Strong password.</p> : <ul className="space-y-0.5 text-2xs text-critical">{res.problems.map((p) => <li key={p}>• {p}</li>)}</ul>}
    </div>
  );
}
