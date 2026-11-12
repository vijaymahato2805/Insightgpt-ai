import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonStyles = cva(
  "inline-flex items-center justify-center gap-2 rounded-xl text-sm font-semibold transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-primary text-white shadow-glow hover:bg-primary/90",
        secondary: "border border-border bg-white/[0.035] text-foreground hover:bg-white/[0.075]",
        ghost: "text-muted hover:bg-white/[0.06] hover:text-foreground",
      },
      size: { default: "h-11 px-4", icon: "size-10", small: "h-9 px-3 text-xs" },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonStyles>;
export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonStyles({ variant, size, className }))} {...props} />;
}

type InputProps = InputHTMLAttributes<HTMLInputElement>;
export function Input({ className, ...props }: InputProps) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-xl border border-border bg-black/20 px-3.5 text-sm text-foreground outline-none transition placeholder:text-muted/70 focus:border-primary/70 focus:ring-2 focus:ring-primary/15",
        className,
      )}
      {...props}
    />
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn("rounded-2xl border border-border bg-surface", className)}>{children}</section>;
}

export function StatusDot({ tone = "neutral" }: { tone?: "good" | "warn" | "neutral" }) {
  const color = tone === "good" ? "bg-emerald-400" : tone === "warn" ? "bg-amber-400" : "bg-slate-500";
  return <span className={cn("size-2 rounded-full", color)} aria-hidden="true" />;
}
