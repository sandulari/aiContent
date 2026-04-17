"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault(); setError(""); setLoading(true);
    try {
      const reg = await api.auth.register({ email, display_name: name, password });
      setToken(reg.access_token);
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex">
      <div className="hidden lg:flex lg:w-[48%] items-center justify-center p-16 relative overflow-hidden">
        <div className="absolute inset-0 opacity-[0.03]" style={{backgroundImage: "url(\"data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E\")"}} />
        <div className="relative max-w-md">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-[#16a34a] to-[#4ade80] flex items-center justify-center mb-10 shadow-lg shadow-green-900/30">
            <span className="text-lg font-black text-white">SP</span>
          </div>
          <h1 className="text-[10px] text-[#4ade80] font-bold uppercase tracking-[0.3em] mb-4">Shadow Pages</h1>
          <h2 className="text-4xl font-bold text-[#e0e0e0] leading-tight mb-4">
            Start creating viral content in minutes
          </h2>
          <p className="text-[15px] text-[#555] leading-relaxed mb-8">
            Connect your Instagram, and our AI engine finds the perfect viral content for your brand. No manual searching. No guesswork. Just results.
          </p>
          <div className="flex items-center gap-6 text-[11px] text-[#444] uppercase tracking-wider">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-[#4ade80]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              2 min setup
            </div>
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-[#4ade80]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              Exclusive access
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-[400px]">
          <div className="lg:hidden mb-10 text-center">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#16a34a] to-[#4ade80] flex items-center justify-center mx-auto mb-3">
              <span className="text-sm font-black text-white">SP</span>
            </div>
            <p className="text-[9px] text-[#4ade80] font-bold uppercase tracking-[0.3em]">Shadow Pages</p>
          </div>

          <div className="mb-8">
            <h2 className="text-2xl font-bold text-[#e0e0e0] mb-1">Create your account</h2>
            <p className="text-sm text-[#444]">Get exclusive access to the content engine</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">Your Name</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} required autoFocus placeholder="Full name"
                className="w-full h-12 px-4 text-[15px] bg-[#0e0e0e] text-[#ddd] border border-[#1a1a1a] rounded-xl focus:outline-none focus:border-[#4ade80]/30 focus:shadow-[0_0_0_3px_rgba(74,222,128,0.06)] placeholder:text-[#2a2a2a] transition-all" />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@example.com"
                className="w-full h-12 px-4 text-[15px] bg-[#0e0e0e] text-[#ddd] border border-[#1a1a1a] rounded-xl focus:outline-none focus:border-[#4ade80]/30 focus:shadow-[0_0_0_3px_rgba(74,222,128,0.06)] placeholder:text-[#2a2a2a] transition-all" />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="8+ characters"
                className="w-full h-12 px-4 text-[15px] bg-[#0e0e0e] text-[#ddd] border border-[#1a1a1a] rounded-xl focus:outline-none focus:border-[#4ade80]/30 focus:shadow-[0_0_0_3px_rgba(74,222,128,0.06)] placeholder:text-[#2a2a2a] transition-all" />
            </div>

            {error && (
              <div className="p-3 rounded-xl bg-[#dc2626]/5 border border-[#dc2626]/10">
                <p className="text-sm text-[#f87171]">{error}</p>
              </div>
            )}

            <button type="submit" disabled={loading}
              className="w-full h-12 rounded-xl text-[12px] font-bold uppercase tracking-[0.15em] text-white bg-gradient-to-r from-[#16a34a] to-[#22c55e] hover:from-[#15803d] hover:to-[#16a34a] disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-green-900/20 flex items-center justify-center gap-2">
              {loading && <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              {loading ? "Creating..." : "Get Started"}
            </button>
          </form>

          <p className="mt-6 text-center text-xs text-[#333]">
            Already have an account?{" "}
            <Link href="/auth/login" className="text-[#4ade80] hover:text-[#86efac] font-medium">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
