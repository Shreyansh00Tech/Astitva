"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { Bell, CheckCheck, Circle, CircleDot } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { cn, fmtDate, relTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SeverityBadge } from "@/components/status";

export default function Notifications() {
  const [filter, setFilter] = useState("all");
  const { data, error, isLoading, mutate } = useSWR(`/api/notifications${filter === "unread" ? "?unread_only=true" : ""}`, fetcher, { refreshInterval: 30000 });
  const mark = async (n: any, read: boolean) => {
    try { await api(`/api/notifications/${n.id}/${read ? "read" : "unread"}`, { method: "POST" }); mutate(); } catch (e) { toast.error(errorMessage(e)); }
  };
  const all = async () => { try { await api("/api/notifications/read-all", { method: "POST" }); mutate(); toast.success("All caught up"); } catch (e) { toast.error(errorMessage(e)); } };
  return (
    <>
      <PageHeader title="Notifications" description="Approvals, expiries, alerts and recertification reminders. Delivered live."
        actions={<Button variant="outline" onClick={all} disabled={!data?.unread}><CheckCheck />Mark all read</Button>} />
      <Tabs value={filter} onValueChange={setFilter} className="mb-3">
        <TabsList><TabsTrigger value="all">All</TabsTrigger><TabsTrigger value="unread">Unread{data?.unread ? ` (${data.unread})` : ""}</TabsTrigger></TabsList>
      </Tabs>
      <Card>
        {error ? <ErrorState error={error} onRetry={() => mutate()} /> : isLoading ? <LoadingRows /> : !data.items.length ? <EmptyState icon={Bell} title="Nothing here" description="You're all caught up." /> : (
          <ul className="divide-y">
            {data.items.map((n: any) => (
              <li key={n.id} className={cn("flex items-start gap-3 px-4 py-3", !n.read && "bg-violet/[0.03]")}>
                <button onClick={() => mark(n, !n.read)} aria-label={n.read ? "Mark unread" : "Mark read"} className="mt-0.5 text-muted-foreground hover:text-foreground">
                  {n.read ? <Circle className="h-4 w-4" /> : <CircleDot className="h-4 w-4 text-violet" />}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {n.link ? <Link href={n.link} onClick={() => !n.read && mark(n, true)} className={cn("text-sm hover:underline", !n.read && "font-medium")}>{n.title}</Link>
                      : <span className={cn("text-sm", !n.read && "font-medium")}>{n.title}</span>}
                    {n.severity && n.severity !== "INFO" && <SeverityBadge severity={n.severity} />}
                  </div>
                  {n.body && <p className="mt-0.5 text-xs text-muted-foreground">{n.body}</p>}
                </div>
                <span className="shrink-0 text-2xs text-muted-foreground" title={fmtDate(n.created_at)}>{relTime(n.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
