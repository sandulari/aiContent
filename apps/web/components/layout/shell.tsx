"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Sidebar } from "./sidebar";
import { getToken, removeToken } from "@/lib/auth";
import { api } from "@/lib/api";

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);
  const [isAuthed, setIsAuthed] = useState(false);
  const authVerified = useRef(false);

  const isPublicPage = pathname === "/" || pathname.startsWith("/auth") || pathname.startsWith("/onboarding");
  const isEditorPage = pathname.startsWith("/editor");

  useEffect(() => {
    if (isPublicPage) {
      setAuthChecked(true);
      return;
    }

    const token = getToken();
    if (!token) {
      router.replace("/auth/login");
      setAuthChecked(true);
      return;
    }

    // Only verify the token ONCE — not on every navigation
    if (authVerified.current) {
      setIsAuthed(true);
      setAuthChecked(true);
      return;
    }

    api.auth.me()
      .then(() => {
        authVerified.current = true;
        setIsAuthed(true);
        setAuthChecked(true);
      })
      .catch(() => {
        removeToken();
        router.replace("/auth/login");
        setAuthChecked(true);
      });
  }, [pathname, isPublicPage, router]);

  // Still checking auth — show nothing (prevents flash of broken content)
  if (!authChecked) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0d1117]">
        <div className="w-5 h-5 border-2 border-[#58a6ff] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Public pages — no sidebar
  if (isPublicPage || isEditorPage) {
    return <>{children}</>;
  }

  // Not authenticated — don't render anything (redirect is happening)
  if (!isAuthed) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0d1117]">
        <div className="w-5 h-5 border-2 border-[#58a6ff] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Authenticated — show sidebar + content
  return (
    <div className="flex h-screen bg-[#0d1117]">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
