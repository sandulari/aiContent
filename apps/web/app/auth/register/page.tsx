"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";

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
      await api.auth.register({ email, display_name: name, password });
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen bg-[#0d1117] flex">
      <div className="hidden lg:flex lg:w-[48%] items-center justify-center p-16 relative overflow-hidden">
        <div className="absolute inset-0 bg-[#0d1117]" />
        <div className="relative max-w-md">
          <div className="w-14 h-14 rounded-lg bg-gradient-to-br from-[#16a34a] to-[#4ade80] flex items-center justify-center mb-10">
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
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-[#16a34a] to-[#4ade80] flex items-center justify-center mx-auto mb-3">
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
                className="w-full h-12 px-4 text-[15px] bg-[#161b22] text-[#c9d1d9] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff] placeholder:text-[#484f58] transition-colors duration-150" />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@example.com"
                className="w-full h-12 px-4 text-[15px] bg-[#161b22] text-[#c9d1d9] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff] placeholder:text-[#484f58] transition-colors duration-150" />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="8+ characters"
                className="w-full h-12 px-4 text-[15px] bg-[#161b22] text-[#c9d1d9] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff] placeholder:text-[#484f58] transition-colors duration-150" />
            </div>

            {error && (
              <div className="p-3 rounded-lg bg-[#dc2626]/5 border border-[#dc2626]/10">
                <p className="text-sm text-[#f87171]">{error}</p>
              </div>
            )}

            <button type="submit" disabled={loading}
              className="w-full h-12 rounded-lg text-[12px] font-bold uppercase tracking-[0.15em] text-white bg-[#238636] hover:bg-[#2ea043] disabled:opacity-40 disabled:cursor-not-allowed transition-colors duration-150 flex items-center justify-center gap-2">
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
