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
  const base = "inline-flex items-center justify-center gap-1.5 font-semibold rounded-lg transition-all duration-200 select-none uppercase tracking-wider";
  const variants = {
    primary: "bg-gradient-to-r from-[#238636] via-[#2ea043] to-[#238636] text-white hover:from-[#2ea043] hover:via-[#3fb950] hover:to-[#2ea043] active:from-[#166534] disabled:opacity-40 shadow-lg shadow-green-900/20 hover:shadow-green-800/30 transition-all duration-200",
    secondary: "bg-[#141414] text-[#999] border border-[#222] hover:bg-[#1a1a1a] hover:text-[#ccc] hover:border-[#333] active:bg-[#111] disabled:opacity-40 transition-all duration-200",
    danger: "bg-[#dc2626] text-white hover:bg-[#b91c1c] disabled:opacity-40 transition-all duration-200",
    ghost: "bg-transparent text-[#666] hover:text-[#ccc] hover:bg-[#141414] active:bg-[#111] disabled:opacity-40 transition-all duration-200",
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
