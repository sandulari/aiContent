"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/auth";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    // If logged in, go to dashboard. If not, go to login.
    if (getToken()) {
      router.replace("/dashboard");
    } else {
      router.replace("/auth/login");
    }
  }, [router]);

  return (
    <div className="flex h-screen items-center justify-center bg-[#0d1117]">
      <div className="w-5 h-5 border-2 border-[#58a6ff] border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
