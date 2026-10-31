"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

const VARS = ["series-1", "series-2", "series-3", "series-4", "status-good", "status-warning", "status-serious",
  "status-critical", "grid", "axis", "chart-surface"] as const;
type Palette = Record<(typeof VARS)[number], string>;

export function usePalette(): Palette {
  const { resolvedTheme } = useTheme();
  const read = () => {
    const out: any = {};
    if (typeof window === "undefined") return out;
    const cs = getComputedStyle(document.documentElement);
    VARS.forEach((v) => (out[v] = cs.getPropertyValue(`--${v}`).trim()));
    return out;
  };
  const [p, setP] = useState<Palette>(read);
  useEffect(() => { const id = requestAnimationFrame(() => setP(read())); return () => cancelAnimationFrame(id); }, [resolvedTheme]);
  return p;
}

export const STATUS_KEY: Record<string, keyof Palette> = { LOW: "status-good", MEDIUM: "status-warning", HIGH: "status-serious", CRITICAL: "status-critical" };

const shortDate = (v: string) => {
  if (/^\d{4}-\d{2}$/.test(v)) return new Date(v + "-01").toLocaleDateString(undefined, { month: "short" });
  const d = new Date(v);
  return isNaN(d.getTime()) ? v : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

function ChartTooltip({ active, payload, label, labelFmt }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-2.5 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-foreground">{labelFmt ? labelFmt(label) : label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-muted-foreground">
          <span className="h-2 w-2 rounded-sm" style={{ background: p.color || p.payload?.fill }} />
          <span className="capitalize">{String(p.name).replace(/_/g, " ")}</span>
          <span className="ml-auto pl-3 font-medium tabular text-foreground">{p.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted-foreground">
      {items.map((i) => <span key={i.label} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: i.color }} />{i.label}</span>)}
    </div>
  );
}

const axisProps = { tickLine: false, axisLine: false, fontSize: 11, tickMargin: 6 } as const;

export function AreaSeries({ data, x, y, height = 200, colorKey = "series-1", dateAxis = true }: { data: any[]; x: string; y: string; height?: number; colorKey?: keyof Palette; dateAxis?: boolean }) {
  const p = usePalette();
  const c = p[colorKey];
  const id = `g-${y}-${colorKey}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -6, bottom: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={c} stopOpacity={0.22} />
            <stop offset="100%" stopColor={c} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="0" />
        <XAxis dataKey={x} {...axisProps} tickFormatter={dateAxis ? shortDate : undefined} minTickGap={24} />
        <YAxis {...axisProps} allowDecimals={false} width={44} />
        <Tooltip content={<ChartTooltip labelFmt={dateAxis ? shortDate : undefined} />} cursor={{ stroke: p.axis, strokeDasharray: "3 3" }} />
        <Area type="monotone" dataKey={y} name={y} stroke={c} strokeWidth={2} fill={`url(#${id})`} activeDot={{ r: 4, strokeWidth: 2, stroke: p["chart-surface"] }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function LinesChart({ data, x, series, height = 200 }: { data: any[]; x: string; series: { key: string; label: string; color: keyof Palette }[]; height?: number }) {
  const p = usePalette();
  return (
    <div className="space-y-2">
      <Legend items={series.map((s) => ({ label: s.label, color: p[s.color] }))} />
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: -6, bottom: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey={x} {...axisProps} tickFormatter={shortDate} minTickGap={20} />
          <YAxis {...axisProps} allowDecimals={false} width={44} />
          <Tooltip content={<ChartTooltip labelFmt={shortDate} />} cursor={{ stroke: p.axis, strokeDasharray: "3 3" }} />
          {series.map((s) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={p[s.color]} strokeWidth={2} dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: p["chart-surface"] }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StackedBars({ data, x, series, height = 200, dateAxis = true }: { data: any[]; x: string; series: { key: string; label: string; color: keyof Palette }[]; height?: number; dateAxis?: boolean }) {
  const p = usePalette();
  return (
    <div className="space-y-2">
      {series.length > 1 && <Legend items={series.map((s) => ({ label: s.label, color: p[s.color] }))} />}
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -6, bottom: 0 }} barCategoryGap="28%">
          <CartesianGrid vertical={false} />
          <XAxis dataKey={x} {...axisProps} tickFormatter={dateAxis ? shortDate : undefined} minTickGap={12} />
          <YAxis {...axisProps} allowDecimals={false} width={44} />
          <Tooltip content={<ChartTooltip labelFmt={dateAxis ? shortDate : undefined} />} cursor={{ fill: p.grid, opacity: 0.5 }} />
          {series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} stackId="a" fill={p[s.color]} stroke={p["chart-surface"]} strokeWidth={series.length > 1 ? 1 : 0}
              radius={i === series.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]} maxBarSize={28} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function HBars({ data, label, value, height, colorKey = "series-1", colorFor }: { data: any[]; label: string; value: string; height?: number; colorKey?: keyof Palette; colorFor?: (row: any) => keyof Palette }) {
  const p = usePalette();
  const h = height || Math.max(120, data.length * 30 + 20);
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 28, left: 0, bottom: 0 }} barCategoryGap="30%">
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis type="category" dataKey={label} {...axisProps} width={150} tick={{ fontSize: 11 }} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: p.grid, opacity: 0.4 }} />
        <Bar dataKey={value} name={value} radius={[0, 4, 4, 0]} maxBarSize={18} label={{ position: "right", fontSize: 11, fill: p.axis }}>
          {data.map((row, i) => <Cell key={i} fill={p[colorFor ? colorFor(row) : colorKey]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
