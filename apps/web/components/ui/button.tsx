"use client";

import { ButtonHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  children: ReactNode;
}

export function Button({ variant = "primary", size = "md", loading = false, disabled, className, children, ...props }: ButtonProps) {
  const base = "inline-flex items-center justify-center gap-1.5 font-semibold rounded-lg transition-colors duration-150 select-none uppercase tracking-wider";
  const variants = {
    primary: "bg-[#238636] hover:bg-[#2ea043] text-white active:bg-[#166534] disabled:opacity-40",
    secondary: "bg-[#21262d] text-[#c9d1d9] border border-[#30363d] hover:bg-[#30363d] hover:text-[#e6edf3] active:bg-[#161b22] disabled:opacity-40",
    danger: "bg-[#dc2626] text-white hover:bg-[#b91c1c] disabled:opacity-40",
    ghost: "bg-transparent text-[#7d8590] hover:text-[#e6edf3] hover:bg-[#161b22] active:bg-[#0d1117] disabled:opacity-40",
  };
  const sizes = {
    sm: "h-8 px-3 text-[10px]",
    md: "h-10 px-4 text-[11px]",
    lg: "h-12 px-6 text-xs",
  };

  return (
    <button disabled={disabled || loading} className={clsx(base, variants[variant], sizes[size], (disabled || loading) && "cursor-not-allowed", className)} {...props}>
      {loading && <div className="w-3.5 h-3.5 border-2 border-current/30 border-t-current rounded-full animate-spin" />}
      {children}
    </button>
  );
}
