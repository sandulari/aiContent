"use client";

import { useEffect, useState } from "react";
import { LEGAL_URLS } from "./legalLinks";

/**
 * Cookie notice.
 *
 * The content engine sets only strictly necessary cookies (the httpOnly
 * auth/refresh tokens and the CSRF token, see services/api/middleware) and
 * loads no analytics, pixel or advertising script; nginx's CSP
 * (default-src 'self') blocks third-party scripts outright. So there is
 * nothing to opt into: this bar informs, links the Cookie Policy and is
 * dismissed once.
 *
 * If a tracker is ever added, it MUST NOT load until the visitor accepts,
 * and this notice must become an accept / reject banner first.
 */
const STORAGE_KEY = "sp_cookie_notice_v1";

export function CookieNotice() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(STORAGE_KEY) !== "dismissed") setShow(true);
    } catch {
      setShow(true);
    }
  }, []);

  if (!show) return null;

  function dismiss() {
    try {
      window.localStorage.setItem(STORAGE_KEY, "dismissed");
    } catch {
      /* storage blocked: hide for this page view only */
    }
    setShow(false);
  }

  return (
    <div
      role="region"
      aria-label="Cookie notice"
      className="fixed inset-x-0 bottom-0 z-50 border-t border-[#21262d] bg-[#0d1117]"
    >
      <div className="mx-auto flex max-w-5xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p className="text-[12px] leading-relaxed text-[#7d8590]">
          We use only essential cookies to keep you signed in and protect your session. No
          analytics or advertising cookies.{" "}
          <a
            href={LEGAL_URLS.cookies}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#4ade80] hover:text-[#86efac]"
          >
            Cookie Policy
          </a>
        </p>
        <button
          type="button"
          onClick={dismiss}
          className="h-9 shrink-0 rounded-lg bg-[#238636] px-5 text-[11px] font-bold uppercase tracking-[0.15em] text-white transition-colors duration-150 hover:bg-[#2ea043]"
        >
          Got it
        </button>
      </div>
    </div>
  );
}
