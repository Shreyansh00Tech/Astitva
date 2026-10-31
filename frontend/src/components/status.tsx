import { AlertOctagon, AlertTriangle, CheckCircle2, Clock, ShieldAlert, ShieldCheck, XCircle, Info, Siren } from "lucide-react";
import { Badge, type Tone } from "@/components/ui/badge";
import { cn, titleCase } from "@/lib/utils";

const LEVEL: Record<string, { tone: Tone; icon: any }> = {
  LOW: { tone: "success", icon: ShieldCheck },
  MEDIUM: { tone: "warning", icon: AlertTriangle },
  HIGH: { tone: "serious", icon: ShieldAlert },
  CRITICAL: { tone: "critical", icon: AlertOctagon },
};

export function RiskBadge({ level, score }: { level?: string; score?: number }) {
  if (!level) return <span className="text-muted-foreground">—</span>;
  const c = LEVEL[level] || LEVEL.LOW;
  const Icon = c.icon;
  return <Badge tone={c.tone}><Icon />{score != null && <span className="tabular">{score}</span>}{titleCase(level)}</Badge>;
}

/** Review priority (deadline + impact + waiting + urgency). Separate from risk: it only orders the queue. */
export function PriorityBadge({ p, compact, hideScore }: { p?: { score: number; level: string; overdue?: boolean; approaching?: boolean } | null; compact?: boolean; hideScore?: boolean }) {
  if (!p) return <span className="text-muted-foreground">—</span>;
  const c = LEVEL[p.level] || LEVEL.LOW;
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Badge tone={c.tone} className="gap-1">{!hideScore && <span className="tabular">{p.score}</span>}{!compact && titleCase(p.level)}{compact && p.level[0]}</Badge>
      {p.overdue && <Badge tone="critical" className="animate-pulse2"><Clock />Overdue</Badge>}
      {!p.overdue && p.approaching && <Badge tone="warning"><Clock />Due soon</Badge>}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <RiskBadge level={severity} />;
}

export function RiskMeter({ score, level }: { score: number; level: string }) {
  const color = { LOW: "bg-success", MEDIUM: "bg-warning", HIGH: "bg-serious", CRITICAL: "bg-critical" }[level] || "bg-success";
  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-2">
        <span className="text-4xl font-semibold tabular tracking-tight">{score}</span>
        <span className="text-sm text-muted-foreground">/ 100</span>
        <span className="ml-auto"><RiskBadge level={level} /></span>
      </div>
      <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${score}%` }} />
        {[30, 60, 80].map((t) => <span key={t} className="absolute top-0 h-full w-0.5 bg-card" style={{ left: `${t}%` }} />)}
      </div>
      <div className="flex justify-between text-2xs text-muted-foreground tabular"><span>0 Low</span><span>31 Med</span><span>61 High</span><span>81 Crit</span></div>
    </div>
  );
}

const SENS: Record<string, Tone> = { PUBLIC: "neutral", INTERNAL: "info", CONFIDENTIAL: "warning", RESTRICTED: "serious", CRITICAL: "critical" };
export function SensitivityBadge({ level }: { level: string }) {
  return <Badge tone={SENS[level] || "neutral"} className="uppercase tracking-wide">{level}</Badge>;
}

const STATUS: Record<string, { tone: Tone; icon: any }> = {
  PENDING: { tone: "warning", icon: Clock }, APPROVED: { tone: "success", icon: CheckCircle2 },
  REJECTED: { tone: "critical", icon: XCircle }, CHANGES_REQUESTED: { tone: "info", icon: Info },
  CANCELLED: { tone: "neutral", icon: XCircle }, ACTIVE: { tone: "success", icon: CheckCircle2 },
  EXPIRED: { tone: "neutral", icon: Clock }, REVOKED: { tone: "critical", icon: XCircle },
  OPEN: { tone: "warning", icon: AlertTriangle }, ACKNOWLEDGED: { tone: "info", icon: Info },
  RESOLVED: { tone: "success", icon: CheckCircle2 }, REVIEWED: { tone: "info", icon: CheckCircle2 },
  REMEDIATED: { tone: "success", icon: CheckCircle2 }, REVIEW_SCHEDULED: { tone: "info", icon: Clock },
  RETAINED: { tone: "success", icon: CheckCircle2 }, RESTRICTED: { tone: "warning", icon: ShieldAlert },
  COMPLETED: { tone: "success", icon: CheckCircle2 }, DEACTIVATED: { tone: "critical", icon: XCircle },
  ALLOWED: { tone: "success", icon: CheckCircle2 }, DENIED: { tone: "critical", icon: XCircle },
  SUSPENDED: { tone: "critical", icon: XCircle },
};
export function StatusBadge({ status }: { status: string }) {
  const c = STATUS[status] || { tone: "neutral" as Tone, icon: Info };
  const Icon = c.icon;
  return <Badge tone={c.tone}><Icon />{titleCase(status)}</Badge>;
}

const PERM_TONE: Record<string, Tone> = { READ: "neutral", EXECUTE: "info", WRITE: "warning", DELETE: "serious", ADMIN: "critical" };
export function Perms({ perms, strike }: { perms: string[]; strike?: string[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {perms.map((p) => (
        <Badge key={p} tone={PERM_TONE[p] || "neutral"} className={cn("font-mono", strike?.includes(p) && "line-through opacity-60")}>{p}</Badge>
      ))}
    </span>
  );
}

export function BreakGlassBadge() {
  return <Badge tone="solidCritical" className="uppercase tracking-wider"><Siren />Break-glass</Badge>;
}

export const STAGE_LABEL: Record<string, string> = { MANAGER: "Manager", RISK: "Security review", OWNER: "Resource owner" };

export function StageTrack({ stages, current, status }: { stages: string[]; current: string | null; status: string }) {
  const idx = current ? stages.indexOf(current) : status === "APPROVED" ? stages.length : -1;
  return (
    <div className="flex items-center gap-1">
      {stages.map((s, i) => {
        const done = i < idx || status === "APPROVED";
        const active = i === idx && status === "PENDING";
        const failed = status === "REJECTED" && i === Math.max(0, idx);
        return (
          <div key={s} className="flex items-center gap-1">
            <span title={STAGE_LABEL[s]} className={cn("h-1.5 w-6 rounded-full",
              done ? "bg-success" : active ? "bg-violet animate-pulse2" : failed ? "bg-critical" : "bg-muted-foreground/20")} />
          </div>
        );
      })}
      <span className="ml-1 text-2xs text-muted-foreground">{status === "PENDING" && current ? STAGE_LABEL[current] : titleCase(status)}</span>
    </div>
  );
}
