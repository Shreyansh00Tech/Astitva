import Link from "next/link";
import { cn } from "@/lib/utils";

export function StatTile({ label, value, hint, icon: Icon, tone = "default", href }: {
  label: string; value: React.ReactNode; hint?: React.ReactNode; icon?: any;
  tone?: "default" | "violet" | "warning" | "critical" | "success"; href?: string;
}) {
  const toneCls = { default: "text-muted-foreground", violet: "text-violet", warning: "text-warning", critical: "text-critical", success: "text-success" }[tone];
  const body = (
    <div className={cn("group relative h-full rounded-lg border bg-card p-4 card-elevated transition-colors", href && "hover:border-violet/40")}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        {Icon && <Icon className={cn("h-4 w-4", toneCls)} />}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular">{value}</div>
      {hint && <div className="mt-1 text-2xs text-muted-foreground">{hint}</div>}
    </div>
  );
  return href ? <Link href={href} className="block h-full">{body}</Link> : body;
}
