"use client";
import * as React from "react";
import * as TT from "@radix-ui/react-tooltip";
import { AlertTriangle, Inbox, RotateCw } from "lucide-react";
import { cn, initials } from "@/lib/utils";
import { Button } from "./button";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return <div className="space-y-2 p-4">{Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>;
}

export function EmptyState({ title, description, icon: Icon = Inbox, action }: { title: string; description?: string; icon?: any; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 rounded-full border bg-muted/50 p-2.5"><Icon className="h-5 w-5 text-muted-foreground" /></div>
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="mt-1 max-w-sm text-xs text-muted-foreground">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: any; onRetry?: () => void }) {
  const status = error?.status;
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 rounded-full border border-critical/30 bg-critical/10 p-2.5"><AlertTriangle className="h-5 w-5 text-critical" /></div>
      <p className="text-sm font-medium">{status === 403 ? "You don't have access to this" : status === 404 ? "Not found" : "Couldn't load this data"}</p>
      <p className="mt-1 max-w-sm text-xs text-muted-foreground">{status === 403 ? "Your role does not include this permission. Access is enforced by the server." : (error?.message || "Please try again.")}</p>
      {onRetry && status !== 403 && <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}><RotateCw />Retry</Button>}
    </div>
  );
}

export function Avatar({ name, className }: { name?: string; className?: string }) {
  const hue = Array.from(name || "x").reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return (
    <span className={cn("inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-2xs font-semibold text-white", className)}
      style={{ background: `linear-gradient(135deg, hsl(${hue} 45% 45%), hsl(${(hue + 40) % 360} 50% 38%))` }}>
      {initials(name)}
    </span>
  );
}

export function Tip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  return (
    <TT.Provider delayDuration={200}>
      <TT.Root>
        <TT.Trigger asChild>{children}</TT.Trigger>
        <TT.Portal>
          <TT.Content sideOffset={6} className="z-50 max-w-xs rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground shadow-lg animate-fade-in">{content}</TT.Content>
        </TT.Portal>
      </TT.Root>
    </TT.Provider>
  );
}

export function PageHeader({ title, description, actions, eyebrow }: { title: string; description?: string; actions?: React.ReactNode; eyebrow?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && <div className="mb-1">{eyebrow}</div>}
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function KV({ k, v, className }: { k: string; v: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start justify-between gap-4 py-1.5 text-[13px]", className)}>
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right font-medium">{v}</span>
    </div>
  );
}

export function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[12px]", className)}>{children}</span>;
}
