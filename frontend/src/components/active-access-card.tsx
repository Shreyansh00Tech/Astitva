"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { ArrowUpRight, KeyRound } from "lucide-react";
import { fetcher } from "@/lib/api";
import { useMounted } from "@/lib/motion";
import { cn, duration } from "@/lib/utils";
import { Card, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, Skeleton } from "@/components/ui/misc";
import { Perms, SensitivityBadge } from "@/components/status";

const R = 10;
const C = 2 * Math.PI * R;

/** Ring that drains from full to the share of time left. Amber with a soft pulse under 24h. */
function ExpiryRing({ grantedAt, expiresAt, now, delay }: { grantedAt: string; expiresAt: string; now: number; delay: number }) {
  const mounted = useMounted();
  const start = new Date(grantedAt).getTime();
  const end = new Date(expiresAt).getTime();
  const left = Math.max(0, (end - now) / 1000);
  const frac = end > start ? Math.max(0, Math.min(1, (end - now) / (end - start))) : 0;
  const soon = left < 86400;
  return (
    <div className="flex items-center gap-2">
      <svg width="26" height="26" viewBox="0 0 26 26" className={cn("-rotate-90 shrink-0", soon && "ov-soft-pulse")} aria-hidden>
        <circle cx="13" cy="13" r={R} fill="none" strokeWidth="2.5" className="stroke-muted" />
        <circle cx="13" cy="13" r={R} fill="none" strokeWidth="2.5" strokeLinecap="round" strokeDasharray={C}
          className={cn("ov-ring", soon ? "stroke-warning" : "stroke-violet")}
          style={{ strokeDashoffset: mounted ? C * (1 - frac) : 0, transitionDelay: `${delay}ms` }} />
      </svg>
      <span className={cn("whitespace-nowrap text-xs tabular", soon ? "text-warning" : "text-muted-foreground")}>{duration(left)}</span>
    </div>
  );
}

/** The employee's active grants with a draining expiry ring per row. Sized to pair with Daily work activity. */
export function ActiveAccessCard({ className }: { className?: string }) {
  const { data } = useSWR("/api/grants?scope=mine&status=ACTIVE", fetcher, { refreshInterval: 60000 });
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(t); }, []);
  const rows = (data || []).slice().sort((a: any, b: any) =>
    (a.expires_at ? new Date(a.expires_at).getTime() : Infinity) - (b.expires_at ? new Date(b.expires_at).getTime() : Infinity));
  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader title="Active access" description="Your grants and the time left on each"
        action={<Link href="/active-access" className="inline-flex items-center gap-0.5 text-2xs text-violet hover:underline">View all<ArrowUpRight className="h-3 w-3" /></Link>} />
      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin">
        {!data ? <div className="space-y-2 px-4 pb-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-9" />)}</div>
          : !rows.length ? <EmptyState icon={KeyRound} title="No active access" description="Approved requests appear here with the time left on each grant." />
          : (
            <table className="w-full text-[13px]">
              <thead className="sticky top-0 z-10 bg-card">
                <tr className="border-y text-left text-2xs font-medium uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Resource</th><th className="px-2 py-2 font-medium">Permissions</th><th className="px-4 py-2 font-medium">Expires in</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((g: any, i: number) => (
                  <tr key={g.id} className="ov-rise border-b last:border-0 even:bg-muted/30" style={{ animationDelay: `${i * 60}ms` }}>
                    <td className="px-4 py-2"><div className="truncate font-medium">{g.resource.name}</div><SensitivityBadge level={g.resource.sensitivity} /></td>
                    <td className="px-2 py-2"><Perms perms={g.permissions} /></td>
                    <td className="px-4 py-2">{g.expires_at
                      ? <ExpiryRing grantedAt={g.granted_at} expiresAt={g.expires_at} now={now} delay={150 + i * 80} />
                      : <Badge tone="neutral">Standing</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </Card>
  );
}
