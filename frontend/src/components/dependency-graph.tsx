"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { Bot, Boxes, Check, Database, Plug, User, Users } from "lucide-react";
import { cn, fmtDate } from "@/lib/utils";

export type GNode = {
  id: string; type: "RESOURCE" | "USER" | "USER_GROUP" | "AGENT" | "API"; label: string; sub?: string;
  status: "ACTIVE" | "REVOKED" | "SUSPENDED" | "DEGRADED"; depth: number; impact: "ROOT" | "DIRECT" | "INDIRECT";
  can_revoke?: boolean; can_restore?: boolean; criticality?: string; sensitivity?: string; count?: number;
  dependency_id?: string; description?: string; resource_type?: string;
};
export type GEdge = {
  id: string; source: string; target: string; kind: string; status: string; permissions?: string[];
  emergency?: boolean; tokens?: number; expires_at?: string | null; label?: string;
};
export type Graph = { nodes: GNode[]; edges: GEdge[]; summary: Record<string, number>; resource: any; viewer: any };

const ROW = 58;
const NODE_W = 212;
const TYPE_ORDER: Record<string, number> = { USER: 0, USER_GROUP: 1, AGENT: 2, API: 3, RESOURCE: 3 };
const ICON: Record<string, any> = { RESOURCE: Boxes, USER: User, USER_GROUP: Users, AGENT: Bot, API: Plug };
const TYPE_TONE: Record<string, string> = {
  RESOURCE: "text-violet bg-violet/10", USER: "text-info bg-info/10", USER_GROUP: "text-muted-foreground bg-muted",
  AGENT: "text-violet bg-violet/10", API: "text-success bg-success/10",
};

/** Layered layout: the resource on the left, direct dependents in the middle, indirect ones on the right. */
function layout(g: Graph) {
  const root = g.nodes.find((n) => n.impact === "ROOT")!;
  const parent: Record<string, string> = {};
  for (const e of g.edges) if (!parent[e.target]) parent[e.target] = e.source;
  const col1 = g.nodes.filter((n) => n.depth === 1)
    .sort((a, b) => (TYPE_ORDER[a.type] ?? 9) - (TYPE_ORDER[b.type] ?? 9) || a.label.localeCompare(b.label));
  const pos: Record<string, { col: number; row: number }> = {};
  col1.forEach((n, i) => (pos[n.id] = { col: 1, row: i }));
  // Indirect nodes are placed next to their (first) parent, in parent order.
  const col2: GNode[] = [];
  for (const p of col1) for (const n of g.nodes) if (n.depth === 2 && parent[n.id] === p.id && !col2.includes(n)) col2.push(n);
  for (const n of g.nodes) if (n.depth === 2 && !col2.includes(n)) col2.push(n);
  let next = 0;
  for (const n of col2) {
    const want = pos[parent[n.id]]?.row ?? 0;
    const row = Math.max(next, want - 0.5);
    pos[n.id] = { col: 2, row };
    next = row + 1;
  }
  const rows = Math.max(col1.length, next, 1);
  pos[root.id] = { col: 0, row: (Math.max(col1.length, 1) - 1) / 2 };
  return { pos, rows, hasCol2: col2.length > 0, root };
}

const edgeClass = (status: string, preview: boolean) => cn(
  "fill-none transition-[stroke,opacity] duration-500",
  preview ? "stroke-critical graph-flow-fast" :
  status === "ACTIVE" ? "stroke-violet/50 graph-flow" :
  status === "REVOKED" ? "stroke-critical/70 [stroke-dasharray:4_5]" :
  status === "SUSPENDED" ? "stroke-warning/80 [stroke-dasharray:4_5]" : "stroke-warning/60 [stroke-dasharray:1_5]",
);

