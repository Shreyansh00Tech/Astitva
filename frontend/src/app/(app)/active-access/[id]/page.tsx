"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import {
  ArrowDown, ArrowLeft, ArrowUp, Brain, ChevronLeft, ChevronRight, Database, FlaskConical, Pencil, Play, Plus,
  Search, Settings2, ShieldCheck, Table2, Trash2,
} from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { cn, fmtDate } from "@/lib/utils";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, KV, LoadingRows, Mono, Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Perms, SensitivityBadge } from "@/components/status";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { HBars } from "@/components/charts";

const NOREVAL = { revalidateOnFocus: false };

function SimBadge({ children = "Simulated" }: { children?: React.ReactNode }) {
  return <Badge tone="violet" className="uppercase tracking-wide"><FlaskConical />{children}</Badge>;
}

function SimNote({ children }: { children: React.ReactNode }) {
  return <p className="mt-2 text-2xs font-medium uppercase tracking-wider text-violet">{children}</p>;
}

function fmtCell(v: any, type?: string) {
  if (v === null || v === undefined || v === "") return <span className="text-muted-foreground/60">—</span>;
  if (type === "boolean") return v ? "Yes" : "No";
  if (type === "number") return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(v);
}

// ------------------------------------------------------------------ records table
function RecordForm({ columns, initial, onSubmit, onClose, title }: { columns: any[]; initial?: any; onSubmit: (v: any) => Promise<void>; onClose: () => void; title: string }) {
  const editable = columns.filter((c) => c.editable);
  const [v, setV] = useState<any>(() => Object.fromEntries(editable.map((c) => [c.name, initial?.[c.name] ?? (c.type === "boolean" ? false : c.type === "category" && !c.nullable ? c.options[0] : "")])));
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    const out: any = {};
    for (const c of editable) {
      const x = v[c.name];
      out[c.name] = x === "" ? null : c.type === "number" || c.type === "integer" ? Number(x) : x;
      if (initial && out[c.name] === initial[c.name]) delete out[c.name];
    }
    try { await onSubmit(out); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={title} description="Synthetic demo record. Every change is validated by the server and audited.">
        <div className="grid gap-3 sm:grid-cols-2">
          {editable.map((c) => (
            <Field key={c.name} label={c.name} hint={c.description}>
              {c.type === "category" ? (
                <Select value={v[c.name] ?? ""} onChange={(e) => setV({ ...v, [c.name]: e.target.value })}>
                  {c.nullable && <option value="">—</option>}
                  {c.options.map((o: string) => <option key={o}>{o}</option>)}
                </Select>
              ) : c.type === "boolean" ? (
                <Select value={String(!!v[c.name])} onChange={(e) => setV({ ...v, [c.name]: e.target.value === "true" })}>
                  <option value="false">No</option><option value="true">Yes</option>
                </Select>
              ) : (
                <Input type={c.type === "date" ? "date" : c.type === "number" || c.type === "integer" ? "number" : "text"}
                  step={c.type === "integer" ? 1 : "any"} min={c.min ?? undefined} max={c.max ?? undefined}
                  value={v[c.name] ?? ""} onChange={(e) => setV({ ...v, [c.name]: e.target.value })} />
              )}
            </Field>
          ))}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button loading={busy} onClick={submit}>Save</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RecordsTable({ rid, table, actions, onChanged }: { rid: string; table: any; actions: any; onChanged: () => void }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<string | null>(null);
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [deleting, setDeleting] = useState<any>(null);
  useEffect(() => { const t = setTimeout(() => { setQuery(q); setPage(1); }, 250); return () => clearTimeout(t); }, [q]);
  useEffect(() => { setPage(1); setSort(null); setQ(""); }, [table.name]);
  const key = `/api/workspace/${rid}/records?table=${table.name}&page=${page}&size=10${query ? `&q=${encodeURIComponent(query)}` : ""}${sort ? `&sort=${sort}&dir=${dir}` : ""}`;
  const { data, error, isLoading, mutate } = useSWR(key, fetcher, { ...NOREVAL, keepPreviousData: true });
  const cols = table.columns;
  const changed = () => { mutate(); onChanged(); };
  const toggleSort = (c: string) => { if (sort === c) setDir(dir === "asc" ? "desc" : "asc"); else { setSort(c); setDir("asc"); } setPage(1); };
  const showRowActions = actions.edit_record || actions.delete_record;
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2">Data preview <SimBadge>Synthetic demo data</SimBadge>{data?.masked && <Badge tone="warning">Identifiers masked by admin</Badge>}</span>}
        description="Fictional rows only. Search, sort and paging never change the data."
        action={actions.add_record && <Button size="sm" onClick={() => setAdding(true)}><Plus />Add record</Button>} />
      <div className="flex items-center gap-2 px-4 pb-3">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search records" className="h-9 pl-8" />
        </div>
        {data && <span className="text-xs text-muted-foreground">{data.total} matching</span>}
      </div>
      {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading && !data ? <LoadingRows /> : !data.rows.length ? <EmptyState title="No matching records" /> : (
        <Table>
          <THead><TR>{cols.map((c: any) => (
            <TH key={c.name}><button className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => toggleSort(c.name)}>
              {c.name}{sort === c.name && (dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}</button></TH>))}
            {showRowActions && <TH className="text-right">Actions</TH>}</TR></THead>
          <TBody>
            {data.rows.map((r: any) => (
              <TR key={r.id}>
                {cols.map((c: any) => <TD key={c.name} className={cn("whitespace-nowrap", c.key && "font-mono text-[12px]", (c.type === "number" || c.type === "integer") && "tabular")}>{fmtCell(r.data[c.name], c.type)}</TD>)}
                {showRowActions && (
                  <TD className="text-right"><div className="flex justify-end gap-1">
                    {actions.edit_record && <Button size="sm" variant="ghost" onClick={() => setEditing(r)} aria-label="Edit"><Pencil /></Button>}
                    {actions.delete_record && <Button size="sm" variant="ghost" className="text-critical" onClick={() => setDeleting(r)} aria-label="Delete"><Trash2 /></Button>}
                  </div></TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      {data && data.pages > 1 && (
        <div className="flex items-center justify-end gap-2 border-t px-4 py-2 text-xs text-muted-foreground">
          Page {data.page} of {data.pages}
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft /></Button>
          <Button size="sm" variant="outline" disabled={page >= data.pages} onClick={() => setPage(page + 1)}><ChevronRight /></Button>
        </div>
      )}
      {adding && <RecordForm title="Add synthetic record" columns={cols} onClose={() => setAdding(false)}
        onSubmit={async (v) => { try { await api(`/api/workspace/${rid}/records`, { json: { table: table.name, values: v } }); toast.success("Record added"); setAdding(false); changed(); } catch (e) { toast.error(errorMessage(e)); } }} />}
      {editing && <RecordForm title={`Edit ${editing.key}`} columns={cols} initial={editing.data} onClose={() => setEditing(null)}
        onSubmit={async (v) => { try { await api(`/api/workspace/${rid}/records/${editing.id}`, { method: "PATCH", json: { table: table.name, values: v } }); toast.success("Record updated"); setEditing(null); changed(); } catch (e) { toast.error(errorMessage(e)); } }} />}
      {deleting && (
        <Dialog open onOpenChange={(o) => !o && setDeleting(null)}>
          <DialogContent title={`Delete ${deleting.key}?`} description="Removes this synthetic record from the demo table. The action is audited.">
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleting(null)}>Cancel</Button>
              <Button variant="destructive" onClick={async () => { try { await api(`/api/workspace/${rid}/records/${deleting.id}?table=${table.name}`, { method: "DELETE" }); toast.success("Record deleted"); setDeleting(null); changed(); } catch (e) { toast.error(errorMessage(e)); } }}><Trash2 />Delete</Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </Card>
  );
}

function SchemaCard({ table }: { table: any }) {
  return (
    <Card>
      <CardHeader title="Schema and columns" description={`${table.columns.length} columns · matches the rows in the data preview`} />
      <Table>
        <THead><TR><TH>Column</TH><TH>Data type</TH><TH>Description</TH><TH>Allowed values</TH></TR></THead>
        <TBody>{table.columns.map((c: any) => (
          <TR key={c.name}>
            <TD><Mono>{c.name}</Mono>{c.key && <Badge tone="outline" className="ml-1.5">key</Badge>}{c.pii && <Badge tone="warning" className="ml-1.5">identifier</Badge>}</TD>
            <TD className="capitalize">{c.type}{c.nullable ? " (optional)" : ""}</TD>
            <TD className="text-muted-foreground">{c.description}</TD>
            <TD className="text-xs text-muted-foreground">{c.options ? c.options.join(", ") : c.min !== null && c.max !== null ? `${c.min} to ${c.max}` : "—"}</TD>
          </TR>))}
        </TBody>
      </Table>
    </Card>
  );
}

function StatsCard({ rid, table, chartColumn, version }: { rid: string; table: any; chartColumn?: string; version: number }) {
  const { data, error } = useSWR(`/api/workspace/${rid}/stats?table=${table.name}&v=${version}`, fetcher, NOREVAL);
  if (error) return <Card><ErrorState error={error} /></Card>;
  if (!data) return <Card><LoadingRows rows={3} /></Card>;
  const catCols = Object.keys(data.categories);
  const chartCol = chartColumn && data.categories[chartColumn] ? chartColumn : catCols[0];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[["Total records", data.records], ["Columns", data.columns], ["Missing values", data.missing_values], ["Category columns", catCols.length]].map(([k, v]) => (
          <Card key={k as string} className="p-4"><div className="text-2xs uppercase tracking-wider text-muted-foreground">{k}</div><div className="mt-1 text-2xl font-semibold tabular">{v}</div></Card>
        ))}
      </div>
      <p className="text-2xs text-muted-foreground">Calculated live from the synthetic rows above, so the numbers change when a record is added, edited or deleted.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        {chartCol && (
          <Card><CardHeader title={`Distribution: ${chartCol}`} description="Count of synthetic records per value" />
            <CardBody><HBars data={data.categories[chartCol]} label="value" value="count" colorKey="series-2" /></CardBody></Card>
        )}
        <Card>
          <CardHeader title="Numeric columns" description="Summary statistics" />
          {Object.keys(data.numeric).length ? (
            <Table><THead><TR><TH>Column</TH><TH className="text-right">Min</TH><TH className="text-right">Mean</TH><TH className="text-right">Median</TH><TH className="text-right">Max</TH></TR></THead>
              <TBody>{Object.entries(data.numeric).map(([k, s]: any) => (
                <TR key={k}><TD><Mono>{k}</Mono></TD>{["min", "mean", "median", "max"].map((m) => <TD key={m} className="text-right tabular">{fmtCell(s[m], "number")}</TD>)}</TR>))}
              </TBody></Table>
          ) : <EmptyState title="No numeric columns" />}
          {Object.keys(data.booleans).length > 0 && (
            <CardBody className="pt-3">{Object.entries(data.booleans).map(([k, b]: any) => <KV key={k} k={k} v={`Yes ${b.true} · No ${b.false}`} />)}</CardBody>
          )}
        </Card>
      </div>
      {catCols.length > 1 && (
        <Card><CardHeader title="Category breakdown" />
          <CardBody className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
            {catCols.map((c) => <div key={c}><div className="mb-1 font-mono text-[12px] text-muted-foreground">{c}</div>
              {data.categories[c].map((x: any) => <KV key={x.value} k={x.value} v={x.count} className="py-0.5" />)}</div>)}
          </CardBody></Card>
      )}
      <Card><CardHeader title="Missing values by column" />
        <CardBody className="grid gap-x-6 sm:grid-cols-3">{Object.entries(data.missing_by_column).map(([k, v]: any) => <KV key={k} k={k} v={v} />)}</CardBody></Card>
    </div>
  );
}

function QueryCard({ rid, table }: { rid: string; table: any }) {
  const cols = table.columns;
  const groupable = cols.filter((c: any) => c.type === "category" || c.type === "boolean");
  const numeric = cols.filter((c: any) => c.type === "number" || c.type === "integer");
  const [f, setF] = useState({ column: cols[1]?.name || cols[0].name, op: "eq", value: "" });
  const [useFilter, setUseFilter] = useState(false);
  const [groupBy, setGroupBy] = useState(groupable[0]?.name || "");
  const [metric, setMetric] = useState("count");
  const [metricCol, setMetricCol] = useState(numeric[0]?.name || "");
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setRes(null); setF({ column: cols[1]?.name || cols[0].name, op: "eq", value: "" }); setGroupBy(groupable[0]?.name || ""); setMetricCol(numeric[0]?.name || ""); }, [table.name]); // eslint-disable-line react-hooks/exhaustive-deps
  const col = cols.find((c: any) => c.name === f.column);
  const run = async () => {
    setBusy(true);
    try {
      setRes(await api(`/api/workspace/${rid}/query`, { json: { table: table.name, filters: useFilter ? [f] : [], group_by: groupBy || null, metric, metric_column: metric === "count" ? null : metricCol } }));
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2">Run a demo query <SimBadge /></span>} description="A mock filter and aggregate over the synthetic rows. No real database is queried." />
      <CardBody className="space-y-3">
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={useFilter} onChange={(e) => setUseFilter(e.target.checked)} />Filter rows</label>
        {useFilter && (
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Column"><Select value={f.column} onChange={(e) => setF({ ...f, column: e.target.value, value: "" })}>{cols.map((c: any) => <option key={c.name}>{c.name}</option>)}</Select></Field>
            <Field label="Operator"><Select value={f.op} onChange={(e) => setF({ ...f, op: e.target.value })}>
              <option value="eq">equals</option><option value="neq">not equal</option><option value="contains">contains</option>
              {(col?.type === "number" || col?.type === "integer" || col?.type === "date") && <><option value="gt">greater than</option><option value="lt">less than</option></>}
            </Select></Field>
            <Field label="Value">{col?.options ? <Select value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })}><option value="">Choose</option>{col.options.map((o: string) => <option key={o}>{o}</option>)}</Select>
              : col?.type === "boolean" ? <Select value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })}><option value="true">Yes</option><option value="false">No</option></Select>
              : <Input value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} />}</Field>
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Group by"><Select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}><option value="">No grouping (show rows)</option>{groupable.map((c: any) => <option key={c.name}>{c.name}</option>)}</Select></Field>
          {groupBy && <Field label="Metric"><Select value={metric} onChange={(e) => setMetric(e.target.value)}><option value="count">count</option>{numeric.length > 0 && <><option value="avg">average</option><option value="sum">sum</option></>}</Select></Field>}
          {groupBy && metric !== "count" && <Field label="Of column"><Select value={metricCol} onChange={(e) => setMetricCol(e.target.value)}>{numeric.map((c: any) => <option key={c.name}>{c.name}</option>)}</Select></Field>}
        </div>
        <div className="flex justify-end"><Button loading={busy} onClick={run}><Play />Run demo query</Button></div>
        {res && (
          <div className="rounded-md border border-violet/30 bg-violet/5 p-3 animate-fade-in">
            <SimNote>{res.label}</SimNote>
            <pre className="mt-2 overflow-x-auto rounded bg-muted p-2 font-mono text-2xs scroll-thin">{res.sql}</pre>
            <p className="mt-2 text-xs text-muted-foreground">{res.matched} matching synthetic rows</p>
            {res.mode === "aggregate" ? (
              <Table><THead><TR><TH>{groupBy}</TH><TH className="text-right">{metric}{metric !== "count" ? `(${metricCol})` : ""}</TH></TR></THead>
                <TBody>{res.groups.map((g: any) => <TR key={String(g.group)}><TD>{fmtCell(g.group)}</TD><TD className="text-right tabular">{fmtCell(g.value, "number")}</TD></TR>)}</TBody></Table>
            ) : (
              <Table><THead><TR>{cols.map((c: any) => <TH key={c.name}>{c.name}</TH>)}</TR></THead>
                <TBody>{res.rows.map((r: any) => <TR key={r.id}>{cols.map((c: any) => <TD key={c.name} className="whitespace-nowrap">{fmtCell(r.data[c.name], c.type)}</TD>)}</TR>)}</TBody></Table>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

// ------------------------------------------------------------------ admin
function AdminCard({ rid }: { rid: string }) {
  const { data, error, mutate } = useSWR(`/api/workspace/${rid}/admin`, fetcher, NOREVAL);
  if (error) return <Card><ErrorState error={error} /></Card>;
  if (!data) return <Card><LoadingRows rows={3} /></Card>;
  const set = async (k: string, v: boolean) => { try { await api(`/api/workspace/${rid}/settings`, { method: "PATCH", json: { [k]: v } }); toast.success("Setting saved"); mutate(); } catch (e) { toast.error(errorMessage(e)); } };
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Administrative settings" description="Simulated settings. Changes are audited." />
        <CardBody className="space-y-2">
          {data.settings_apply === "DATA" ? (
            <label className="flex items-start gap-2 text-[13px]"><input type="checkbox" className="mt-1" checked={data.settings.mask_identifiers} onChange={(e) => set("mask_identifiers", e.target.checked)} />
              <span>Mask identifier columns for non-admin holders<span className="block text-xs text-muted-foreground">Columns marked “identifier” are shown partly hidden to anyone without ADMIN, and cannot be filtered on.</span></span></label>
          ) : (
            <label className="flex items-start gap-2 text-[13px]"><input type="checkbox" className="mt-1" checked={data.settings.inference_logging} onChange={(e) => set("inference_logging", e.target.checked)} />
              <span>Keep a log of demo predictions<span className="block text-xs text-muted-foreground">Mock flag only. Every prediction is audited regardless.</span></span></label>
          )}
          <p className="pt-1 text-xs text-muted-foreground"><ShieldCheck className="mr-1 inline h-3.5 w-3.5" />{data.policy_note}</p>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Who holds access" description="Active grants on this resource" />
        <Table><THead><TR><TH>Person</TH><TH>Permissions</TH><TH>Purpose</TH><TH>Expires</TH></TR></THead>
          <TBody>{data.holders.map((h: any, i: number) => <TR key={i}><TD className="font-medium">{h.user.name}</TD><TD><Perms perms={h.permissions} /></TD><TD className="text-muted-foreground">{h.purpose_label}</TD><TD className="text-xs">{h.expires_at ? fmtDate(h.expires_at) : "Standing"}</TD></TR>)}</TBody></Table>
      </Card>
      <Card>
        <CardHeader title="Recent workspace activity" />
        {data.activity.length ? (
          <Table><THead><TR><TH>When</TH><TH>Who</TH><TH>Action</TH><TH>Result</TH></TR></THead>
            <TBody>{data.activity.map((a: any, i: number) => <TR key={i}><TD className="whitespace-nowrap text-xs">{fmtDate(a.at)}</TD><TD>{a.actor}</TD><TD><Mono>{a.action}</Mono></TD>
              <TD><Badge tone={a.allowed ? "success" : "critical"}>{a.allowed ? "Allowed" : "Denied"}</Badge> <span className="text-xs text-muted-foreground">{a.reason}</span></TD></TR>)}</TBody></Table>
        ) : <EmptyState title="No activity yet" />}
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ model
function Playground({ rid, pg }: { rid: string; pg: any }) {
  const defaults = Object.fromEntries(pg.inputs.map((f: any) => [f.name, f.default]));
  const [v, setV] = useState<any>(defaults);
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setRes(await api(`/api/workspace/${rid}/predict`, { json: { values: v } })); } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); } };
  const tone = res?.level === "High" ? "critical" : res?.level === "Medium" ? "warning" : "success";
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2">Try a Demo Prediction <SimBadge /></span>} description="Enter fictional values or pick an example. A fixed demo formula produces the result; no model or external service is called." />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap gap-2">{pg.presets.map((p: any) => <Button key={p.label} size="sm" variant="subtle" onClick={() => { setV({ ...defaults, ...p.values }); setRes(null); }}>{p.label}</Button>)}</div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {pg.inputs.map((f: any) => (
            <Field key={f.name} label={f.label}>
              {f.type === "category" ? <Select value={v[f.name]} onChange={(e) => setV({ ...v, [f.name]: e.target.value })}>{f.options.map((o: string) => <option key={o}>{o}</option>)}</Select>
                : f.type === "boolean" ? <Select value={String(v[f.name])} onChange={(e) => setV({ ...v, [f.name]: e.target.value === "true" })}><option value="false">No</option><option value="true">Yes</option></Select>
                : <Input type="number" min={f.min ?? undefined} max={f.max ?? undefined} step={f.step ?? (f.type === "integer" ? 1 : "any")} value={v[f.name]} onChange={(e) => setV({ ...v, [f.name]: e.target.value === "" ? "" : Number(e.target.value) })} />}
            </Field>
          ))}
        </div>
        <div className="flex justify-end"><Button variant="accent" loading={busy} onClick={run}><Play />Run Demo</Button></div>
        {res && (
          <div className="rounded-lg border border-violet/30 bg-violet/5 p-4 animate-fade-in">
            <SimNote>{res.label}</SimNote>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div><div className="text-2xs uppercase tracking-wider text-muted-foreground">{res.score_label}</div><div className="text-2xl font-semibold tabular">{res.score}</div></div>
              <div><div className="text-2xs uppercase tracking-wider text-muted-foreground">Illustrative result</div><div className="text-base font-semibold">{res.predicted_class}</div></div>
              {res.level && <div><div className="text-2xs uppercase tracking-wider text-muted-foreground">Risk level</div><Badge tone={tone as any} className="mt-1">{res.level}</Badge></div>}
            </div>
            {res.recommendations && (
              <ol className="mt-3 space-y-1 text-[13px]">{res.recommendations.map((r: any, i: number) => <li key={r.item} className="flex justify-between"><span>{i + 1}. {r.item}</span><span className="tabular text-muted-foreground">{r.score}</span></li>)}</ol>
            )}
            <p className="mt-3 text-xs text-muted-foreground">{res.explanation}</p>
            <p className="mt-1 text-2xs text-muted-foreground">{res.engine}</p>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function MetadataEditor({ rid, m, onSaved }: { rid: string; m: any; onSaved: () => void }) {
  const [f, setF] = useState({ description: m.description || "", monitoring_notes: m.monitoring_notes || "", decision_threshold: m.decision_threshold });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const body: any = { description: f.description, monitoring_notes: f.monitoring_notes };
      if (m.decision_threshold !== null && m.decision_threshold !== undefined) body.decision_threshold = Number(f.decision_threshold);
      await api(`/api/workspace/${rid}/metadata`, { method: "PATCH", json: body }); toast.success("Model metadata saved"); onSaved();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader title="Edit model metadata" description="WRITE lets you change descriptive fields and the demo decision threshold. It does not retrain or deploy anything." />
      <CardBody className="space-y-3">
        <Field label="Description"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Monitoring notes"><Textarea value={f.monitoring_notes} onChange={(e) => setF({ ...f, monitoring_notes: e.target.value })} placeholder="e.g. Weekly drift review (demo)" /></Field>
        {m.decision_threshold !== null && m.decision_threshold !== undefined && (
          <Field label={`Demo decision threshold: ${Number(f.decision_threshold).toFixed(2)}`} hint="Used by the demo playground to turn a score into a class.">
            <input type="range" min={0.05} max={0.95} step={0.05} value={f.decision_threshold} onChange={(e) => setF({ ...f, decision_threshold: Number(e.target.value) })} className="w-full accent-[hsl(var(--violet))]" />
          </Field>
        )}
        <div className="flex justify-end"><Button loading={busy} onClick={save}>Save metadata</Button></div>
      </CardBody>
    </Card>
  );
}

function ModelView({ d, rid, refresh }: { d: any; rid: string; refresh: () => void }) {
  const m = d.model;
  const a = d.actions;
  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        {a.view && <TabsTrigger value="performance">Performance</TabsTrigger>}
        {a.view && <TabsTrigger value="predictions">Sample predictions</TabsTrigger>}
        {a.view && <TabsTrigger value="explain">Explainability</TabsTrigger>}
        {a.run_prediction && <TabsTrigger value="playground">Try a demo prediction</TabsTrigger>}
        {a.edit_metadata && <TabsTrigger value="metadata">Edit metadata</TabsTrigger>}
        {a.admin && <TabsTrigger value="admin">Admin</TabsTrigger>}
      </TabsList>
      <TabsContent value="overview">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card><CardHeader title="Model overview" />
            <CardBody>
              <KV k="Model type" v={m.task} /><KV k="Algorithm" v={m.algorithm} /><KV k="Version" v={m.version} />
              <KV k="Classification" v={<SensitivityBadge level={d.resource.sensitivity} />} /><KV k="Owner / team" v={m.owner_team} />
              <KV k="Prediction target" v={m.target} /><KV k="Created" v={m.created} /><KV k="Last updated" v={fmtDate(m.updated, false)} />
              <KV k="Status" v={<Badge tone="violet">{m.status}</Badge>} />
            </CardBody></Card>
          <Card><CardHeader title="About" description={m.status_note} />
            <CardBody className="space-y-2 text-[13px]">
              <p>{m.description}</p>
              {m.monitoring_notes && <p className="text-xs text-muted-foreground">Monitoring notes: {m.monitoring_notes}</p>}
              {d.read_restricted && <p className="text-xs text-warning">Your grant does not include READ, so metrics, samples and explainability are hidden.</p>}
            </CardBody></Card>
        </div>
      </TabsContent>
      {a.view && (
        <TabsContent value="performance">
          <Card><CardHeader title="Model performance" description="Illustrative numbers. No real model was trained or evaluated." />
            <Table><THead><TR><TH>Metric</TH><TH className="text-right">Simulated value</TH></TR></THead>
              <TBody>{m.metrics.map((x: any) => <TR key={x.name}><TD>{x.name}</TD><TD className="text-right font-medium tabular">{x.value}</TD></TR>)}</TBody></Table>
            <CardBody className="pt-2"><SimNote>{m.metrics_label}</SimNote></CardBody>
          </Card>
        </TabsContent>
      )}
      {a.view && (
        <TabsContent value="predictions">
          <Card><CardHeader title="Sample predictions" description={m.samples.label} />
            <Table><THead><TR>{m.samples.columns.map((c: string) => <TH key={c}>{c}</TH>)}</TR></THead>
              <TBody>{m.samples.rows.map((r: any[], i: number) => <TR key={i}>{r.map((v, j) => <TD key={j} className={cn(j === 0 && "font-mono text-[12px]")}>{v}</TD>)}</TR>)}</TBody></Table>
            <CardBody className="pt-2"><SimNote>Pre-generated demo examples</SimNote></CardBody>
          </Card>
        </TabsContent>
      )}
      {a.view && (
        <TabsContent value="explain">
          <Card><CardHeader title="Model features and explainability" description="Fictional input features and how much each one matters" />
            <CardBody><HBars data={m.features.map((f: any) => ({ feature: f.name, importance: f.importance }))} label="feature" value="importance" colorKey="series-1" />
              <SimNote>{m.features_label}</SimNote></CardBody></Card>
        </TabsContent>
      )}
      {a.run_prediction && m.playground && <TabsContent value="playground"><Playground rid={rid} pg={m.playground} /></TabsContent>}
      {a.edit_metadata && <TabsContent value="metadata"><MetadataEditor rid={rid} m={m} onSaved={refresh} /></TabsContent>}
      {a.admin && <TabsContent value="admin"><AdminCard rid={rid} /></TabsContent>}
    </Tabs>
  );
}

// ------------------------------------------------------------------ dataset / database
function DataView({ d, rid, refresh }: { d: any; rid: string; refresh: () => void }) {
  const isDb = d.kind === "DATABASE";
  const info = isDb ? d.database : d.dataset;
  const tables = info.tables || [];
  const [tname, setTname] = useState<string>(tables[0]?.name || "");
  const [version, setVersion] = useState(0);
  const table = tables.find((t: any) => t.name === tname) || tables[0];
  const a = d.actions;
  const changed = () => { setVersion((x) => x + 1); refresh(); };
  const tablePicker = isDb && tables.length > 1 && (
    <div className="mb-3 flex flex-wrap items-center gap-2"><span className="text-xs text-muted-foreground">Table</span>
      {tables.map((t: any) => <Button key={t.name} size="sm" variant={t.name === table.name ? "default" : "outline"} onClick={() => setTname(t.name)}><Table2 />{t.name}<span className="opacity-60">{t.records}</span></Button>)}</div>
  );
  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        {a.view && <TabsTrigger value="data">{isDb ? "Tables and rows" : "Data preview"}</TabsTrigger>}
        {a.view && <TabsTrigger value="schema">Schema</TabsTrigger>}
        {a.view && <TabsTrigger value="stats">Statistics</TabsTrigger>}
        {a.run_query && <TabsTrigger value="query">Demo query</TabsTrigger>}
        {a.admin && <TabsTrigger value="admin">Admin</TabsTrigger>}
      </TabsList>
      <TabsContent value="overview">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card><CardHeader title={isDb ? "Database overview" : "Dataset overview"} />
            <CardBody>
              {isDb ? <><KV k="Engine" v={info.engine} /><KV k="Schema" v={<Mono>{info.schema}</Mono>} /></> : <KV k="Dataset ID" v={<Mono>{info.dataset_id}</Mono>} />}
              <KV k="Classification" v={<SensitivityBadge level={d.resource.sensitivity} />} /><KV k="Owner / team" v={info.owner_team} />
              {!isDb && a.view && <><KV k="Records" v={`${info.records} fictional records`} /><KV k="Columns" v={info.columns} /><KV k="Last updated" v={fmtDate(info.last_updated)} /></>}
              {isDb && a.view && <KV k="Tables" v={tables.length} />}
              <KV k="Status" v={<Badge tone="violet">{info.status}</Badge>} />
            </CardBody></Card>
          <Card><CardHeader title="Description and purpose" />
            <CardBody className="space-y-2 text-[13px]"><p>{d.resource.description}</p>{!isDb && <p className="text-muted-foreground">{info.purpose}</p>}
              {d.read_restricted && <p className="text-xs text-warning">Your grant does not include READ, so rows and statistics are hidden.</p>}</CardBody></Card>
        </div>
        {isDb && a.view && (
          <Card className="mt-4"><CardHeader title="Tables" description="Fictional tables with table-level record counts" />
            <Table><THead><TR><TH>Table</TH><TH className="text-right">Records</TH><TH className="text-right">Columns</TH><TH>Last updated</TH></TR></THead>
              <TBody>{tables.map((t: any) => <TR key={t.name}><TD><Mono>{t.name}</Mono></TD><TD className="text-right tabular">{t.records}</TD><TD className="text-right tabular">{t.columns.length}</TD><TD className="text-xs text-muted-foreground">{fmtDate(t.last_updated)}</TD></TR>)}</TBody></Table></Card>
        )}
      </TabsContent>
      {a.view && table && <TabsContent value="data">{tablePicker}<RecordsTable rid={rid} table={table} actions={a} onChanged={changed} /></TabsContent>}
      {a.view && table && <TabsContent value="schema">{tablePicker}<SchemaCard table={table} /></TabsContent>}
      {a.view && table && <TabsContent value="stats">{tablePicker}<StatsCard rid={rid} table={table} chartColumn={info.chart_column} version={version} /></TabsContent>}
      {a.run_query && table && <TabsContent value="query">{tablePicker}<QueryCard rid={rid} table={table} /></TabsContent>}
      {a.admin && <TabsContent value="admin"><AdminCard rid={rid} /></TabsContent>}
    </Tabs>
  );
}

export default function ResourceWorkspace({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: d, error, mutate } = useSWR(`/api/workspace/${id}`, fetcher, NOREVAL);
  const back = <Link href="/active-access" className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />Active access</Link>;
  if (error) {
    const code = error?.data?.detail?.code;
    return <>{back}<Card>{error.status === 403 ? (
      <EmptyState icon={ShieldCheck} title={code === "GRANT_EXPIRED" ? "Your access has expired" : code === "POLICY_DENIED" ? "Blocked by access policy" : "No active access"}
        description={errorMessage(error)} action={<Button asChild variant="outline"><Link href="/requests">Request access</Link></Button>} />
    ) : <ErrorState error={error} onRetry={() => mutate()} />}</Card></>;
  }
  if (!d) return <>{back}<Skeleton className="mb-4 h-20 w-full" /><LoadingRows /></>;
  const Icon = d.kind === "MODEL" ? Brain : Database;
  return (
    <>
      {back}
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg border bg-muted/50 p-2.5"><Icon className="h-5 w-5 text-violet" /></div>
          <div>
            <div className="flex flex-wrap items-center gap-2"><h1 className="text-lg font-semibold tracking-tight">{d.resource.name}</h1>
              <SensitivityBadge level={d.resource.sensitivity} /><SimBadge>{d.kind === "MODEL" ? "Demo only" : "Synthetic demo data"}</SimBadge></div>
            <p className="mt-0.5 text-xs text-muted-foreground"><Mono>{d.resource.code}</Mono> · {d.resource.department} · {d.kind === "MODEL" ? "ML model" : d.kind === "DATABASE" ? "Database" : "Dataset"}</p>
          </div>
        </div>
        <Card className="min-w-[260px] p-3">
          <div className="text-2xs uppercase tracking-wider text-muted-foreground">Your access</div>
          <div className="mt-1"><Perms perms={d.permissions} /></div>
          <div className="mt-2 text-xs text-muted-foreground">{d.grant.purpose_label} · {d.expires_at ? `expires ${fmtDate(d.expires_at)}` : "standing access"}</div>
          {d.grant.request_id && <Link href={`/requests/${d.grant.request_id}`} className="mt-1 inline-flex items-center gap-1 text-2xs text-violet hover:underline"><Settings2 className="h-3 w-3" />Approved request</Link>}
        </Card>
      </div>
      <div className="mb-4 rounded-md border border-violet/25 bg-violet/5 px-3 py-2 text-xs text-muted-foreground"><FlaskConical className="mr-1.5 inline h-3.5 w-3.5 text-violet" />{d.disclaimer} Only the actions your grant allows are shown, and the server checks each one again.</div>
      {d.kind === "MODEL" ? <ModelView d={d} rid={id} refresh={() => mutate()} /> : <DataView d={d} rid={id} refresh={() => mutate()} />}
    </>
  );
}
