"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

// ── Niche tags ──────────────────────────────────────────────────────────
const NICHE_TAGS = [
  "Business", "Entrepreneurship", "Motivation", "Mindset", "Finance", "Investing", "Real Estate",
  "Crypto", "Wealth", "Money", "Side Hustle", "Freelancing", "Marketing", "Sales", "E-commerce",
  "Dropshipping", "Amazon FBA", "Personal Brand", "Leadership", "Coaching",
  "Fitness", "Gym", "Bodybuilding", "Weight Loss", "Yoga", "CrossFit", "Running", "Nutrition",
  "Supplements", "Wellness", "Mental Health", "Self Care", "Meditation",
  "Beauty", "Skincare", "Makeup", "Hair", "Nails", "Fashion", "Style", "Outfits", "Streetwear",
  "Luxury", "Designer", "Watches", "Cars", "Lifestyle",
  "Comedy", "Memes", "Funny", "Entertainment", "Gaming", "Esports", "Streaming",
  "Tech", "AI", "Programming", "Coding", "Startups", "SaaS", "Apps", "Gadgets",
  "Food", "Cooking", "Recipes", "Baking", "Restaurant", "Foodie", "Vegan",
  "Travel", "Adventure", "Backpacking", "Hotels", "Flights", "Digital Nomad",
  "Photography", "Videography", "Film", "Editing", "Content Creation",
  "Music", "DJ", "Producer", "Singing", "Guitar", "Piano",
  "Education", "Learning", "Study", "University", "Science", "History",
  "Sports", "Soccer", "Basketball", "Football", "MMA", "Boxing", "Tennis",
  "Parenting", "Family", "Kids", "Pregnancy", "Home", "Interior Design",
  "Pets", "Dogs", "Cats", "Animals",
  "Art", "Drawing", "Painting", "Design", "Architecture",
  "Spirituality", "Astrology", "Manifestation", "Law of Attraction",
  "Dating", "Relationships", "Marriage", "Confidence", "Social Skills",
  "News", "Politics", "World Events", "Climate", "Environment",
];

// ── Analyzing steps ─────────────────────────────────────────────────────
const ANALYZING_STEPS = [
  "Connecting to Instagram...",
  "Analyzing your content style...",
  "Discovering similar pages...",
  "Scanning viral reels...",
  "Profiling content matches...",
  "Building your personalized feed...",
];

type Phase = "connect" | "niche" | "references" | "analyzing" | "done" | "error";

