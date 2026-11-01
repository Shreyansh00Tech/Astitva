"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Trash2 } from "lucide-react";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CAT, PLANNER_CATS, addDays, dateInput, deletePlanner, savePlanner, timeInput } from "@/lib/planner";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export type PlannerDraft = { item?: any; start?: Date };

/** Add or edit one task on the employee's own calendar. */
export function PlannerDialog({ draft, onClose }: { draft: PlannerDraft | null; onClose: () => void }) {
  const item = draft?.item;
  const [f, setF] = useState({ title: "", notes: "", category: "WORK", priority: "MEDIUM", date: "", start: "", end: "", all_day: false, done: false });
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!draft) return;
    setErr("");
    if (item) {
      const s = new Date(item.start_at), e = new Date(item.end_at);
      setF({ title: item.title, notes: item.notes || "", category: item.category, priority: item.priority, date: dateInput(s),
        start: timeInput(s), end: timeInput(e), all_day: item.all_day, done: item.done });
    } else {
      const s = draft.start || (() => { const n = new Date(); n.setMinutes(n.getMinutes() < 30 ? 30 : 60, 0, 0); return n; })();
      const e = new Date(s.getTime() + 60 * 60000);
      setF({ title: "", notes: "", category: "WORK", priority: "MEDIUM", date: dateInput(s), start: timeInput(s), end: timeInput(e), all_day: false, done: false });
    }
  }, [draft, item]);

  const set = (k: keyof typeof f) => (e: any) => setF((p) => ({ ...p, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!f.title.trim()) return setErr("Give the task a title");
    let start: Date, end: Date;
    if (f.all_day) {
      start = new Date(`${f.date}T00:00`);
      end = addDays(start, 1); end.setMinutes(-1); // 23:59 the same day
    } else {
      start = new Date(`${f.date}T${f.start}`);
      end = new Date(`${f.date}T${f.end}`);
      if (end <= start) return setErr("End time must be after the start time");
    }
    setBusy("save");
    try {
      await savePlanner(item?.id ?? null, { title: f.title, notes: f.notes || null, category: f.category, priority: f.priority,
        start_at: start.toISOString(), end_at: end.toISOString(), all_day: f.all_day, done: f.done });
      toast.success(item ? "Task updated" : "Task added to your calendar");
      onClose();
    } catch (e2) { setErr(errorMessage(e2)); } finally { setBusy(""); }
  }

  async function remove() {
    setBusy("delete");
    try { await deletePlanner(item.id); toast.success("Task removed"); onClose(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(""); }
  }

  return (
    <Dialog open={!!draft} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={item ? "Edit task" : "New task"} description="Only you can see the tasks on your calendar.">
        <form onSubmit={submit} className="space-y-3.5">
          <Field label="Title"><Input autoFocus value={f.title} onChange={set("title")} maxLength={160} placeholder="e.g. Review fraud model PR" /></Field>
          <div>
            <div className="mb-1.5 text-xs font-medium text-foreground/80">Calendar</div>
            <div className="flex flex-wrap gap-1.5">
              {PLANNER_CATS.map((c) => (
                <button type="button" key={c} onClick={() => setF((p) => ({ ...p, category: c }))}
                  className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
                    f.category === c ? "border-foreground/70 bg-foreground/[0.04] font-medium" : "text-muted-foreground hover:bg-accent")}>
                  <i className={cn("h-2 w-2 rounded-full", CAT[c].dot)} />{CAT[c].label}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-[1.4fr_1fr_1fr] gap-2">
            <Field label="Date"><Input type="date" value={f.date} onChange={set("date")} required /></Field>
            <Field label="Start"><Input type="time" value={f.start} onChange={set("start")} disabled={f.all_day} /></Field>
            <Field label="End"><Input type="time" value={f.end} onChange={set("end")} disabled={f.all_day} /></Field>
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" className="accent-[hsl(var(--violet))]" checked={f.all_day} onChange={set("all_day")} />All day</label>
            {item && <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" className="accent-[hsl(var(--violet))]" checked={f.done} onChange={set("done")} />Done</label>}
            <label className="ml-auto inline-flex items-center gap-2 text-xs text-muted-foreground">Priority
              <Select value={f.priority} onChange={set("priority")} className="h-8 w-28 text-xs"><option value="LOW">Low</option><option value="MEDIUM">Medium</option><option value="HIGH">High</option></Select>
            </label>
          </div>
          <Field label="Notes"><Textarea value={f.notes} onChange={set("notes")} maxLength={2000} className="min-h-[64px]" placeholder="Optional" /></Field>
          {err && <p className="text-xs text-critical">{err}</p>}
          <div className="flex items-center gap-2 border-t pt-3">
            {item && <Button type="button" variant="ghost" size="sm" className="text-critical" onClick={remove} loading={busy === "delete"}><Trash2 />Delete</Button>}
            <div className="ml-auto flex gap-2">
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" variant="accent" loading={busy === "save"}><CheckCircle2 />{item ? "Save" : "Add to calendar"}</Button>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
