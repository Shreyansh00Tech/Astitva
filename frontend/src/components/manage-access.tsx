"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Check, MinusCircle, ShieldX } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";

/**
 * Remove granted access: drop individual permissions (grant is narrowed, a new token is issued)
 * or revoke everything (token invalidated). The backend decides who is allowed; this is only the UI.
 */
export function ManageAccessDialog({ grant, self, onClose, onDone }: {
  grant: { id: string; permissions: string[]; userName: string; resourceName: string };
  self?: boolean; onClose: () => void; onDone: () => void;
}) {
  const [remove, setRemove] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"" | "restrict" | "revoke">("");
  const keep = grant.permissions.filter((p) => !remove.includes(p));
  const canRestrict = remove.length > 0 && keep.length > 0 && reason.trim().length >= 3;

  const run = async (kind: "restrict" | "revoke") => {
    setBusy(kind);
    try {
      if (kind === "restrict") await api(`/api/grants/${grant.id}/restrict`, { json: { permissions: keep, reason } });
      else await api(`/api/grants/${grant.id}/revoke`, { json: { reason } });
      toast.success(kind === "restrict" ? `Removed ${remove.join(", ")}. New token issued with ${keep.join(", ")}.` : "Access revoked and token invalidated");
      onDone();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(""); }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={self ? "Remove my access" : "Remove access"} description={`${grant.userName} · ${grant.resourceName}`}>
        <div className="space-y-4">
          <Field label="Permissions" hint={grant.permissions.length > 1 ? "Click a permission to remove it. The rest stays active with a new token." : "Only one permission is left, so you can only revoke the whole access."}>
            <div className="flex flex-wrap gap-1.5">
              {grant.permissions.map((p) => {
                const off = remove.includes(p);
                return (
                  <button key={p} type="button" disabled={grant.permissions.length < 2}
                    onClick={() => setRemove(off ? remove.filter((x) => x !== p) : [...remove, p])}
                    className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-1 font-mono text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-70",
                      off ? "border-critical/50 bg-critical/10 text-critical line-through" : "border-success/40 bg-success/10 text-success hover:bg-success/15")}>
                    {off ? <MinusCircle className="h-3 w-3" /> : <Check className="h-3 w-3" />}{p}
                  </button>
                );
              })}
            </div>
          </Field>
          <Field label="Reason (recorded in the audit trail and sent to the employee)">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={self ? "e.g. Work finished" : "e.g. Write access no longer needed"} />
          </Field>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" onClick={() => run("restrict")} loading={busy === "restrict"} disabled={!canRestrict || !!busy}>
              <MinusCircle />Remove selected{remove.length ? ` (${remove.length})` : ""}
            </Button>
            <Button variant="destructive" onClick={() => run("revoke")} loading={busy === "revoke"} disabled={reason.trim().length < 3 || !!busy}>
              <ShieldX />Revoke all access
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
