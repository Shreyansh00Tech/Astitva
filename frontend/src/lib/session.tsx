"use client";

import { createContext, useContext } from "react";
import useSWR from "swr";
import { fetcher } from "./api";

export type Me = {
  id: string; name: string; email: string; employee_id: string; designation: string; department: string;
  department_code: string; roles: string[]; permissions: string[]; mfa_enabled: boolean; session_id: string;
  manager: { name: string } | null;
};

type Ctx = { me?: Me; loading: boolean; can: (p: string) => boolean; refresh: () => void };
const SessionCtx = createContext<Ctx>({ loading: true, can: () => false, refresh: () => {} });

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const { data, isLoading, mutate } = useSWR<Me>("/api/auth/me", fetcher, { revalidateOnFocus: true });
  const can = (p: string) => !!data?.permissions?.includes(p);
  return <SessionCtx.Provider value={{ me: data, loading: isLoading, can, refresh: () => mutate() }}>{children}</SessionCtx.Provider>;
}

export const useSession = () => useContext(SessionCtx);

export const ROLE_LABEL: Record<string, string> = {
  SECURITY_ADMIN: "Security Manager", MANAGER: "Manager", RISK_REVIEWER: "Risk Reviewer",
  RESOURCE_OWNER: "Resource Owner", REQUESTER: "Employee",
};

export function primaryRole(roles: string[] = []) {
  for (const r of ["SECURITY_ADMIN", "RISK_REVIEWER", "RESOURCE_OWNER", "MANAGER", "REQUESTER"]) if (roles.includes(r)) return r;
  return "REQUESTER";
}
