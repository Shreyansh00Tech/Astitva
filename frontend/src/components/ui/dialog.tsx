"use client";
import * as React from "react";
import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({ title, description, children, className, wide }: { title: string; description?: string; children: React.ReactNode; className?: string; wide?: boolean }) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <D.Content className={cn(
        "fixed left-1/2 top-1/2 z-50 w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-popover p-0 shadow-2xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[.98] max-h-[90vh] overflow-y-auto scroll-thin",
        wide ? "max-w-2xl" : "max-w-lg", className)}>
        <div className="flex items-start justify-between border-b px-5 py-4">
          <div>
            <D.Title className="text-sm font-semibold">{title}</D.Title>
            {description && <D.Description className="mt-0.5 text-xs text-muted-foreground">{description}</D.Description>}
          </div>
          <D.Close className="rounded-md p-1 text-muted-foreground hover:bg-accent"><X className="h-4 w-4" /></D.Close>
        </div>
        <div className="px-5 py-4">{children}</div>
      </D.Content>
    </D.Portal>
  );
}
