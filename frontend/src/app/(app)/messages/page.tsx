"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { ArrowLeft, CheckCheck, Lock, MessagesSquare, Search, SendHorizontal, Users } from "lucide-react";
import { api, errorMessage, fetcher } from "@/lib/api";
import { useChatEvents } from "@/lib/chat";
import { live } from "@/lib/realtime";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { Avatar, EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";

type Contact = {
  id: string; name: string; email: string; designation: string | null; department: string | null; employee_id: string;
  is_manager: boolean; relation: string; conversation_id: string | null; unread: number;
  last_message: Msg | null;
};
type Msg = { id: string; conversation_id: string; sender_id: string; body: string; created_at: string; pending?: boolean };
type Thread = {
  id: string; contact: Contact | null; can_send: boolean; messages: Msg[]; has_more: boolean;
  my_last_read_at: string | null; their_last_read_at: string | null;
};

const time = (v: string) => new Date(v).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

function listTime(v?: string) {
  if (!v) return "";
  const d = new Date(v), now = new Date();
  if (d.toDateString() === now.toDateString()) return time(v);
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

function dayLabel(v: string) {
  const d = new Date(v), now = new Date();
  if (d.toDateString() === now.toDateString()) return "Today";
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
}

export default function Messages() {
  const { me, can } = useSession();
  const allowed = can("messages:use");
  const [q, setQ] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null); // contact (user) id
  const [convId, setConvId] = useState<string | null>(null);
  const contacts = useSWR<Contact[]>(allowed ? "/api/messages/contacts" : null, fetcher, { refreshInterval: live(20000, 8000) });
  const thread = useSWR<Thread>(allowed && convId ? `/api/messages/conversations/${convId}` : null, fetcher, { refreshInterval: live(15000, 3000) });

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    const rows = (contacts.data || []).filter((c) => !term || [c.name, c.designation, c.department, c.employee_id, c.email]
      .some((x) => x?.toLowerCase().includes(term)));
    return rows.sort((a, b) => (b.last_message?.created_at || "").localeCompare(a.last_message?.created_at || "") || a.name.localeCompare(b.name));
  }, [contacts.data, q]);
  const active = contacts.data?.find((c) => c.id === activeId) || null;
  const totalUnread = (contacts.data || []).reduce((n, c) => n + c.unread, 0);

  const markRead = async (cid: string) => {
    try { await api(`/api/messages/conversations/${cid}/read`, { method: "POST" }); contacts.mutate(); } catch { /* retried on next open */ }
  };

  const openContact = async (c: Contact) => {
    setActiveId(c.id);
    if (c.conversation_id) { setConvId(c.conversation_id); if (c.unread) markRead(c.conversation_id); return; }
    try {
      const r = await api<{ id: string }>("/api/messages/conversations", { json: { user_id: c.id } });
      setConvId(r.id);
      contacts.mutate();
    } catch (e) { toast.error(errorMessage(e)); }
  };

  useChatEvents((e) => {
    if (e.type === "chat") {
      contacts.mutate();
      if (e.message.conversation_id === convId) {
        thread.mutate((t) => t && !t.messages.some((m) => m.id === e.message.id)
          ? { ...t, messages: [...t.messages.filter((m) => !(m.pending && m.body === e.message.body && e.message.sender_id === me?.id)), e.message] }
          : t, { revalidate: false });
        if (e.message.sender_id !== me?.id && document.visibilityState === "visible") markRead(convId);
      } else if (e.message.sender_id !== me?.id) {
        toast(`New message from ${e.sender_name || "a colleague"}`, { description: e.message.body.slice(0, 80) });
      }
    } else if (e.type === "read" && e.conversation_id === convId) {
      thread.mutate();
    }
  }, allowed);

  if (me && !allowed) {
    return <div className="rounded-xl border bg-card"><ErrorState error={{ status: 403 }} /></div>;
  }

  return (
    <div className="flex h-[calc(100vh-7.5rem)] min-h-[480px] overflow-hidden rounded-xl border bg-card shadow-sm">
      {/* contacts */}
      <aside className={cn("flex w-full flex-col border-r md:w-[320px] md:shrink-0", activeId && "hidden md:flex")}>
        <div className="border-b px-4 pb-3 pt-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold tracking-tight">Messages</h1>
              {totalUnread > 0 && <span className="rounded-full bg-violet/15 px-1.5 py-0.5 text-2xs font-semibold text-violet tabular">{totalUnread} new</span>}
            </div>
            <span className="flex items-center gap-1 text-2xs text-muted-foreground"><Lock className="h-3 w-3" />Private</span>
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search people…" aria-label="Search people"
              className="h-8 w-full rounded-md border bg-background/60 pl-8 pr-2 text-[13px] outline-none placeholder:text-muted-foreground/70 focus:border-violet focus:ring-2 focus:ring-ring/30" />
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-1.5 scroll-thin">
          {contacts.error ? <ErrorState error={contacts.error} onRetry={() => contacts.mutate()} />
            : !contacts.data ? <div className="space-y-1.5 p-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}</div>
            : !filtered.length ? <EmptyState icon={Users} title={q ? "No one matches" : "No contacts yet"} description={q ? "Try a name, team or employee ID." : "Employees and managers appear here."} />
            : filtered.map((c) => (
              <button key={c.id} onClick={() => openContact(c)}
                className={cn("group flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left transition-colors",
                  activeId === c.id ? "bg-violet/10 ring-1 ring-violet/25" : "hover:bg-accent")}>
                <span className="relative">
                  <Avatar name={c.name} className="h-9 w-9 text-xs" />
                  {c.is_manager && <span className="absolute -bottom-0.5 -right-0.5 rounded-full border-2 border-card bg-violet px-1 text-[8px] font-bold leading-3 text-white">M</span>}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className={cn("truncate text-[13px]", c.unread ? "font-semibold text-foreground" : "font-medium")}>{c.name}</span>
                    <span className={cn("shrink-0 text-2xs tabular", c.unread ? "text-violet" : "text-muted-foreground")}>{listTime(c.last_message?.created_at)}</span>
                  </span>
                  <span className="flex items-center justify-between gap-2">
                    <span className={cn("truncate text-xs", c.unread ? "text-foreground/90" : "text-muted-foreground")}>
                      {c.last_message ? `${c.last_message.sender_id === me?.id ? "You: " : ""}${c.last_message.body}` : `${c.designation || "Colleague"} · ${c.relation}`}
                    </span>
                    {c.unread > 0 && <span className="flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full bg-violet px-1.5 text-[10px] font-semibold text-white tabular">{c.unread}</span>}
                  </span>
                </span>
              </button>
            ))}
        </div>
        <div className="border-t px-4 py-2.5 text-2xs text-muted-foreground">Employees and managers only. Chats are visible to their two members.</div>
      </aside>

      {/* conversation */}
      <section className={cn("min-w-0 flex-1 flex-col", activeId ? "flex" : "hidden md:flex")}>
        {!active ? (
          <div className="flex flex-1 flex-col items-center justify-center bg-gradient-to-b from-transparent to-violet/[0.03] p-8 text-center">
            <div className="mb-4 rounded-2xl border bg-background/60 p-4 shadow-sm"><MessagesSquare className="h-7 w-7 text-violet" /></div>
            <p className="text-sm font-medium">Select a conversation</p>
            <p className="mt-1 max-w-xs text-xs text-muted-foreground">Pick a colleague on the left to start a private chat. New messages arrive live.</p>
          </div>
        ) : (
          <Conversation key={active.id} contact={active} convId={convId} thread={thread} meId={me?.id}
            onBack={() => { setActiveId(null); setConvId(null); }} />
        )}
      </section>
    </div>
  );
}

