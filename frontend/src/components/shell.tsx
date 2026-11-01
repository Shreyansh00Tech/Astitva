"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import {
  Activity, Bell, Bot, Building2, Check, ChevronsUpDown, ClipboardCheck, Database, FileClock, Gauge, KeyRound, LogOut,
  Menu, MessagesSquare, Monitor, Moon, Network, ScrollText, Search, Settings, ShieldAlert, Siren, Sun, TrendingUp, Users, X, Inbox,
} from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { primaryRole, ROLE_LABEL, useSession } from "@/lib/session";
import { emergencyBeep, primeBeep } from "@/lib/beep";
import { cn, relTime } from "@/lib/utils";
import { useChatEvents } from "@/lib/chat";
import { live, socketsEnabled } from "@/lib/realtime";
import { Wordmark } from "./logo";
import { Avatar, Skeleton } from "./ui/misc";
import { Dropdown, DropdownContent, DropdownItem, DropdownLabel, DropdownSeparator, DropdownTrigger } from "./ui/dropdown";
import * as Popover from "@radix-ui/react-popover";
import * as D from "@radix-ui/react-dialog";

type NavItem = { href: string; label: string; icon: any; perm?: string[]; badgeKey?: string };
const NAV: { section: string; items: NavItem[] }[] = [
  { section: "Workspace", items: [
    { href: "/", label: "Overview", icon: Gauge },
    { href: "/requests", label: "Access Requests", icon: Inbox, perm: ["requests:create"] },
    { href: "/approvals", label: "Approval Center", icon: ClipboardCheck, perm: ["approvals:read"] },
    { href: "/employees", label: "Employee Intelligence", icon: Users, perm: ["employees:read_team", "employees:read_all"] },
    { href: "/active-access", label: "Active Access", icon: KeyRound },
    { href: "/resources", label: "Resource Registry", icon: Database, perm: ["resources:read"] },
    { href: "/messages", label: "Messages", icon: MessagesSquare, perm: ["messages:use"], badgeKey: "messages" },
  ]},
  { section: "Security", items: [
    { href: "/ai-security", label: "AI Security Center", icon: Bot, perm: ["agents:read"] },
    { href: "/dependency-graph", label: "Dependency Graph", icon: Network, perm: ["graph:read"] },
    { href: "/drift", label: "Permission Drift", icon: TrendingUp, perm: ["drift:read"] },
    { href: "/emergency", label: "Emergency Access", icon: Siren, perm: ["emergency:request"] },
    { href: "/audit", label: "Audit & Compliance", icon: ScrollText, perm: ["audit:read", "alerts:read"] },
    { href: "/policies", label: "Policies", icon: FileClock, perm: ["policies:read"] },
  ]},
  { section: "Account", items: [
    { href: "/notifications", label: "Notifications", icon: Bell },
    { href: "/settings", label: "Settings", icon: Settings },
  ]},
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const { can } = useSession();
  const chat = can("messages:use");
  const { data: unread, mutate: refreshUnread } = useSWR(chat ? "/api/messages/unread" : null, fetcher, { refreshInterval: live(30000, 8000) });
  useChatEvents(() => refreshUnread(), chat);
  const badges: Record<string, number> = { messages: unread?.unread || 0 };
  return (
    <nav className="flex h-full flex-col">
      <div className="flex h-14 items-center px-4"><Wordmark /></div>
      <div className="flex-1 space-y-5 overflow-y-auto px-2.5 py-3 scroll-thin">
        {NAV.map((sec) => {
          const items = sec.items.filter((i) => !i.perm || i.perm.some(can));
          if (!items.length) return null;
          return (
            <div key={sec.section}>
              <div className="px-2 pb-1.5 text-2xs font-medium uppercase tracking-wider text-muted-foreground/80">{sec.section}</div>
              <div className="space-y-0.5">
                {items.map((i) => {
                  const active = i.href === "/" ? path === "/" : path.startsWith(i.href);
                  return (
                    <Link key={i.href} href={i.href} onClick={onNavigate}
                      className={cn("group relative flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] transition-colors",
                        active ? "bg-card font-medium text-foreground shadow-sm hairline" : "text-muted-foreground hover:bg-accent hover:text-foreground")}>
                      {active && <span className="absolute -left-2.5 h-4 w-0.5 rounded-r bg-violet" />}
                      <i.icon className={cn("h-4 w-4", active ? "text-violet" : "")} />
                      {i.label}
                      {i.badgeKey && badges[i.badgeKey] > 0 && (
                        <span className="ml-auto flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-violet px-1.5 text-[10px] font-semibold text-white tabular shadow-sm"
                          aria-label={`${badges[i.badgeKey]} unread`}>{badges[i.badgeKey] > 99 ? "99+" : badges[i.badgeKey]}</span>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <div className="m-2.5 rounded-lg border bg-card p-3 text-2xs text-muted-foreground">
        <div className="mb-1 flex items-center gap-1.5 font-medium text-foreground"><ShieldAlert className="h-3.5 w-3.5 text-violet" />Simulated environment</div>
        Fictional Nexora Technologies data. No real systems are connected.
      </div>
    </nav>
  );
}

function OrgSwitcher() {
  return (
    <Dropdown>
      <DropdownTrigger className="hidden items-center gap-2 rounded-md px-2 py-1 text-[13px] hover:bg-accent md:flex">
        <span className="flex h-5 w-5 items-center justify-center rounded bg-violet/15 text-[10px] font-bold text-violet">NX</span>
        <span className="font-medium">Nexora Technologies</span>
        <ChevronsUpDown className="h-3.5 w-3.5 text-muted-foreground" />
      </DropdownTrigger>
      <DropdownContent align="start" className="w-64">
        <DropdownLabel>Organizations</DropdownLabel>
        <DropdownItem><Building2 />Nexora Technologies<Check className="ml-auto !text-violet" /></DropdownItem>
        <DropdownItem disabled className="opacity-50"><Building2 />Nexora Labs (sandbox)<span className="ml-auto text-2xs">no access</span></DropdownItem>
        <DropdownSeparator />
        <div className="px-2 py-1.5 text-2xs text-muted-foreground">Single-tenant demo. Tenancy switching is shown for completeness.</div>
      </DropdownContent>
    </Dropdown>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const Icon = !mounted ? Monitor : theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;
  return (
    <Dropdown>
      <DropdownTrigger className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Theme"><Icon className="h-4 w-4" /></DropdownTrigger>
      <DropdownContent className="min-w-[140px]">
        {[["light", Sun, "Light"], ["dark", Moon, "Dark"], ["system", Monitor, "System"]].map(([v, I, l]: any) => (
          <DropdownItem key={v} onSelect={() => setTheme(v)}><I />{l}{theme === v && <Check className="ml-auto !text-violet" />}</DropdownItem>
        ))}
      </DropdownContent>
    </Dropdown>
  );
}

function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const router = useRouter();
  const { data, isLoading } = useSWR(q.length >= 2 ? `/api/search?q=${encodeURIComponent(q)}` : null, fetcher, { keepPreviousData: true });
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  const go = (href: string) => { setOpen(false); setQ(""); router.push(href); };
  const groups: [string, any[], (x: any) => [string, string, string]][] = data ? [
    ["Employees", data.employees, (e) => [e.name, `${e.employee_id} · ${e.department}`, `/employees/${e.id}`]],
    ["Resources", data.resources, (r) => [r.name, `${r.code} · ${r.sensitivity}`, `/resources/${r.id}`]],
    ["Requests", data.requests, (r) => [r.ref, `${r.resource} · ${r.status}`, `/requests/${r.id}`]],
  ] : [];
  return (
    <D.Root open={open} onOpenChange={setOpen}>
      <D.Trigger className="flex h-8 w-full max-w-sm items-center gap-2 rounded-md border bg-card px-2.5 text-[13px] text-muted-foreground shadow-sm hover:border-foreground/20">
        <Search className="h-3.5 w-3.5" /><span className="flex-1 text-left">Search employees, resources, requests…</span>
        <kbd className="hidden rounded border bg-muted px-1.5 font-mono text-[10px] sm:inline">⌘K</kbd>
      </D.Trigger>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px]" />
        <D.Content className="fixed left-1/2 top-[12vh] z-50 w-[calc(100vw-32px)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border bg-popover shadow-2xl animate-fade-in">
          <D.Title className="sr-only">Search</D.Title>
          <div className="flex items-center gap-2 border-b px-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type at least 2 characters…" className="h-11 flex-1 bg-transparent text-sm outline-none" />
          </div>
          <div className="max-h-[50vh] overflow-y-auto p-1.5 scroll-thin">
            {q.length < 2 && <p className="px-3 py-6 text-center text-xs text-muted-foreground">Results are scoped to what your role can see.</p>}
            {isLoading && <div className="space-y-1 p-2"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>}
            {groups.map(([title, rows, map]) => rows?.length ? (
              <div key={title} className="mb-1">
                <div className="px-2 py-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground">{title}</div>
                {rows.map((r: any) => { const [a, b, href] = map(r); return (
                  <button key={href} onClick={() => go(href)} className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-accent">
                    <span className="font-medium">{a}</span><span className="text-2xs text-muted-foreground">{b}</span>
                  </button>); })}
              </div>) : null)}
            {data && !groups.some(([, r]) => r?.length) && <p className="px-3 py-6 text-center text-xs text-muted-foreground">No matches.</p>}
          </div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

function NotificationBell() {
  const { data, mutate } = useSWR("/api/notifications?unread_only=false", fetcher, { refreshInterval: live(30000, 10000) });
  const { me } = useSession();
  const isSecurityManager = !!me?.roles?.includes("SECURITY_ADMIN");
  const beepRef = useRef(isSecurityManager);
  beepRef.current = isSecurityManager;
  const wsRef = useRef<WebSocket | null>(null);
  useEffect(() => (isSecurityManager ? primeBeep() : undefined), [isSecurityManager]);
  useEffect(() => {
    if (!socketsEnabled) return;
    let stop = false;
    let retry: any;
    const connect = () => {
      const base = process.env.NEXT_PUBLIC_WS_URL || `${location.protocol === "https:" ? "wss" : "ws"}://${location.hostname}:8000`;
      try {
        const ws = new WebSocket(`${base}/api/ws/notifications`);
        wsRef.current = ws;
        ws.onmessage = (ev) => {
          const m = JSON.parse(ev.data);
          if (m.type === "notification") {
            mutate();
            // Break-glass activated: one soft beep, Security Manager only.
            if (m.event === "alert:BREAKGLASS" && beepRef.current) emergencyBeep(m.id);
            (m.severity === "CRITICAL" ? toast.error : m.severity === "WARNING" ? toast.warning : toast.info)(m.title);
          }
        };
        ws.onclose = () => { if (!stop) retry = setTimeout(connect, 10000); };
      } catch { /* polling fallback continues */ }
    };
    connect();
    return () => { stop = true; clearTimeout(retry); wsRef.current?.close(); };
  }, [mutate]);
  // Polling only (e.g. on Vercel): announce notifications that arrived since the last poll, the same way
  // the WebSocket push does. The first load only records what is already there.
  const seenRef = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (socketsEnabled || !data?.items) return;
    const fresh = data.items.filter((n: any) => !n.read && seenRef.current && !seenRef.current.has(n.id));
    seenRef.current = new Set(data.items.map((n: any) => n.id));
    for (const n of fresh.reverse()) {
      if (n.kind === "SECURITY_ALERT" && /^BREAK-GLASS activated/.test(n.title) && beepRef.current) emergencyBeep(n.id);
      (n.severity === "CRITICAL" ? toast.error : n.severity === "WARNING" ? toast.warning : toast.info)(n.title);
    }
  }, [data]);
  const items = (data?.items || []).slice(0, 8);
  return (
    <Popover.Root>
      <Popover.Trigger className="relative rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Notifications">
        <Bell className="h-4 w-4" />
        {data?.unread > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-violet px-1 text-[9px] font-semibold text-white tabular">{data.unread > 99 ? "99+" : data.unread}</span>}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} className="z-50 w-[360px] rounded-xl border bg-popover shadow-2xl animate-fade-in">
          <div className="flex items-center justify-between border-b px-3 py-2.5">
            <span className="text-[13px] font-semibold">Notifications</span>
            <button className="text-2xs text-violet hover:underline" onClick={async () => { await api("/api/notifications/read-all", { method: "POST" }); mutate(); }}>Mark all read</button>
          </div>
          <div className="max-h-[380px] overflow-y-auto scroll-thin">
            {!items.length && <p className="p-6 text-center text-xs text-muted-foreground">You're all caught up.</p>}
            {items.map((n: any) => (
              <Link key={n.id} href={n.link || "/notifications"} onClick={() => !n.read && api(`/api/notifications/${n.id}/read`, { method: "POST" }).then(() => mutate())}
                className={cn("flex gap-2.5 border-b px-3 py-2.5 last:border-0 hover:bg-accent/60", !n.read && "bg-violet/[0.04]")}>
                <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", n.read ? "bg-transparent" : n.severity === "CRITICAL" ? "bg-critical" : n.severity === "WARNING" ? "bg-warning" : "bg-violet")} />
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium">{n.title}</div>
                  <div className="line-clamp-2 text-xs text-muted-foreground">{n.body}</div>
                  <div className="mt-0.5 text-2xs text-muted-foreground/80">{relTime(n.created_at)}</div>
                </div>
              </Link>
            ))}
          </div>
          <Link href="/notifications" className="block border-t px-3 py-2 text-center text-xs text-muted-foreground hover:text-foreground">View all</Link>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function ProfileMenu() {
  const { me } = useSession();
  const router = useRouter();
  const logout = async () => {
    try { await api("/api/auth/logout", { method: "POST" }); } catch { /* session may already be gone */ }
    router.replace("/login");
  };
  const role = primaryRole(me?.roles);
  return (
    <Dropdown>
      <DropdownTrigger className="flex items-center gap-2 rounded-md py-1 pl-1 pr-2 hover:bg-accent">
        <Avatar name={me?.name} />
        <div className="hidden text-left leading-tight lg:block">
          <div className="text-[13px] font-medium">{me?.name || "…"}</div>
          <div className="text-2xs text-muted-foreground">{ROLE_LABEL[role]}</div>
        </div>
      </DropdownTrigger>
      <DropdownContent className="w-64">
        <div className="px-2 py-2">
          <div className="text-[13px] font-medium">{me?.name}</div>
          <div className="text-xs text-muted-foreground">{me?.email}</div>
          <div className="mt-2 flex flex-wrap gap-1">
            {me?.roles.filter((r) => r !== "REQUESTER" || me.roles.length === 1).map((r) => (
              <span key={r} className="rounded bg-violet/10 px-1.5 py-0.5 text-2xs font-medium text-violet">{ROLE_LABEL[r]}</span>
            ))}
          </div>
        </div>
        <DropdownSeparator />
        <DropdownItem onSelect={() => router.push("/settings")}><Settings />Settings & security</DropdownItem>
        <DropdownItem onSelect={() => router.push("/active-access")}><KeyRound />My access</DropdownItem>
        <DropdownSeparator />
        <DropdownItem onSelect={logout} className="text-critical"><LogOut className="!text-critical" />Sign out</DropdownItem>
      </DropdownContent>
    </Dropdown>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, loading } = useSession();
  const [mobileOpen, setMobileOpen] = useState(false);
  const role = primaryRole(me?.roles);
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 border-r bg-sidebar lg:block"><Sidebar /></aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-[260px] border-r bg-sidebar shadow-xl animate-fade-in">
            <button className="absolute right-2 top-3 rounded-md p-1.5 hover:bg-accent" onClick={() => setMobileOpen(false)} aria-label="Close menu"><X className="h-4 w-4" /></button>
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur-md">
          <button className="rounded-md p-2 hover:bg-accent lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu className="h-4 w-4" /></button>
          <OrgSwitcher />
          <div className="mx-2 hidden h-5 w-px bg-border md:block" />
          <div className="flex flex-1 justify-center md:justify-start"><GlobalSearch /></div>
          <div className="flex items-center gap-1">
            {me && <span className="mr-1 hidden items-center gap-1.5 rounded-full border px-2 py-0.5 text-2xs font-medium sm:inline-flex">
              <Activity className="h-3 w-3 text-violet" />{ROLE_LABEL[role]}</span>}
            <ThemeToggle />
            <NotificationBell />
            <ProfileMenu />
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {loading && !me ? <div className="space-y-3"><Skeleton className="h-8 w-60" /><Skeleton className="h-28 w-full" /><Skeleton className="h-64 w-full" /></div> : children}
        </main>
      </div>
    </div>
  );
}
