"use client";

import { InputHTMLAttributes, forwardRef } from "react";
import clsx from "clsx";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> { label?: string; error?: string; }

export const Input = forwardRef<HTMLInputElement, InputProps>(({ label, error, className, ...props }, ref) => (
  <div>
    {label && <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">{label}</label>}
    <input ref={ref} className={clsx(
      "w-full h-11 px-4 text-sm bg-[#161b22] text-[#c9d1d9] border rounded-lg transition-colors duration-150",
      "placeholder:text-[#484f58] focus:outline-none",
      error ? "border-[#dc2626] focus:border-[#dc2626]" : "border-[#21262d] focus:border-[#58a6ff]",
      "disabled:opacity-30 disabled:cursor-not-allowed", className
    )} {...props} />
    {error && <p className="mt-1.5 text-xs text-[#dc2626]">{error}</p>}
  </div>
));
Input.displayName = "Input";
