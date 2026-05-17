"use client";

import { InputHTMLAttributes, useState, forwardRef } from "react";
import clsx from "clsx";

/**
 * Password input with a show/hide eye toggle.
 *
 * Drop-in replacement for a raw ``<input type="password" />`` in the auth
 * forms. The toggle is keyboard-accessible (``type="button"`` so it doesn't
 * submit the form) and announces state via ``aria-label``/``aria-pressed``.
 *
 * Styling matches the auth-page password fields verbatim (h-12, 15px) so
 * a substitution is visually invisible aside from the trailing icon.
 */
type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export const PasswordField = forwardRef<HTMLInputElement, Props>(
  function PasswordField({ className, ...props }, ref) {
    const [visible, setVisible] = useState(false);
    return (
      <div className="relative">
        <input
          ref={ref}
          type={visible ? "text" : "password"}
          className={clsx(
            "w-full h-12 pl-4 pr-11 text-[15px] bg-[#161b22] text-[#c9d1d9]",
            "border border-[#21262d] rounded-lg",
            "focus:outline-none focus:border-[#58a6ff]",
            "placeholder:text-[#484f58] transition-colors duration-150",
            className,
          )}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          tabIndex={0}
          className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-[#484f58] hover:text-[#c9d1d9] focus:outline-none focus:text-[#c9d1d9] transition-colors"
        >
          {visible ? <EyeOff /> : <Eye />}
        </button>
      </div>
    );
  },
);

function Eye() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOff() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M17.94 17.94A10.06 10.06 0 0 1 12 19c-7 0-10-7-10-7a18.4 18.4 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 7 10 7a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="2" y1="2" x2="22" y2="22" />
    </svg>
  );
}