export function DependencyGraph({ graph, selected, onToggle, preview, highlightChanged }: {
  graph: Graph; selected: Set<string>; onToggle?: (n: GNode) => void; preview?: Set<string>; highlightChanged?: Set<string>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [hover, setHover] = useState<string | null>(null);
  useLayoutEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(760, e.contentRect.width)));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);
  const { pos, rows, hasCol2 } = useMemo(() => layout(graph), [graph]);
  const cols = hasCol2 ? 3 : 2;
  const gap = (width - NODE_W * cols) / (cols - 1 || 1);
  const x = (col: number) => col * (NODE_W + gap);
  const y = (row: number) => 30 + row * ROW;
  const height = rows * ROW + 34;
  const byId = useMemo(() => Object.fromEntries(graph.nodes.map((n) => [n.id, n])), [graph]);
  const related = useMemo(() => {
    if (!hover) return null;
    const s = new Set([hover]);
    for (const e of graph.edges) if (e.source === hover || e.target === hover) { s.add(e.source); s.add(e.target); }
    return s;
  }, [hover, graph]);

  return (
    <div className="overflow-x-auto scroll-thin">
      <div ref={wrap} className="relative min-w-[760px]" style={{ height }}>
        <svg className="absolute inset-0 h-full w-full" width={width} height={height} aria-hidden>
          {graph.edges.map((e) => {
            const a = pos[e.source], b = pos[e.target];
            if (!a || !b || b.col <= a.col) return null; // a direct node also reached indirectly: the direct link is enough
            const x1 = x(a.col) + NODE_W, y1 = y(a.row) + 22, x2 = x(b.col), y2 = y(b.row) + 22;
            const mid = (x1 + x2) / 2;
            const dim = related && !(related.has(e.source) && related.has(e.target));
            const pv = !!preview?.has(e.target);
            return (
              <path key={e.id} d={`M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`} strokeWidth={pv ? 2 : 1.5}
                className={edgeClass(e.status, pv)} style={{ opacity: dim ? 0.12 : 1 }} />
            );
          })}
        </svg>
        {graph.nodes.map((n) => {
          const p = pos[n.id];
          if (!p) return null;
          const Icon = ICON[n.type] || Database;
          const inEdge = graph.edges.find((e) => e.target === n.id);
          const isSel = selected.has(n.id);
          const pv = !!preview?.has(n.id);
          const changed = !!highlightChanged?.has(n.id);
          const off = n.status === "REVOKED" || n.status === "SUSPENDED";
          const clickable = !!onToggle && !!n.can_revoke;
          return (
            <div key={n.id}
              onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
              onClick={() => clickable && onToggle!(n)}
              title={nodeTitle(n, inEdge)}
              className={cn(
                "group absolute flex h-11 items-center gap-2 rounded-lg border bg-card px-2.5 shadow-sm transition-all duration-500 ease-out",
                n.impact === "ROOT" && "border-violet/50 shadow-violet/10 ring-2 ring-violet/15",
                n.status === "REVOKED" && "border-critical/50 bg-critical/[.04]",
                n.status === "SUSPENDED" && "border-warning/60 bg-warning/[.05]",
                n.status === "DEGRADED" && "border-dashed border-warning/60",
                n.impact === "INDIRECT" && n.status === "ACTIVE" && "border-dashed",
                pv && "graph-pulse border-critical",
                changed && "graph-pop",
                isSel && !pv && "border-critical ring-2 ring-critical/25",
                clickable && "cursor-pointer hover:-translate-y-px hover:shadow-md",
                related && !related.has(n.id) && "opacity-30",
              )}
              style={{ left: x(p.col), top: y(p.row), width: NODE_W, animationDelay: `${Math.min(p.row, 12) * 25}ms` }}>
              <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-md", TYPE_TONE[n.type], off && "grayscale")}><Icon className="h-3.5 w-3.5" /></span>
              <div className="min-w-0 flex-1">
                <div className={cn("truncate text-[12.5px] font-medium leading-tight", off && "text-muted-foreground line-through decoration-critical/60")}>{n.label}</div>
                <div className="truncate text-2xs text-muted-foreground">
                  {n.status !== "ACTIVE" ? <span className={cn("font-medium", n.status === "REVOKED" ? "text-critical" : "text-warning")}>{n.status === "DEGRADED" ? "Degraded" : n.status === "REVOKED" ? "Revoked" : "Cut off"}</span>
                    : inEdge?.permissions?.length ? inEdge.permissions.join(" · ") : n.sub}
                  {inEdge?.emergency && <span className="ml-1 text-critical">· Break-glass</span>}
                </div>
              </div>
              {onToggle && n.can_revoke && (
                <span className={cn("grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors", isSel ? "border-critical bg-critical text-white" : "border-border group-hover:border-critical/60")}>
                  {isSel && <Check className="h-3 w-3" />}
                </span>
              )}
              {n.criticality && n.status === "ACTIVE" && !n.can_revoke && (
                <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", n.criticality === "CRITICAL" ? "bg-critical" : n.criticality === "HIGH" ? "bg-serious" : n.criticality === "MEDIUM" ? "bg-warning" : "bg-muted-foreground/40")} />
              )}
            </div>
          );
        })}
        <ColumnLabel x={x(0)} label="Model / resource" />
        <ColumnLabel x={x(1)} label="Directly affected" />
        {hasCol2 && <ColumnLabel x={x(2)} label="Indirectly affected" />}
      </div>
    </div>
  );
}

function ColumnLabel({ x, label }: { x: number; label: string }) {
  return <div className="pointer-events-none absolute top-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground" style={{ left: x }}>{label}</div>;
}

function nodeTitle(n: GNode, e?: GEdge) {
  const parts = [n.label, n.sub];
  if (e?.permissions?.length) parts.push(`Permissions: ${e.permissions.join(", ")}`);
  if (e?.tokens) parts.push(`${e.tokens} live token(s)`);
  if (e?.expires_at) parts.push(`Expires ${fmtDate(e.expires_at)}`);
  if (n.description) parts.push(n.description);
  if (n.impact === "INDIRECT") parts.push("Indirect: depends on a resource that consumes this model");
  return parts.filter(Boolean).join("\n");
}

export function GraphLegend() {
  const item = (cls: string, label: string) => (
    <span className="inline-flex items-center gap-1.5"><svg width="26" height="6"><path d="M1,3 L25,3" strokeWidth={2} className={cls} /></svg>{label}</span>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted-foreground">
      {item("stroke-violet/60 graph-flow", "Live access")}
      {item("stroke-critical [stroke-dasharray:4_5]", "Revoked")}
      {item("stroke-warning [stroke-dasharray:4_5]", "API cut off")}
      {item("stroke-warning/70 [stroke-dasharray:1_5]", "Degraded (indirect)")}
      <span className="inline-flex items-center gap-1"><User className="h-3 w-3 text-info" />User</span>
      <span className="inline-flex items-center gap-1"><Bot className="h-3 w-3 text-violet" />AI agent</span>
      <span className="inline-flex items-center gap-1"><Plug className="h-3 w-3 text-success" />API / service</span>
    </div>
  );
}

/** Nodes that would go dark if the selected nodes are revoked (selected + everything downstream of them). */
export function downstreamOf(graph: Graph, ids: Set<string>) {
  const out = new Set(ids);
  let grew = true;
  while (grew) {
    grew = false;
    for (const e of graph.edges) if (out.has(e.source) && !out.has(e.target) && e.status === "ACTIVE") { out.add(e.target); grew = true; }
  }
  return out;
}

