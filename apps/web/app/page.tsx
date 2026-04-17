"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    // Try to verify auth via cookie — if it works, go to dashboard.
    // If not, go to login.
    api.auth.me()
      .then(() => router.replace("/dashboard"))
      .catch(() => router.replace("/auth/login"));
  }, [router]);

  return (
    <div className="flex h-screen items-center justify-center bg-[#0d1117]">
      <div className="w-5 h-5 border-2 border-[#58a6ff] border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
