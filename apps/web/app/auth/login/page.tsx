"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault(); setError(""); setLoading(true);
    try {
      await api.auth.login({ email, password });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Invalid credentials");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen bg-[#010409] flex">
      {/* Left — branding */}
      <div className="hidden lg:flex lg:w-[48%] items-center justify-center p-16 relative overflow-hidden">
        {/* Animated gradient background */}
        <div className="absolute inset-0 bg-gradient-to-br from-[#010409] via-[#0d1117] to-[#010409] animate-[fadeSlideIn_2s_ease-out]" />
        <div className="absolute inset-0 opacity-[0.04] bg-[radial-gradient(ellipse_at_top_left,_rgba(74,222,128,0.15),_transparent_50%),_radial-gradient(ellipse_at_bottom_right,_rgba(88,166,255,0.1),_transparent_50%)]" />
        {/* Subtle background texture */}
        <div className="absolute inset-0 opacity-[0.03]" style={{backgroundImage: "url(\"data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E\")"}} />
        <div className="relative max-w-md">
          <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-[#16a34a] to-[#4ade80] flex items-center justify-center mb-10 shadow-lg shadow-green-900/30 ring-1 ring-green-400/20">
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
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-[#16a34a] to-[#4ade80] flex items-center justify-center mx-auto mb-3 ring-1 ring-green-400/20">
              <span className="text-sm font-black text-white">SP</span>
            </div>
            <p className="text-[9px] text-[#4ade80] font-bold uppercase tracking-[0.3em]">Shadow Pages</p>
          </div>

          <div className="mb-8">
            <h2 className="text-2xl font-bold text-[#e0e0e0] mb-1">Welcome back</h2>
            <p className="text-sm text-[#444]">Sign in to access your content engine</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus
                placeholder="you@example.com"
                className="w-full h-12 px-4 text-[15px] bg-[#0e0e0e] text-[#ddd] border border-[#1a1a1a] rounded-xl focus:outline-none focus:border-[#4ade80]/30 focus:shadow-[0_0_0_3px_rgba(74,222,128,0.06)] placeholder:text-[#2a2a2a] transition-all shadow-inner shadow-black/20" />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                placeholder="Enter your password"
                className="w-full h-12 px-4 text-[15px] bg-[#0e0e0e] text-[#ddd] border border-[#1a1a1a] rounded-xl focus:outline-none focus:border-[#4ade80]/30 focus:shadow-[0_0_0_3px_rgba(74,222,128,0.06)] placeholder:text-[#2a2a2a] transition-all shadow-inner shadow-black/20" />
            </div>

            <div className="flex justify-end -mt-1">
              <Link href="/auth/forgot-password" className="text-sm text-[#4ade80] hover:underline">
                Forgot your password?
              </Link>
            </div>

            {error && (
              <div className="p-3 rounded-xl bg-[#dc2626]/5 border border-[#dc2626]/10">
                <p className="text-sm text-[#f87171]">{error}</p>
              </div>
            )}

            <button type="submit" disabled={loading}
              className="w-full h-12 rounded-xl text-[12px] font-bold uppercase tracking-[0.15em] text-white bg-gradient-to-r from-[#238636] via-[#2ea043] to-[#238636] hover:from-[#2ea043] hover:via-[#3fb950] hover:to-[#2ea043] disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200 shadow-lg shadow-green-900/20 hover:shadow-green-800/30 flex items-center justify-center gap-2">
              {loading && <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              {loading ? "Signing in..." : "Sign In"}
            </button>
          </form>

          <p className="mt-6 text-center text-xs text-[#333]">
            Don't have an account?{" "}
            <Link href="/auth/register" className="text-[#4ade80] hover:text-[#86efac] font-medium">Create one</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
