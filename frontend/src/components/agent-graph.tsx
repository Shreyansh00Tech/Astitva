"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, BookOpenText, CheckCircle2, CircleHelp, Database, FileText, Gavel, History, Info, Layers, Scale, ShieldCheck, Sparkles, Swords, XCircle,
} from "lucide-react";
import { cn, hours, titleCase } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Perms, RiskBadge, SensitivityBadge } from "@/components/status";

/* ------------------------------------------------------------------ vocabulary */
export const VERDICT: Record<string, { label: string; tone: any; edge: string; dot: string }> = {
  OK: { label: "OK", tone: "success", edge: "stroke-success/70", dot: "bg-success" },
  CAUTION: { label: "Caution", tone: "warning", edge: "stroke-warning/80", dot: "bg-warning" },
  RISK: { label: "Risk", tone: "critical", edge: "stroke-critical/80", dot: "bg-critical" },
  NO_DATA: { label: "No data", tone: "neutral", edge: "stroke-muted-foreground/40", dot: "bg-muted-foreground/50" },
  AGREES: { label: "Agrees", tone: "success", edge: "stroke-success/70", dot: "bg-success" },
  ADJUSTED: { label: "Adjusted", tone: "violet", edge: "stroke-violet/70", dot: "bg-violet" },
};
export const FINAL_VERDICT: Record<string, { label: string; tone: any; icon: any }> = {
  APPROVE: { label: "Approve", tone: "success", icon: CheckCircle2 },
  APPROVE_NARROWED: { label: "Approve narrowed", tone: "info", icon: Layers },
  ESCALATE: { label: "Escalate", tone: "warning", icon: AlertTriangle },
  REJECT_SUGGESTED: { label: "Reject / investigate", tone: "critical", icon: XCircle },
};
const AGENT_ICON: Record<string, any> = {
  HISTORY: History, DATA_IMPACT: Database, PURPOSE: FileText, POLICY: BookOpenText, CHALLENGER: Swords,
};
const SEV: Record<string, { icon: any; cls: string }> = {
  good: { icon: CheckCircle2, cls: "text-success" }, info: { icon: Info, cls: "text-info" },
  warn: { icon: AlertTriangle, cls: "text-warning" }, risk: { icon: XCircle, cls: "text-critical" },
};
export const BAND: Record<string, string> = { AUTO: "Auto-approve band", MANAGER: "Manager band", MANAGER_AND_SECURITY: "Manager + Security band" };

export function Delta({ v, className }: { v: number; className?: string }) {
  return (
    <span className={cn("rounded-md px-1.5 py-0.5 font-mono text-2xs font-semibold tabular",
      v > 0 ? "bg-critical/10 text-critical" : v < 0 ? "bg-success/10 text-success" : "bg-muted text-muted-foreground", className)}>
      {v > 0 ? `+${v}` : v}
    </span>
  );
}

/* ------------------------------------------------------------------ layout */
const W = 222, H = 104, ROW = 118, COLS = 4;
type NodeKey = string;
type Pos = { col: number; row: number };

const LAYOUT: Record<NodeKey, Pos> = {
  REQUEST: { col: 0, row: 2 }, RULE: { col: 1, row: 0 },
  HISTORY: { col: 1, row: 1 }, DATA_IMPACT: { col: 1, row: 2 }, PURPOSE: { col: 1, row: 3 }, POLICY: { col: 1, row: 4 },
  CHALLENGER: { col: 2, row: 2.5 }, AGGREGATOR: { col: 3, row: 1.25 }, DECISION: { col: 3, row: 3.25 },
};