export default function OnboardingPage() {
  const router = useRouter();

  // ── Shared state ────────────────────────────────────────────────────
  const [phase, setPhase] = useState<Phase>("connect");
  const [error, setError] = useState("");

  // Phase 1: Connect
  const [username, setUsername] = useState("");
  const [ownPageId, setOwnPageId] = useState<string | null>(null);

  // Phase 2: Niche
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  // Phase 3: References
  const [refInput, setRefInput] = useState("");
  const [referencePages, setReferencePages] = useState<{ username: string; id?: string }[]>([]);
  const [addingRef, setAddingRef] = useState(false);

  // Phase 4: Analyzing
  const [stepIndex, setStepIndex] = useState(0);

  // ── Step animation ──────────────────────────────────────────────────
  useEffect(() => {
    if (phase !== "analyzing") return;
    const timer = setInterval(() => {
      setStepIndex((prev) => Math.min(prev + 1, ANALYZING_STEPS.length - 1));
    }, 2500);
    return () => clearInterval(timer);
  }, [phase]);

  // ── Phase 1: Connect handler ───────────────────────────────────────
  const handleConnect = useCallback(async () => {
    const clean = username.trim().replace("@", "").replace("https://www.instagram.com/", "").replace("/", "");
    if (!clean) return;
    setUsername(clean);

    try {
      const page = await api.myPages.add(clean, "own");
      setOwnPageId(page.id);
      setPhase("niche");
    } catch (err: any) {
      if (err?.message?.includes("already")) {
        // Page already connected — try to get it from list
        try {
          const pages = await api.myPages.list("own");
          const existing = pages.find((p) => p.ig_username === clean);
          if (existing) {
            setOwnPageId(existing.id);
            setPhase("niche");
            return;
          }
        } catch {}
        // Fallback: just go to dashboard
        router.push("/dashboard");
      } else {
        setError(err?.message || "Something went wrong. Please try again.");
        setPhase("error");
      }
    }
  }, [username, router]);

  // ── Phase 2: Niche handler ─────────────────────────────────────────
  const toggleTag = (tag: string) => {
    setSelectedTags((prev) => {
      if (prev.includes(tag)) return prev.filter((t) => t !== tag);
      if (prev.length >= 5) return prev;
      return [...prev, tag];
    });
  };

  const handleNicheNext = async () => {
    if (selectedTags.length === 0 || !ownPageId) return;
    try {
      await api.myPages.setNicheTags(ownPageId, selectedTags);
    } catch (err: any) {
      // Non-blocking — tags are nice-to-have, don't block flow
    }
    setPhase("references");
  };

  // ── Phase 3: References handler ────────────────────────────────────
  const handleAddRef = async () => {
    const clean = refInput.trim().replace("@", "").replace("https://www.instagram.com/", "").replace("/", "");
    if (!clean) return;
    if (referencePages.some((r) => r.username === clean)) {
      setRefInput("");
      return;
    }
    if (referencePages.length >= 10) return;

    setAddingRef(true);
    try {
      const page = await api.myPages.add(clean, "reference");
      setReferencePages((prev) => [...prev, { username: clean, id: page.id }]);
      setRefInput("");
    } catch (err: any) {
      if (err?.message?.includes("already")) {
        // Already connected — just add to local list
        setReferencePages((prev) => [...prev, { username: clean }]);
        setRefInput("");
      } else {
        setError(err?.message || "Failed to add page");
      }
    } finally {
      setAddingRef(false);
    }
  };

  const handleRemoveRef = (username: string) => {
    const ref = referencePages.find((r) => r.username === username);
    if (ref?.id) {
      api.myPages.remove(ref.id).catch(() => {});
    }
    setReferencePages((prev) => prev.filter((r) => r.username !== username));
  };

  const handleReferencesNext = async () => {
    setPhase("analyzing");
    setStepIndex(0);

    // Trigger deep discovery pipeline in background
    if (ownPageId) {
      try {
        await api.myPages.triggerDiscovery(ownPageId);
      } catch (err) {
        // Non-blocking — pipeline runs async, don't stop onboarding
        console.warn("Discovery trigger failed:", err);
      }
    }

    // Wait for animation, then redirect to discover page
    setTimeout(() => {
      setPhase("done");
      setTimeout(() => router.push("/discover"), 1500);
    }, ANALYZING_STEPS.length * 2500 + 1000);
  };

  const handleSkipReferences = async () => {
    setPhase("analyzing");
    setStepIndex(0);

    // Still trigger discovery even without references (will use fallback)
    if (ownPageId) {
      try {
        await api.myPages.triggerDiscovery(ownPageId);
      } catch (err) {
        console.warn("Discovery trigger failed:", err);
      }
    }

    setTimeout(() => {
      setPhase("done");
      setTimeout(() => router.push("/discover"), 1500);
    }, ANALYZING_STEPS.length * 2500 + 1000);
  };

  // ── Render ──────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[#0d1117] flex items-center justify-center">
      <div className="w-full max-w-lg px-6">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-lg bg-[#238636] flex items-center justify-center mx-auto mb-3">
            <span className="text-lg font-black text-white">SP</span>
          </div>
        </div>

        {/* ── Phase 1: Connect ───────────────────────────────────────── */}
        {phase === "connect" && (
          <div className="space-y-6">
            <div className="text-center">
              <h1 className="text-2xl font-bold text-[#e6edf3] mb-2">Connect Your Instagram</h1>
              <p className="text-sm text-[#7d8590]">
                Enter your Instagram username and we'll find the best viral reels for your page
              </p>
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

        {/* ── Phase 2: Niche ─────────────────────────────────────────── */}
        {phase === "niche" && (
          <div className="space-y-6">
            <div className="text-center">
              <h1 className="text-2xl font-bold text-[#e6edf3] mb-2">Choose Your Niche</h1>
              <p className="text-sm text-[#7d8590]">
                Select 1-5 tags that describe your page. This helps us find the best content for you.
              </p>
            </div>

            <div className="bg-[#161b22] border border-[#21262d] rounded-lg p-5">
              <div className="flex flex-wrap gap-2 max-h-[340px] overflow-y-auto pr-1">
                {NICHE_TAGS.map((tag) => {
                  const selected = selectedTags.includes(tag);
                  return (
                    <button
                      key={tag}
                      onClick={() => toggleTag(tag)}
                      className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors ${
                        selected
                          ? "bg-[#238636] text-white border-[#238636]"
                          : "bg-[#161b22] text-[#7d8590] border-[#21262d] hover:border-[#30363d] hover:text-[#e6edf3]"
                      }`}
                    >
                      {tag}
                    </button>
                  );
                })}
              </div>

              {selectedTags.length > 0 && (
                <div className="mt-4 pt-3 border-t border-[#21262d]">
                  <p className="text-xs text-[#7d8590] mb-2">
                    Selected ({selectedTags.length}/5):
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedTags.map((tag) => (
                      <span
                        key={tag}
                        className="px-2 py-1 text-xs bg-[#238636] text-white rounded-md cursor-pointer hover:bg-[#2ea043]"
                        onClick={() => toggleTag(tag)}
                      >
                        {tag} x
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="flex gap-3">
              <Button
                variant="secondary"
                className="flex-1"
                onClick={() => setPhase("connect")}
              >
                Back
              </Button>
              <Button
                size="lg"
                className="flex-1"
                onClick={handleNicheNext}
                disabled={selectedTags.length === 0}
              >
                Continue
              </Button>
            </div>
          </div>
        )}

        {/* ── Phase 3: References ────────────────────────────────────── */}
        {phase === "references" && (
          <div className="space-y-6">
            <div className="text-center">
              <h1 className="text-2xl font-bold text-[#e6edf3] mb-2">Add Reference Pages</h1>
              <p className="text-sm text-[#7d8590]">
                Add pages you want to be like. These pages inspire your content style.
                We'll find viral reels similar to what they post.
              </p>
            </div>

            <div className="bg-[#161b22] border border-[#21262d] rounded-lg p-5 space-y-4">
              {/* Input row */}
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[#484f58] text-sm">@</span>
                  <input
                    type="text"
                    value={refInput}
                    onChange={(e) => setRefInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleAddRef()}
                    placeholder="reference_page"
                    className="w-full h-10 pl-8 pr-3 text-sm bg-[#0d1117] text-[#e6edf3] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff] placeholder:text-[#484f58]"
                    disabled={addingRef || referencePages.length >= 10}
                    autoFocus
                  />
                </div>
                <Button
                  onClick={handleAddRef}
                  disabled={addingRef || !refInput.trim() || referencePages.length >= 10}
                  className="h-10 px-4"
                >
                  {addingRef ? "Adding..." : "Add"}
                </Button>
              </div>

              {/* Counter */}
              <p className="text-xs text-[#7d8590]">
                {referencePages.length}/10 added
                {referencePages.length < 3 && (
                  <span className="text-[#484f58]"> (minimum 3)</span>
                )}
              </p>

              {/* List */}
              {referencePages.length > 0 && (
                <div className="space-y-2 max-h-[220px] overflow-y-auto">
                  {referencePages.map((ref) => (
                    <div
                      key={ref.username}
                      className="flex items-center justify-between py-2 px-3 bg-[#0d1117] border border-[#21262d] rounded-lg"
                    >
                      <span className="text-sm text-[#e6edf3]">@{ref.username}</span>
                      <button
                        onClick={() => handleRemoveRef(ref.username)}
                        className="text-[#484f58] hover:text-[#f85149] transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {error && phase === "references" && (
                <p className="text-xs text-[#f85149]">{error}</p>
              )}
            </div>

            <div className="flex gap-3">
              <Button
                variant="secondary"
                className="flex-1"
                onClick={() => { setError(""); setPhase("niche"); }}
              >
                Back
              </Button>
              <Button
                size="lg"
                className="flex-1"
                onClick={handleReferencesNext}
                disabled={referencePages.length < 3}
              >
                Continue
              </Button>
            </div>

            <button
              onClick={handleSkipReferences}
              className="block mx-auto text-xs text-[#484f58] hover:text-[#7d8590] transition-colors"
            >
              Skip for now
            </button>
          </div>
        )}

        {/* ── Phase 4: Analyzing ─────────────────────────────────────── */}
        {phase === "analyzing" && (
          <div className="text-center space-y-8">
            <div>
              <h1 className="text-xl font-bold text-[#e6edf3] mb-2">Building Your Feed</h1>
              <p className="text-sm text-[#7d8590]">This takes about 15 seconds</p>
            </div>

            <div className="space-y-4">
              <div className="w-full h-1 bg-[#21262d] rounded-full overflow-hidden">
                <div
                  className="h-full bg-[#58a6ff] rounded-full transition-all duration-1000 ease-out"
                  style={{ width: `${Math.min(((stepIndex + 1) / ANALYZING_STEPS.length) * 100, 95)}%` }}
                />
              </div>

              <div className="space-y-2">
                {ANALYZING_STEPS.map((step, i) => (
                  <div
                    key={i}
                    className={`flex items-center gap-2 text-sm transition-all duration-300 ${
                      i < stepIndex ? "text-[#3fb950]" : i === stepIndex ? "text-[#e6edf3]" : "text-[#21262d]"
                    }`}
                  >
                    {i < stepIndex ? (
                      <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
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

        {/* ── Done ───────────────────────────────────────────────────── */}
        {phase === "done" && (
          <div className="text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-[#0f2e16] flex items-center justify-center mx-auto">
              <svg className="w-8 h-8 text-[#3fb950]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-[#e6edf3]">You're all set!</h1>
            <p className="text-sm text-[#7d8590]">Your personalized feed is ready. Redirecting...</p>
          </div>
        )}

        {/* ── Error ──────────────────────────────────────────────────── */}
        {phase === "error" && (
          <div className="text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-[#3c1418] flex items-center justify-center mx-auto">
              <svg className="w-8 h-8 text-[#f85149]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-[#e6edf3]">Something went wrong</h1>
            <p className="text-sm text-[#f85149]">{error}</p>
            <Button variant="secondary" onClick={() => { setError(""); setPhase("connect"); }}>
              Try Again
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
