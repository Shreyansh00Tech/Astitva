"use client";

import { useEffect, useState } from "react";
import { Check, FileEdit, Sparkles, X } from "lucide-react";
import { cn, relTime } from "@/lib/utils";

/**
 * Animated approval stepper.
 * Paths: Submitted -> [Auto-approved by policy] -> Access active
 *        Submitted -> Manager -> Access active
 *        Submitted -> Manager -> Security Manager -> Access active
 * Animation uses only transform / opacity (compositor-only, no layout thrash) and turns off
 * under prefers-reduced-motion.
 */

type StepState = "done" | "active" | "rejected" | "changes" | "cancelled" | "upcoming";
type Step = { key: string; label: string; state: StepState; sub?: string };

export const STEP_LABEL: Record<string, string> = { MANAGER: "Manager", RISK: "Security Manager", OWNER: "Resource owner", AUTO: "Auto-approved" };

/** First name from a user object ({name}) or a plain name string; never throws. */
function firstName(u: any): string {
  const n = typeof u === "string" ? u : u?.name ?? u?.full_name ?? "";
  return String(n).trim().split(/\s+/)[0] || "";
}

function buildSteps(r: any): Step[] {
  const stages: string[] = r.required_stages?.length ? r.required_stages : ["AUTO"];
  const approvals: any[] = r.approvals || [];
  const status: string = r.status;
  const cur = r.current_stage ? stages.indexOf(r.current_stage) : -1;
  const decided = r.decision_stage ? stages.indexOf(r.decision_stage) : stages.length - 1;
  const lastApproval = (stage: string) => [...approvals].reverse().find((a) => a.stage === stage);

  const steps: Step[] = [{ key: "SUBMIT", label: "Submitted", state: "done", sub: r.created_at ? relTime(r.created_at) : undefined }];
  stages.forEach((s, i) => {
    let state: StepState = "upcoming";
    if (status === "APPROVED") state = "done";
    else if (status === "PENDING") state = i < cur ? "done" : i === cur ? "active" : "upcoming";
    else if (status === "CHANGES_REQUESTED") state = i < cur ? "done" : i === cur ? "changes" : "upcoming";
    else if (status === "REJECTED") state = i < decided ? "done" : i === decided ? "rejected" : "upcoming";
    else if (status === "CANCELLED") state = i < Math.max(cur, 0) ? "done" : i === Math.max(cur, 0) ? "cancelled" : "upcoming";

    let sub: string | undefined;
    const a = lastApproval(s);
    if (s === "AUTO") sub = status === "APPROVED" ? `By policy · risk ${r.risk?.score ?? "–"}/100` : undefined;
    else if (state === "done" && a) sub = [firstName(a.approver), a.at ? relTime(a.at) : ""].filter(Boolean).join(" · ") || "Approved";
    else if (state === "done") sub = "Approved";
    else if (state === "active") {
      const names = (Array.isArray(r.stage_approvers) ? r.stage_approvers : []).map(firstName).filter(Boolean);
      sub = names.length ? `Pending · ${names.join(", ")}` : "Pending";
    }
    else if (state === "rejected") sub = a && firstName(a.approver) ? `Rejected · ${firstName(a.approver)}` : "Rejected";
    else if (state === "changes") sub = "Changes requested";
    else if (state === "cancelled") sub = "Cancelled";
    steps.push({ key: s, label: STEP_LABEL[s] || s, state, sub });
  });
  const live = status === "APPROVED";
  const acc = r.access;
  if (live && acc?.status === "REVOKED") {
    const by = firstName(acc.revoked_by);
    steps.push({ key: "ACTIVE", label: "Access revoked", state: "rejected", sub: [by && `By ${by}`, acc.revoked_at && relTime(acc.revoked_at)].filter(Boolean).join(" · ") || "Revoked" });
  } else if (live && acc?.status === "EXPIRED") {
    steps.push({ key: "ACTIVE", label: "Access expired", state: "cancelled", sub: acc.expires_at ? relTime(acc.expires_at) : "Expired" });
  } else {
    const narrowed = live && acc && Array.isArray(acc.permissions) && acc.permissions.length < (r.approved_permissions?.length ?? 0);
    steps.push({ key: "ACTIVE", label: "Access active", state: live ? "done" : "upcoming",
      sub: !live ? undefined : narrowed ? `Now ${acc.permissions.join(", ")} only` : (r.decided_at ? relTime(r.decided_at) : "Granted") });
  }
  return steps;
}

function Node({ step, index, mounted }: { step: Step; index: number; mounted: boolean }) {
  const s = step.state;
  const delay = { animationDelay: `${index * 140}ms`, transitionDelay: `${index * 140}ms` };
  return (
    <span className="relative flex h-8 w-8 items-center justify-center">
      {s === "active" && (
        <>
          <span className="stepper-ring absolute inset-0 rounded-full bg-violet/30" />
          <span className="stepper-ring absolute inset-0 rounded-full bg-violet/20 [animation-delay:700ms]" />
        </>
      )}
      <span style={delay}
        className={cn("relative z-10 flex h-8 w-8 items-center justify-center rounded-full border-2 text-xs font-semibold transition-[transform,opacity] duration-500 [transition-timing-function:cubic-bezier(.22,1,.36,1)] motion-reduce:transition-none",
          mounted ? "scale-100 opacity-100" : "scale-75 opacity-0",
          s === "done" && "border-success bg-success text-white shadow-[0_0_0_4px_hsl(var(--success)/0.12)]",
          s === "active" && "border-violet bg-card text-violet shadow-[0_0_0_4px_hsl(var(--violet)/0.15)]",
          s === "rejected" && "border-critical bg-critical text-white",
          s === "changes" && "border-warning bg-warning/15 text-warning",
          s === "cancelled" && "border-muted-foreground/40 bg-muted text-muted-foreground",
          s === "upcoming" && "border-border bg-card text-muted-foreground")}>
        {s === "done" ? (step.key === "AUTO" ? <Sparkles className="stepper-pop h-4 w-4" style={delay} /> : <Check className="stepper-pop h-4 w-4" strokeWidth={3} style={delay} />)
          : s === "rejected" ? <X className="h-4 w-4" strokeWidth={3} />
          : s === "changes" ? <FileEdit className="h-3.5 w-3.5" />
          : s === "active" ? <span className="stepper-dot h-2.5 w-2.5 rounded-full bg-violet" />
          : index}
      </span>
    </span>
  );
}

