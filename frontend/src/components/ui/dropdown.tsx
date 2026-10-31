"use client";
import * as M from "@radix-ui/react-dropdown-menu";
import { cn } from "@/lib/utils";

export const Dropdown = M.Root;
export const DropdownTrigger = M.Trigger;
export function DropdownContent({ className, align = "end", ...p }: M.DropdownMenuContentProps) {
  return (
    <M.Portal>
      <M.Content align={align} sideOffset={6} className={cn(
        "z-50 min-w-[200px] rounded-lg border bg-popover p-1 shadow-xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95", className)} {...p} />
    </M.Portal>
  );
}
export function DropdownItem({ className, ...p }: M.DropdownMenuItemProps) {
  return <M.Item className={cn("flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 text-[13px] outline-none data-[highlighted]:bg-accent [&_svg]:size-4 [&_svg]:text-muted-foreground", className)} {...p} />;
}
export const DropdownSeparator = () => <M.Separator className="my-1 h-px bg-border" />;
export const DropdownLabel = ({ className, ...p }: M.DropdownMenuLabelProps) => <M.Label className={cn("px-2 py-1.5 text-2xs font-medium uppercase tracking-wider text-muted-foreground", className)} {...p} />;
