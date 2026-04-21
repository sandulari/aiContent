"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault(); setError(""); setSuccess(""); setLoading(true);
    try {
      await api.auth.forgotPassword(email);
      setSuccess("Check your email for a reset link");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen bg-[#0d1117] flex">
      {/* Left — branding */}
      <div className="hidden lg:flex lg:w-[48%] items-center justify-center p-16 relative overflow-hidden">
        <div className="absolute inset-0 bg-[#0d1117]" />
        <div className="relative max-w-md">
          <div className="w-12 h-12 rounded-lg bg-gradient-to-br from-[#16a34a] to-[#4ade80] flex items-center justify-center mb-10">
            <span className="text-lg font-black text-white">SP</span>
          </div>
          <h1 className="text-[10px] text-[#4ade80] font-bold uppercase tracking-[0.3em] mb-4">Shadow Pages</h1>
          <h2 className="text-4xl font-bold text-[#e0e0e0] leading-tight mb-4">
            Content Engine
          </h2>
          <p className="text-[15px] text-[#555] leading-relaxed mb-10">
            Your exclusive AI-powered tool that finds viral reels matched to your brand, downloads them from alternative sources, and creates ready-to-post content in seconds.
          </p>
          <div className="space-y-3">
            {[
              "AI finds viral content for YOUR specific page",
              "Download without Instagram fingerprint",
              "One-click branded reel creation",
            ].map((t, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="w-5 h-5 rounded-full bg-[#4ade80]/10 flex items-center justify-center flex-shrink-0">
                  <svg className="w-3 h-3 text-[#4ade80]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                </div>
                <span className="text-[13px] text-[#666]">{t}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right — form */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-[400px]">
          <div className="lg:hidden mb-10 text-center">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#16a34a] to-[#4ade80] flex items-center justify-center mx-auto mb-3">
              <span className="text-sm font-black text-white">SP</span>
            </div>
            <p className="text-[9px] text-[#4ade80] font-bold uppercase tracking-[0.3em]">Shadow Pages</p>
          </div>

          <div className="mb-8">
            <h2 className="text-2xl font-bold text-[#e0e0e0] mb-1">Forgot your password?</h2>
            <p className="text-sm text-[#444]">Enter your email and we'll send you a reset link</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus
                placeholder="you@example.com"
                className="w-full h-12 px-4 text-[15px] bg-[#161b22] text-[#c9d1d9] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff] placeholder:text-[#484f58] transition-colors duration-150" />
            </div>

            {error && (
              <div className="p-3 rounded-lg bg-[#dc2626]/5 border border-[#dc2626]/10">
                <p className="text-sm text-[#f87171]">{error}</p>
              </div>
            )}

            {success && (
              <div className="p-3 rounded-lg bg-[#16a34a]/5 border border-[#16a34a]/10">
                <p className="text-sm text-[#4ade80]">{success}</p>
              </div>
            )}

            <button type="submit" disabled={loading}
              className="w-full h-12 rounded-lg text-[12px] font-bold uppercase tracking-[0.15em] text-white bg-[#238636] hover:bg-[#2ea043] disabled:opacity-40 disabled:cursor-not-allowed transition-colors duration-150 flex items-center justify-center gap-2">
              {loading && <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              {loading ? "Sending..." : "Send Reset Link"}
            </button>
          </form>

          <p className="mt-6 text-center text-xs text-[#333]">
            <Link href="/auth/login" className="text-[#4ade80] hover:text-[#86efac] font-medium">Back to Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