export function ApprovalStepper({ r, className }: { r: any; className?: string }) {
  const steps = buildSteps(r);
  const [mounted, setMounted] = useState(false);
  useEffect(() => { const id = requestAnimationFrame(() => setMounted(true)); return () => cancelAnimationFrame(id); }, []);

  return (
    <div className={cn("relative flex w-full items-start overflow-x-auto pb-1 scroll-thin", className)} role="list" aria-label="Approval progress">
      {steps.map((s, i) => {
        const next = steps[i + 1];
        const filled = next && (next.state === "done" || next.state === "active" || next.state === "rejected" || next.state === "changes");
        const flowing = next?.state === "active";
        const tone = next?.state === "rejected" ? "bg-critical" : next?.state === "changes" ? "bg-warning" : "bg-success";
        return (
          <div key={s.key} role="listitem" aria-current={s.state === "active" ? "step" : undefined}
            className="relative flex min-w-[112px] flex-1 flex-col items-center text-center">
            {next && (
              <span className="absolute left-[calc(50%+20px)] right-[calc(-50%+20px)] top-[15px] h-[3px] overflow-hidden rounded-full bg-border">
                <span style={{ transitionDelay: `${i * 140 + 120}ms` }}
                  className={cn("absolute inset-0 origin-left rounded-full transition-transform duration-700 [transition-timing-function:cubic-bezier(.22,1,.36,1)] motion-reduce:transition-none",
                    flowing ? "bg-violet/50" : tone, mounted && filled ? "scale-x-100" : "scale-x-0")} />
                {flowing && mounted && <span className="stepper-flow absolute inset-y-0 w-1/3 rounded-full bg-gradient-to-r from-transparent via-violet to-transparent" />}
              </span>
            )}
            <Node step={s} index={i} mounted={mounted} />
            <span className={cn("mt-2 text-xs font-medium", s.state === "upcoming" || s.state === "cancelled" ? "text-muted-foreground" : "text-foreground")}>{s.label}</span>
            <span className={cn("mt-0.5 min-h-[14px] text-2xs",
              s.state === "active" ? "text-violet" : s.state === "rejected" ? "text-critical" : s.state === "changes" ? "text-warning" : "text-muted-foreground")}>{s.sub}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Compact version for tables: segmented bar + current label. */
export function MiniStepper({ r }: { r: any }) {
  const steps = buildSteps(r).slice(1); // without "Submitted"
  const [mounted, setMounted] = useState(false);
  useEffect(() => { const id = requestAnimationFrame(() => setMounted(true)); return () => cancelAnimationFrame(id); }, []);
  const current = steps.find((s) => s.state === "active" || s.state === "rejected" || s.state === "changes" || s.state === "cancelled");
  const label = r.status === "APPROVED" && r.access?.status === "REVOKED" ? "Access revoked"
    : r.status === "APPROVED" && r.access?.status === "EXPIRED" ? "Access expired"
    : r.status === "APPROVED" ? (r.auto_approved ? "Auto-approved · active" : "Approved · active")
    : current ? `${current.label} · ${current.state === "active" ? "pending" : current.state === "changes" ? "changes requested" : current.state}` : r.status.toLowerCase();
  return (
    <div className="flex min-w-[120px] flex-col gap-1 whitespace-nowrap">
      <div className="flex items-center gap-1">
        {steps.map((s, i) => (
          <span key={s.key} title={`${s.label}${s.sub ? ` · ${s.sub}` : ""}`} className="relative h-1.5 w-7 overflow-hidden rounded-full bg-muted-foreground/15">
            <span style={{ transitionDelay: `${i * 110}ms` }}
              className={cn("absolute inset-0 origin-left rounded-full transition-transform duration-500 [transition-timing-function:cubic-bezier(.22,1,.36,1)] motion-reduce:transition-none",
                s.state === "done" ? "bg-success" : s.state === "active" ? "bg-violet" : s.state === "rejected" ? "bg-critical" : s.state === "changes" ? "bg-warning" : s.state === "cancelled" ? "bg-muted-foreground/40" : "bg-transparent",
                mounted && s.state !== "upcoming" ? "scale-x-100" : "scale-x-0")} />
            {s.state === "active" && mounted && <span className="stepper-flow absolute inset-y-0 w-1/2 bg-gradient-to-r from-transparent via-white/70 to-transparent" />}
          </span>
        ))}
      </div>
      <span className={cn("text-2xs", current?.state === "active" ? "text-violet" : current?.state === "rejected" || r.access?.status === "REVOKED" ? "text-critical" : r.access?.status === "EXPIRED" ? "text-muted-foreground" : r.status === "APPROVED" ? "text-success" : "text-muted-foreground")}>{label}</span>
    </div>
  );
}
