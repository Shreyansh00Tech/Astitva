import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs font-medium leading-none whitespace-nowrap [&_svg]:size-3",
  {
    variants: {
      tone: {
        neutral: "bg-secondary text-secondary-foreground border-transparent",
        outline: "bg-transparent text-muted-foreground",
        violet: "bg-violet/10 text-violet border-violet/20",
        info: "bg-info/10 text-info border-info/20",
        success: "bg-success/10 text-success border-success/20",
        warning: "bg-warning/10 text-warning border-warning/25",
        serious: "bg-serious/10 text-serious border-serious/25",
        critical: "bg-critical/10 text-critical border-critical/25",
        solidCritical: "bg-critical text-white border-transparent",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type Tone = NonNullable<VariantProps<typeof badgeVariants>["tone"]>;
export function Badge({ className, tone, ...p }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...p} />;
}
