import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-[13px] font-medium transition-[background,color,box-shadow,transform] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 active:translate-y-px [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm",
        accent: "bg-violet text-white hover:bg-violet/90 shadow-sm shadow-violet/20",
        outline: "border bg-card hover:bg-accent text-foreground",
        ghost: "hover:bg-accent text-foreground",
        subtle: "bg-secondary hover:bg-secondary/70 text-secondary-foreground",
        destructive: "bg-critical text-white hover:bg-critical/90 shadow-sm",
        success: "bg-success text-white hover:bg-success/90 shadow-sm",
        link: "text-violet underline-offset-4 hover:underline px-0 h-auto",
      },
      size: { default: "h-8 px-3", sm: "h-7 px-2.5 text-xs", lg: "h-10 px-4 text-sm", icon: "h-8 w-8" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} disabled={disabled || loading} {...props}>
        {asChild ? children : <>{loading && <Loader2 className="animate-spin" />}{children}</>}
      </Comp>
    );
  },
);
Button.displayName = "Button";
export { buttonVariants };
