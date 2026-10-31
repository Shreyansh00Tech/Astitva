"use client";
import * as T from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = T.Root;
export const TabsContent = (p: T.TabsContentProps) => <T.Content {...p} className={cn("mt-4 focus-visible:outline-none animate-fade-in", p.className)} />;
export function TabsList({ className, ...p }: T.TabsListProps) {
  return <T.List className={cn("inline-flex h-8 items-center gap-0.5 rounded-md bg-secondary p-0.5", className)} {...p} />;
}
export function TabsTrigger({ className, ...p }: T.TabsTriggerProps) {
  return <T.Trigger className={cn(
    "inline-flex h-7 items-center gap-1.5 rounded-[6px] px-2.5 text-xs font-medium text-muted-foreground transition-all data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm hover:text-foreground",
    className)} {...p} />;
}
