"use client";

import { InputHTMLAttributes, forwardRef } from "react";
import clsx from "clsx";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> { label?: string; error?: string; }

export const Input = forwardRef<HTMLInputElement, InputProps>(({ label, error, className, ...props }, ref) => (
  <div>
    {label && <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">{label}</label>}
    <input ref={ref} className={clsx(
      "w-full h-11 px-4 text-sm bg-[#0e0e0e] text-[#ddd] border rounded-xl transition-all duration-200",
      "placeholder:text-[#333] focus:outline-none",
      error ? "border-[#dc2626] focus:border-[#dc2626]" : "border-[#1a1a1a] focus:border-[#4ade80]/40 focus:shadow-[0_0_0_3px_rgba(74,222,128,0.06)]",
      "disabled:opacity-30 disabled:cursor-not-allowed", className
    )} {...props} />
    {error && <p className="mt-1.5 text-xs text-[#dc2626]">{error}</p>}
  </div>
));
Input.displayName = "Input";