function Conversation({ contact, convId, thread, meId, onBack }: {
  contact: Contact; convId: string | null; thread: ReturnType<typeof useSWR<Thread>>; meId?: string; onBack: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [older, setOlder] = useState<Msg[]>([]);
  const [moreOlder, setMoreOlder] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const data = thread.data && thread.data.id === convId ? thread.data : undefined;
  const messages = useMemo(() => {
    const seen = new Set<string>();
    return [...older, ...(data?.messages || [])].filter((m) => (seen.has(m.id) ? false : (seen.add(m.id), true)));
  }, [older, data?.messages]);
  const last = data?.messages[data.messages.length - 1]?.id;

  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [last, convId]);
  useEffect(() => { box.current?.focus(); }, [convId]);

  const loadOlder = async () => {
    const first = messages[0];
    if (!first || !convId) return;
    try {
      const r = await api<Thread>(`/api/messages/conversations/${convId}?before=${encodeURIComponent(first.created_at)}`);
      setOlder((o) => [...r.messages, ...o]);
      setMoreOlder(r.has_more);
    } catch (e) { toast.error(errorMessage(e)); }
  };

  const send = async () => {
    const body = draft.trim();
    if (!body || !convId || sending) return;
    setSending(true);
    setDraft("");
    const temp: Msg = { id: `tmp-${Date.now()}`, conversation_id: convId, sender_id: meId || "", body, created_at: new Date().toISOString(), pending: true };
    thread.mutate((t) => t && { ...t, messages: [...t.messages, temp] }, { revalidate: false });
    try {
      const m = await api<Msg>(`/api/messages/conversations/${convId}/messages`, { json: { body } });
      thread.mutate((t) => t && { ...t, messages: [...t.messages.filter((x) => x.id !== temp.id && x.id !== m.id), m] }, { revalidate: false });
    } catch (e) {
      thread.mutate((t) => t && { ...t, messages: t.messages.filter((x) => x.id !== temp.id) }, { revalidate: false });
      setDraft(body);
      toast.error(errorMessage(e));
    } finally { setSending(false); box.current?.focus(); }
  };

  const seenAt = data?.their_last_read_at;
  const lastMine = [...messages].reverse().find((m) => m.sender_id === meId && !m.pending);

  return (
    <>
      <header className="flex h-[62px] shrink-0 items-center gap-3 border-b px-4">
        <button onClick={onBack} className="-ml-1 rounded-md p-1.5 text-muted-foreground hover:bg-accent md:hidden" aria-label="Back"><ArrowLeft className="h-4 w-4" /></button>
        <Avatar name={contact.name} className="h-9 w-9 text-xs" />
        <div className="min-w-0 leading-tight">
          <div className="truncate text-sm font-semibold">{contact.name}</div>
          <div className="truncate text-xs text-muted-foreground">{[contact.designation, contact.department].filter(Boolean).join(" · ")}</div>
        </div>
        <span className="ml-auto hidden rounded-full border px-2 py-0.5 text-2xs font-medium text-muted-foreground sm:inline">{contact.is_manager ? "Manager" : contact.relation}</span>
      </header>

      <div className="flex-1 overflow-y-auto bg-gradient-to-b from-transparent to-violet/[0.025] px-4 py-4 scroll-thin">
        {!data ? (
          <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className={cn("h-10 w-2/5", i % 2 && "ml-auto")} />)}</div>
        ) : !messages.length ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Avatar name={contact.name} className="mb-3 h-12 w-12 text-sm" />
            <p className="text-sm font-medium">Say hello to {contact.name.split(" ")[0]}</p>
            <p className="mt-1 text-xs text-muted-foreground">This is the start of your private conversation.</p>
          </div>
        ) : (
          <div className="space-y-1">
            {data.has_more && moreOlder && (
              <div className="pb-2 text-center"><button onClick={loadOlder} className="rounded-full border px-3 py-1 text-2xs text-muted-foreground hover:bg-accent hover:text-foreground">Load earlier messages</button></div>
            )}
            {messages.map((m, i) => {
              const prev = messages[i - 1];
              const mine = m.sender_id === meId;
              const newDay = !prev || new Date(prev.created_at).toDateString() !== new Date(m.created_at).toDateString();
              const grouped = !newDay && prev && prev.sender_id === m.sender_id
                && new Date(m.created_at).getTime() - new Date(prev.created_at).getTime() < 5 * 60_000;
              return (
                <div key={m.id}>
                  {newDay && (
                    <div className="my-3 flex items-center gap-3 text-2xs font-medium text-muted-foreground">
                      <span className="h-px flex-1 bg-border" />{dayLabel(m.created_at)}<span className="h-px flex-1 bg-border" />
                    </div>
                  )}
                  <div className={cn("flex", mine ? "justify-end" : "justify-start", !grouped && "pt-1.5")}>
                    <div className={cn("group max-w-[78%] rounded-2xl px-3 py-2 text-[13px] leading-relaxed shadow-sm sm:max-w-[65%]",
                      mine ? "rounded-br-md bg-violet text-white" : "rounded-bl-md border bg-background/80 text-foreground",
                      m.pending && "opacity-60")}>
                      <p className="whitespace-pre-wrap break-words">{m.body}</p>
                      <div className={cn("mt-0.5 flex items-center justify-end gap-1 text-[10px] tabular", mine ? "text-white/70" : "text-muted-foreground")}>
                        {m.pending ? "Sending…" : time(m.created_at)}
                        {mine && lastMine?.id === m.id && seenAt && new Date(seenAt) >= new Date(m.created_at) && <CheckCheck className="h-3 w-3" aria-label="Seen" />}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <div ref={bottom} />
      </div>

      <footer className="shrink-0 border-t p-3">
        {data && !data.can_send ? (
          <p className="py-2 text-center text-xs text-muted-foreground">This person can no longer receive messages.</p>
        ) : (
          <div className="flex items-end gap-2 rounded-xl border bg-background/60 p-1.5 focus-within:border-violet focus-within:ring-2 focus-within:ring-ring/30">
            <textarea ref={box} value={draft} rows={1} maxLength={2000} placeholder={`Message ${contact.name.split(" ")[0]}…`} aria-label="Message"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}
              className="max-h-32 min-h-[34px] flex-1 resize-none bg-transparent px-2 py-1.5 text-[13px] outline-none placeholder:text-muted-foreground/70" />
            <button onClick={send} disabled={!draft.trim() || !convId || sending} aria-label="Send"
              className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-lg bg-violet text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-40">
              <SendHorizontal className="h-4 w-4" />
            </button>
          </div>
        )}
        <p className="mt-1.5 px-1 text-[10px] text-muted-foreground">Enter to send · Shift + Enter for a new line</p>
      </footer>
    </>
  );
}