export function AgentGraph({ review, selected, onSelect }: { review: any; selected: string; onSelect: (k: string) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1100);
  const [hover, setHover] = useState<string | null>(null);
  useLayoutEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(1040, e.contentRect.width)));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);
  const gap = (width - W * COLS) / (COLS - 1);
  const x = (c: number) => c * (W + gap);
  const y = (r: number) => 34 + r * ROW;
  const height = 34 + 5 * ROW - (ROW - H) + 8;
  const agents: any[] = review.agents || [];
  const byCode = useMemo(() => Object.fromEntries(agents.map((a) => [a.code, a])), [agents]);
  const agg = review.aggregator || {};
  const r = review.request;

  const edges: { from: string; to: string; cls: string; label?: React.ReactNode; dashed?: boolean }[] = [
    { from: "REQUEST", to: "RULE", cls: "stroke-violet/60" },
    ...["HISTORY", "DATA_IMPACT", "PURPOSE", "POLICY"].map((k) => ({ from: "REQUEST", to: k, cls: "stroke-violet/40" })),
    ...["HISTORY", "DATA_IMPACT", "PURPOSE", "POLICY"].map((k) => ({
      from: k, to: "CHALLENGER", cls: VERDICT[byCode[k]?.verdict]?.edge || "stroke-muted-foreground/40",
      dashed: byCode[k]?.verdict === "NO_DATA",
    })),
    { from: "CHALLENGER", to: "AGGREGATOR", cls: VERDICT[byCode.CHALLENGER?.verdict]?.edge || "stroke-violet/60",
      label: <Delta v={(agg.delta ?? 0)} /> },
    { from: "RULE", to: "AGGREGATOR", cls: "stroke-violet/60", label: <span className="rounded-md bg-card px-1.5 py-0.5 font-mono text-2xs font-semibold ring-1 ring-border">rule {review.rule_score}</span> },
    { from: "AGGREGATOR", to: "DECISION", cls: review.status === "AWAITING_CHOICE" ? "stroke-warning" : "stroke-success/70",
      dashed: review.status === "AWAITING_CHOICE",
      label: <span className="rounded-md bg-card px-1.5 py-0.5 font-mono text-2xs font-semibold ring-1 ring-border">AI {review.ai_score}</span> },
  ];
  const geo = (from: string, to: string) => {
    const a = LAYOUT[from], b = LAYOUT[to];
    if (a.col === b.col) { // same column: straight down from the bottom port to the top port
      const cx = x(a.col) + W / 2, y1 = y(a.row) + H, y2 = y(b.row);
      return { d: `M${cx},${y1} L${cx},${y2}`, mx: cx, my: (y1 + y2) / 2 };
    }
    const x1 = x(a.col) + W, y1 = y(a.row) + H / 2, x2 = x(b.col), y2 = y(b.row) + H / 2, mid = (x1 + x2) / 2;
    return { d: `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`, mx: mid, my: (y1 + y2) / 2 };
  };
  const related = useMemo(() => {
    if (!hover) return null;
    const s = new Set([hover]);
    for (const e of edges) if (e.from === hover || e.to === hover) { s.add(e.from); s.add(e.to); }
    return s;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hover]);

  const node = (k: string, body: React.ReactNode, opts: { icon: any; tone: string; title: string; sub?: string; ring?: string } ) => {
    const p = LAYOUT[k];
    const Icon = opts.icon;
    return (
      <button key={k} type="button" onClick={() => onSelect(k)} onMouseEnter={() => setHover(k)} onMouseLeave={() => setHover(null)}
        className={cn("group absolute flex flex-col rounded-xl border bg-card p-2.5 text-left shadow-sm outline-none transition-all duration-300",
          "hover:-translate-y-0.5 hover:shadow-md focus-visible:ring-2 focus-visible:ring-violet/40",
          selected === k && "border-violet ring-2 ring-violet/25", opts.ring, related && !related.has(k) && "opacity-35")}
        style={{ left: x(p.col), top: y(p.row), width: W, height: H }}>
        <span className="absolute -left-[5px] top-1/2 h-2.5 w-2.5 -translate-y-1/2 rounded-full border-2 border-card bg-muted-foreground/40" />
        <span className="absolute -right-[5px] top-1/2 h-2.5 w-2.5 -translate-y-1/2 rounded-full border-2 border-card bg-muted-foreground/40" />
        <div className="flex items-center gap-2">
          <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-lg", opts.tone)}><Icon className="h-3.5 w-3.5" /></span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12.5px] font-semibold leading-tight">{opts.title}</div>
            {opts.sub && <div className="truncate text-2xs text-muted-foreground">{opts.sub}</div>}
          </div>
        </div>
        <div className="mt-1.5 min-h-0 flex-1">{body}</div>
      </button>
    );
  };

  const agentNode = (k: string) => {
    const a = byCode[k];
    if (!a) return null;
    const v = VERDICT[a.verdict] || VERDICT.OK;
    const eff = a.effective_delta ?? a.delta;
    return node(k, (
      <>
        <div className="flex items-center gap-1.5">
          <Badge tone={v.tone}>{v.label}</Badge>
          <span className="ml-auto flex items-center gap-1">
            {eff !== a.delta && <span className="font-mono text-2xs text-muted-foreground line-through">{a.delta > 0 ? `+${a.delta}` : a.delta}</span>}
            <Delta v={eff} />
          </span>
        </div>
        <p className="mt-1 line-clamp-2 text-2xs leading-snug text-muted-foreground">{a.summary}</p>
      </>
    ), { icon: AGENT_ICON[k] || Sparkles, tone: "bg-violet/10 text-violet", title: a.name, sub: `${a.findings.length} finding(s)` + (a.data_gaps?.length ? " · data gap" : "") });
  };

  const fv = FINAL_VERDICT[agg.verdict] || FINAL_VERDICT.APPROVE;
  const ch = byCode.CHALLENGER;

  return (
    <div className="overflow-x-auto scroll-thin">
      <div ref={wrap} className="relative min-w-[1040px] select-none" style={{ height }}>
        <div className="pointer-events-none absolute inset-0 rounded-lg opacity-60 [background-image:radial-gradient(hsl(var(--border))_1px,transparent_1px)] [background-size:18px_18px]" />
        <svg className="absolute inset-0 h-full w-full" width={width} height={height} aria-hidden>
          {edges.map((e) => {
            const g = geo(e.from, e.to);
            const dim = related && !(related.has(e.from) && related.has(e.to));
            return <path key={e.from + e.to} d={g.d} strokeWidth={1.75}
              className={cn("fill-none transition-opacity duration-300", e.cls, e.dashed ? "[stroke-dasharray:4_5]" : "graph-flow")}
              style={{ opacity: dim ? 0.12 : 1 }} />;
          })}
        </svg>
        {edges.filter((e) => e.label).map((e) => {
          const g = geo(e.from, e.to);
          const dim = related && !(related.has(e.from) && related.has(e.to));
          // midpoint (t = 0.5) of the curve drawn above
          return <div key={"l" + e.from + e.to} className="absolute -translate-x-1/2 -translate-y-1/2 transition-opacity duration-300"
            style={{ left: g.mx, top: g.my, opacity: dim ? 0.15 : 1 }}>{e.label}</div>;
        })}

        {["Input", "Rule engine + agents", "Second opinion", "Verdict + final score"].map((t, i) => (
          <div key={t} className="pointer-events-none absolute top-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground" style={{ left: x(i) }}>{t}</div>
        ))}

        {node("REQUEST", (
          <div className="space-y-1">
            <div className="truncate text-2xs"><span className="text-foreground">{r?.resource?.name}</span></div>
            <div className="flex items-center gap-1"><SensitivityBadge level={r?.resource?.sensitivity} /><Perms perms={r?.approved_permissions || []} /></div>
          </div>
        ), { icon: FileText, tone: "bg-info/10 text-info", title: r?.ref || "Request", sub: `${r?.requester?.name} · ${r?.purpose_label}` })}

        {node("RULE", (
          <div className="flex items-center gap-2">
            <span className="text-2xl font-semibold tabular leading-none">{review.rule_score}</span>
            <div className="min-w-0">
              <RiskBadge level={agg.rule_level} />
              <div className="mt-0.5 truncate text-2xs text-muted-foreground">{BAND[agg.rule_band]} · decides routing</div>
            </div>
          </div>
        ), { icon: Scale, tone: "bg-violet/15 text-violet", title: "Rule engine", sub: "Deterministic, authoritative", ring: "border-violet/40" })}

        {["HISTORY", "DATA_IMPACT", "PURPOSE", "POLICY"].map(agentNode)}

        {ch && node("CHALLENGER", (
          <>
            <div className="flex items-center gap-1.5">
              <Badge tone={(VERDICT[ch.verdict] || VERDICT.AGREES).tone}>{(VERDICT[ch.verdict] || VERDICT.AGREES).label}</Badge>
              <span className="text-2xs text-muted-foreground">{ch.adjustments?.length || 0} correction(s)</span>
              <span className="ml-auto"><Delta v={ch.delta} /></span>
            </div>
            <p className="mt-1 line-clamp-2 text-2xs leading-snug text-muted-foreground">Confidence {titleCase(ch.confidence || "MEDIUM").toLowerCase()} · removes double counting and claims without evidence</p>
          </>
        ), { icon: Swords, tone: "bg-serious/10 text-serious", title: ch.name, sub: "Checks the other agents" })}

        {node("AGGREGATOR", (
          <div className="flex items-center gap-2">
            <span className="text-2xl font-semibold tabular leading-none">{review.ai_score}</span>
            <div className="min-w-0">
              <Badge tone={fv.tone}><fv.icon />{fv.label}</Badge>
              <div className="mt-0.5 truncate text-2xs text-muted-foreground">AI score · {BAND[agg.ai_band]}</div>
            </div>
          </div>
        ), { icon: Sparkles, tone: "bg-violet/15 text-violet", title: "Aggregator agent", sub: "Fixed rules, final verdict", ring: "border-violet/40" })}

        {node("DECISION", (
          <div className="flex items-center gap-2">
            <span className={cn("text-2xl font-semibold tabular leading-none", review.status === "AWAITING_CHOICE" && "text-muted-foreground")}>{review.status === "AWAITING_CHOICE" ? "?" : review.final_score}</span>
            <div className="min-w-0">
              {review.status === "AWAITING_CHOICE" ? <Badge tone="warning" className="graph-pulse">You choose</Badge>
                : <Badge tone="success"><ShieldCheck />{review.chosen === "AUTO" ? "Automatic" : review.chosen === "AI" ? "AI score chosen" : "Rule score chosen"}</Badge>}
              <div className="mt-0.5 truncate text-2xs text-muted-foreground">rule {review.rule_score} · AI {review.ai_score}</div>
            </div>
          </div>
        ), { icon: Gavel, tone: review.status === "AWAITING_CHOICE" ? "bg-warning/15 text-warning" : "bg-success/10 text-success",
          title: "Final score of record", sub: review.status === "AWAITING_CHOICE" ? "Scores disagree" : "Set",
          ring: review.status === "AWAITING_CHOICE" ? "border-warning/60" : "border-success/40" })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ detail panels */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">{title}</div>{children}</div>;
}

function Findings({ items }: { items: any[] }) {
  if (!items.length) return <p className="text-xs text-muted-foreground">No findings.</p>;
  return (
    <div className="divide-y rounded-md border">
      {items.map((f) => { const s = SEV[f.severity] || SEV.info; return (
        <div key={f.id} className="flex items-start gap-3 px-3 py-2">
          <s.icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", s.cls)} />
          <div className="min-w-0 flex-1">
            <div className="text-[13px]">{f.claim}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {f.evidence.map((e: string) => <span key={e} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground">{e}</span>)}
              {f.overlaps?.length > 0 && <span className="text-[10.5px] text-muted-foreground">· overlaps rule factor {f.overlaps.join(", ").toLowerCase().replaceAll("_", " ")}</span>}
            </div>
          </div>
          <Delta v={f.points} className="mt-0.5" />
        </div>); })}
    </div>
  );
}

export function NodeDetail({ review, k }: { review: any; k: string }) {
  const agg = review.aggregator || {};
  const r = review.request;
  if (k === "REQUEST") return (
    <div className="space-y-3">
      <p className="text-[13px] text-muted-foreground">The input every agent reads. The justification is treated as data, never as an instruction.</p>
      <div className="rounded-md bg-muted/40 p-3 text-[13px]"><div className="mb-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground">Justification</div>{r.justification}</div>
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span>Permissions <Perms perms={r.approved_permissions} /></span><span>Duration {hours(r.approved_duration_hours)}</span><span>Purpose {r.purpose_label}</span>
      </div>
    </div>
  );
  if (k === "RULE") return (
    <div className="space-y-3">
      <p className="text-[13px] text-muted-foreground">The deterministic rule engine. Its score decides who must approve. The agents cannot lower it or remove a reviewer.</p>
      <div className="divide-y rounded-md border">
        {[...(r.risk?.factors || [])].sort((a: any, b: any) => b.points - a.points).map((f: any) => (
          <div key={f.code + f.detail} className="flex items-start gap-3 px-3 py-2">
            <div className="min-w-0 flex-1"><div className="text-[13px] font-medium">{f.label}</div><div className="text-xs text-muted-foreground">{f.detail}</div></div>
            {f.available === false ? <span className="font-mono text-2xs text-muted-foreground">n/a</span> : <Delta v={f.points} />}
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">Total {review.rule_score}/100 · {BAND[agg.rule_band]}</p>
    </div>
  );
  if (k === "AGGREGATOR") {
    const agents: any[] = review.agents || [];
    return (
      <div className="space-y-4">
        <p className="text-[13px] text-muted-foreground">The Aggregator uses fixed rules, not a model: AI score = rule score + every agent&apos;s points after the Challenger, limited to +{agg.caps?.up} / −{agg.caps?.down}.</p>
        <div className="flex flex-wrap items-center gap-1.5 rounded-md border bg-muted/30 p-3 font-mono text-xs">
          <span className="rounded bg-card px-1.5 py-0.5 ring-1 ring-border">rule {review.rule_score}</span>
          {agents.map((a) => <span key={a.code} className="inline-flex items-center gap-1">+ <span className="text-muted-foreground">{a.name.split(" ")[0]}</span><Delta v={a.delta} /></span>)}
          <span>=</span><span className="rounded bg-violet/10 px-1.5 py-0.5 font-semibold text-violet">AI {review.ai_score}</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-md border p-3">
            <div className="text-2xs font-medium uppercase tracking-wider text-muted-foreground">Verdict</div>
            <div className="mt-1.5 text-[13px] font-medium">{(FINAL_VERDICT[agg.verdict] || FINAL_VERDICT.APPROVE).label}</div>
            <p className="mt-1 text-xs text-muted-foreground">{agg.narrative || agg.summary}</p>
            {agg.narrative && <p className="mt-1 text-2xs text-muted-foreground">Phrased by the local model ({agg.narrative_source}).</p>}
          </div>
          <div className="rounded-md border p-3">
            <div className="text-2xs font-medium uppercase tracking-wider text-muted-foreground">Recommended scope</div>
            <div className="mt-1.5 flex items-center gap-2"><Perms perms={agg.recommended_permissions || []} /><span className="text-xs text-muted-foreground">for {hours(agg.recommended_hours)}</span></div>
            <p className="mt-1 text-xs text-muted-foreground">Rule engine&apos;s least-privilege advice, minus what the agents asked to drop.</p>
          </div>
        </div>
        <Section title="When does the Security Manager choose?">
          <ul className="space-y-1 text-xs text-muted-foreground">
            <li>• The scores differ by {agg.choice_gap} or more, or land in different routing bands, or the text tries to steer the reviewer.</li>
            <li>• Otherwise the higher score is used automatically.</li>
            <li>• If the agents score higher and disagree, a Security Manager review is added. A reviewer is never removed.</li>
          </ul>
        </Section>
        <p className="text-2xs text-muted-foreground">Confidence {titleCase(agg.confidence || "MEDIUM").toLowerCase()} · ran in {agg.ms} ms · engine {review.engine}</p>
      </div>
    );
  }
  if (k === "DECISION") return (
    <div className="space-y-2 text-[13px]">
      <p className="text-muted-foreground">{review.chosen_label}.</p>
      {review.chosen_reason && <p className="rounded-md bg-muted/40 p-3">“{review.chosen_reason}”</p>}
      <p className="text-xs text-muted-foreground">The Manager sees this final score and who set it, not the agents&apos; working.</p>
    </div>
  );
  const a = (review.agents || []).find((x: any) => x.code === k);
  if (!a) return null;
  return (
    <div className="space-y-4">
      <p className="text-[13px] text-muted-foreground">{a.role}</p>
      {a.stats?.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {a.stats.map((s: any) => <div key={s.label} className="rounded-md bg-muted/50 px-2.5 py-2"><div className="truncate text-2xs text-muted-foreground">{s.label}</div><div className="text-[13px] font-medium tabular">{s.value}</div></div>)}
        </div>
      )}
      <Section title="Findings"><Findings items={a.findings} /></Section>
      {a.data_gaps?.length > 0 && (
        <Section title="Data gaps">
          <ul className="space-y-1">{a.data_gaps.map((g: string) => <li key={g} className="flex gap-2 text-xs text-muted-foreground"><CircleHelp className="mt-0.5 h-3.5 w-3.5 shrink-0" />{g}</li>)}</ul>
        </Section>
      )}
      {a.retrieval && (
        <Section title={`Policy search · ${a.retrieval.method}`}>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-xs">
              <thead className="bg-muted/40 text-left text-2xs text-muted-foreground"><tr><th className="px-2 py-1.5">Clause</th><th className="px-2 py-1.5">BM25</th><th className="px-2 py-1.5">Text rank</th><th className="px-2 py-1.5">Match rank</th><th className="px-2 py-1.5">RRF</th><th className="px-2 py-1.5">Applies</th></tr></thead>
              <tbody className="divide-y">
                {a.retrieval.hits.map((h: any) => (
                  <tr key={h.id} title={h.text}>
                    <td className="px-2 py-1.5"><span className="font-mono">{h.id}</span> <span className="text-muted-foreground">{h.title}</span></td>
                    <td className="px-2 py-1.5 font-mono tabular">{h.bm25}</td><td className="px-2 py-1.5 tabular">#{h.bm25_rank}</td>
                    <td className="px-2 py-1.5 tabular">#{h.match_rank}</td><td className="px-2 py-1.5 font-mono tabular">{h.rrf}</td>
                    <td className="px-2 py-1.5">{h.applies ? <Badge tone={h.points ? "warning" : "neutral"}>{h.points ? `Yes · +${h.points}` : "Yes"}</Badge> : <span className="text-muted-foreground">{h.matched.length}/{h.conditions.length}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-2xs text-muted-foreground">Search picks what to cite. Points come only from clauses whose conditions are all true.</p>
        </Section>
      )}
      {a.adjustments?.length > 0 && (
        <Section title="Corrections">
          <div className="divide-y rounded-md border">
            {a.adjustments.map((x: any, i: number) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2 text-xs">
                <span className="w-28 shrink-0 font-medium">{x.agent.replace("_", " ").toLowerCase()}</span>
                <span className="font-mono">{x.finding}</span>
                <span className="flex-1 text-muted-foreground">{x.reason}</span>
                <span className="font-mono tabular"><s className="text-muted-foreground">{x.from > 0 ? `+${x.from}` : x.from}</s> → {x.to > 0 ? `+${x.to}` : x.to}</span>
              </div>
            ))}
          </div>
        </Section>
      )}
      <Section title="Reads (read-only)"><div className="flex flex-wrap gap-1">{a.reads.map((s: string) => <Badge key={s} tone="outline">{s}</Badge>)}</div></Section>
    </div>
  );
}

export const NODE_TITLE: Record<string, string> = {
  REQUEST: "Request", RULE: "Rule engine", HISTORY: "History agent", DATA_IMPACT: "Data impact agent", PURPOSE: "Purpose agent",
  POLICY: "Policy agent (search)", CHALLENGER: "Challenger agent", AGGREGATOR: "Aggregator agent", DECISION: "Final score of record",
};
