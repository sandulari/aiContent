"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

const steps = [
  "Connecting to Instagram...",
  "Scanning your profile...",
  "Analyzing your content style...",
  "Detecting your niche...",
  "Finding viral reels for you...",
  "Building your personalized feed...",
  "Almost ready...",
];

export default function OnboardingPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [phase, setPhase] = useState<"input" | "analyzing" | "done" | "error">("input");
  const [stepIndex, setStepIndex] = useState(0);
  const [error, setError] = useState("");

  // Animate through steps while analyzing
  useEffect(() => {
    if (phase !== "analyzing") return;
    const timer = setInterval(() => {
      setStepIndex((prev) => Math.min(prev + 1, steps.length - 1));
    }, 2500);
    return () => clearInterval(timer);
  }, [phase]);

  const handleConnect = async () => {
    const clean = username.trim().replace("@", "").replace("https://www.instagram.com/", "").replace("/", "");
    if (!clean) return;

    setPhase("analyzing");
    setStepIndex(0);
    setError("");

    try {
      await api.myPages.add(clean);
      // Small extra delay so the animation feels complete
      await new Promise((r) => setTimeout(r, 2000));
      setPhase("done");
      setTimeout(() => router.push("/dashboard"), 1500);
    } catch (err: any) {
      if (err?.message?.includes("already")) {
        // Page already connected — just go to dashboard
        setPhase("done");
        setTimeout(() => router.push("/dashboard"), 1000);
      } else {
        setPhase("error");
        setError(err?.message || "Something went wrong. Please try again.");
      }
    }
  };

  return (
    <div className="min-h-screen bg-[#0d1117] flex items-center justify-center">
      <div className="w-full max-w-md px-6">
        {/* Logo */}
        <div className="text-center mb-10">
          <div className="w-16 h-16 rounded-lg bg-gradient-to-br from-[#16a34a] to-[#4ade80] flex items-center justify-center mx-auto mb-4">
            <span className="text-xl font-black text-white">SP</span>
          </div>
        </div>

        {/* Input phase */}
        {phase === "input" && (
          <div className="space-y-6">
            <div className="text-center">
              <h1 className="text-2xl font-bold text-[#e6edf3] mb-2">Connect Your Instagram</h1>
              <p className="text-sm text-[#7d8590]">Enter your Instagram username and we'll find the best viral reels for your page</p>
            </div>

            <div className="bg-[#161b22] border border-[#21262d] rounded-lg p-6 space-y-4">
              <div>
                <label className="block text-xs text-[#7d8590] mb-1.5">Instagram Username</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[#484f58] text-sm">@</span>
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleConnect()}
                    placeholder="yourusername"
                    className="w-full h-11 pl-8 pr-3 text-sm bg-[#0d1117] text-[#e6edf3] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff] placeholder:text-[#484f58]"
                    autoFocus
                  />
                </div>
              </div>

              <Button size="lg" className="w-full" onClick={handleConnect}>
                Connect & Analyze My Page
              </Button>
            </div>

            <p className="text-center text-[10px] text-[#484f58]">
              We only read public data from your profile. We never post or modify anything.
            </p>
          </div>
        )}

        {/* Analyzing phase */}
        {phase === "analyzing" && (
          <div className="text-center space-y-8">
            <div>
              <h1 className="text-xl font-bold text-[#e6edf3] mb-2">Analyzing @{username.replace("@", "")}</h1>
              <p className="text-sm text-[#7d8590]">This takes about 15 seconds</p>
            </div>

            {/* Progress */}
            <div className="space-y-4">
              <div className="w-full h-1 bg-[#21262d] rounded-full overflow-hidden">
                <div
                  className="h-full bg-[#58a6ff] rounded-full transition-all duration-1000 ease-out"
                  style={{ width: `${Math.min(((stepIndex + 1) / steps.length) * 100, 95)}%` }}
                />
              </div>

              <div className="space-y-2">
                {steps.map((step, i) => (
                  <div
                    key={i}
                    className={`flex items-center gap-2 text-sm transition-all duration-300 ${
                      i < stepIndex ? "text-[#3fb950]" : i === stepIndex ? "text-[#e6edf3]" : "text-[#21262d]"
                    }`}
                  >
                    {i < stepIndex ? (
                      <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                    ) : i === stepIndex ? (
                      <div className="w-4 h-4 flex-shrink-0 border-2 border-[#58a6ff] border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <div className="w-4 h-4 flex-shrink-0 rounded-full border border-[#21262d]" />
                    )}
                    {step}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Done phase */}
        {phase === "done" && (
          <div className="text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-[#0f2e16] flex items-center justify-center mx-auto">
              <svg className="w-8 h-8 text-[#3fb950]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
            </div>
            <h1 className="text-xl font-bold text-[#e6edf3]">You're all set!</h1>
            <p className="text-sm text-[#7d8590]">Your personalized feed is ready. Redirecting...</p>
          </div>
        )}

        {/* Error phase */}
        {phase === "error" && (
          <div className="text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-[#3c1418] flex items-center justify-center mx-auto">
              <svg className="w-8 h-8 text-[#f85149]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
            </div>
            <h1 className="text-xl font-bold text-[#e6edf3]">Something went wrong</h1>
            <p className="text-sm text-[#f85149]">{error}</p>
            <Button variant="secondary" onClick={() => setPhase("input")}>Try Again</Button>
          </div>
        )}
      </div>
    </div>
  );
}
