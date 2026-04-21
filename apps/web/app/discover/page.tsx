"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Loading } from "@/components/shared/loading";
import { SkeletonDiscover } from "@/components/shared/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { api, UserPage, Recommendation, RecommendationSummary } from "@/lib/api";
import { formatViews, formatDuration, formatDate } from "@/lib/utils";

type SortBy = "score" | "views" | "recent";

export default function DiscoverPage() {
  const router = useRouter();
  const [pages, setPages] = useState<UserPage[]>([]);
  const [activePage, setActivePage] = useState<UserPage | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [summary, setSummary] = useState<RecommendationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingRecs, setLoadingRecs] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sortBy, setSortBy] = useState<SortBy>("score");
  const [minViews, setMinViews] = useState<number>(0);
  const [pageSize] = useState<number>(100);
  const [offset, setOffset] = useState<number>(0);
  const [hasMore, setHasMore] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPages = useCallback(async () => {
    try {
      const all = await api.myPages.list();
      setPages(all);
      if (all.length > 0 && !activePage) setActivePage(all[0]);
    } catch (e: any) {
      console.error("Failed to fetch pages:", e?.message || "unknown error");
      setError(e?.message || "Failed to load pages. Please try again.");
    }
    setLoading(false);
  }, [activePage]);

  useEffect(() => {
    fetchPages();
  }, [fetchPages]);

  const loadRecs = useCallback(async () => {
    if (!activePage) return;
    setLoadingRecs(true);
    setOffset(0);
    setHasMore(true);
    try {
      const [list, sum] = await Promise.all([
        api.myPages.getRecommendations(activePage.id, {
          sort_by: sortBy,
          limit: pageSize,
          offset: 0,
          min_views: minViews,
        }),
        api.myPages.getRecommendationsSummary(activePage.id).catch(() => null),
      ]);
      setRecs(list);
      setSummary(sum);
      setOffset(list.length);
      setHasMore(list.length >= pageSize);
    } catch (e: any) {
      console.error("Failed to load recommendations:", e?.message || "unknown error");
      setError(e?.message || "Failed to load recommendations. Please try again.");
      setRecs([]);
      setSummary(null);
      setHasMore(false);
    }
    setLoadingRecs(false);
  }, [activePage, sortBy, minViews, pageSize]);

  const loadMore = useCallback(async () => {
    if (!activePage || loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const next = await api.myPages.getRecommendations(activePage.id, {
        sort_by: sortBy,
        limit: pageSize,
        offset,
        min_views: minViews,
      });
      setRecs((prev) => {
        const seen = new Set(prev.map((r) => r.id));
        const add = next.filter((r) => !seen.has(r.id));
        return [...prev, ...add];
      });
      setOffset((o) => o + next.length);
      if (next.length < pageSize) setHasMore(false);
    } catch (e: any) {
      console.error("Failed to load more recommendations:", e?.message || "unknown error");
      setError(e?.message || "Failed to load more reels. Please try again.");
      setHasMore(false);
    }
    setLoadingMore(false);
  }, [activePage, sortBy, minViews, pageSize, offset, loadingMore, hasMore]);

  useEffect(() => {
    loadRecs();
  }, [loadRecs]);

  const handleUseReel = async (rec: Recommendation) => {
    try {
      const result = await api.recommendations.use(rec.id);
      router.push(`/reels/${result.viral_reel_id}`);
    } catch (e: any) {
      console.error("Failed to use reel:", e?.message || "unknown error");
      setError(e?.message || "Failed to use this reel. Please try again.");
    }
  };

  const handleDismiss = async (rec: Recommendation) => {
    try {
      await api.recommendations.dismiss(rec.id);
      setRecs((prev) => prev.filter((r) => r.id !== rec.id));
    } catch (e: any) {
      console.error("Failed to dismiss reel:", e?.message || "unknown error");
      setError(e?.message || "Failed to dismiss reel. Please try again.");
    }
  };

  if (loading) return <SkeletonDiscover />;

  if (pages.length === 0) {
    return (
      <div className="p-8 max-w-3xl mx-auto">
        <Card>
          <EmptyState
            title="Add a page to unlock the discover feed"
            description="Add a reference page (or your own) in Settings. We'll find similar content and surface 100+ reels with 500K+ views."
            actionLabel="Go to Settings"
            onAction={() => router.push("/settings")}
          />
        </Card>
      </div>
    );
  }

  const stillBuilding = summary && !summary.meets_target;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {error && (
        <div className="mx-4 mt-4 p-3 text-sm text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded">
          {error}
        </div>
      )}
      {/* Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-[#e6edf3]">Discover</h1>
          {pages.length > 1 && (
            <select
              value={activePage?.id || ""}
              onChange={(e) => setActivePage(pages.find((p) => p.id === e.target.value) || null)}
              className="h-9 px-3 text-sm bg-[#161b22] text-[#e6edf3] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff]"
            >
              {pages.map((p) => (
                <option key={p.id} value={p.id}>
                  @{p.ig_username} {p.page_type === "reference" ? "(ref)" : ""}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="flex items-center gap-1.5 bg-[#161b22] border border-[#21262d] rounded-lg p-1">
          {[
            { value: 0, label: "All" },
            { value: 10000, label: "10K+" },
            { value: 100000, label: "100K+" },
            { value: 500000, label: "500K+" },
            { value: 1000000, label: "1M+" },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => setMinViews(opt.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors duration-150 ${
                minViews === opt.value
                  ? "bg-[#21262d] text-[#e6edf3]"
                  : "text-[#7d8590] hover:text-[#e6edf3]"
              }`}
            >
              {opt.label}
            </button>
          ))}
          <div className="w-px h-5 bg-[#21262d] mx-1" />
          {[
            { value: "score" as SortBy, label: "Best match" },
            { value: "views" as SortBy, label: "Most views" },
            { value: "recent" as SortBy, label: "Recent" },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => setSortBy(opt.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors duration-150 ${
                sortBy === opt.value
                  ? "bg-[#21262d] text-[#e6edf3]"
                  : "text-[#7d8590] hover:text-[#e6edf3]"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Summary banner */}
      {summary && (
        <Card className="mb-4">
          <div className="flex items-center justify-between text-sm">
            <div>
              <span className="text-[#e6edf3] font-medium">{summary.at_least_500k}</span>
              <span className="text-[#7d8590]"> reels ≥ {formatViews(summary.view_floor)} views</span>
              <span className="text-[#484f58] ml-3">({summary.total} total in pool)</span>
            </div>
            {stillBuilding ? (
              <span className="text-[11px] text-[#f0a500]">
                Still building your pool — target 500+
              </span>
            ) : (
              <span className="text-[11px] text-[#3fb950]">{summary.total} reels available</span>
            )}
          </div>
        </Card>
      )}

      {loadingRecs ? (
        <Loading size="md" className="py-16" />
      ) : recs.length === 0 ? (
        <Card>
          <EmptyState
            title="No reels yet"
            description="We're scraping and scoring — try lowering the view filter, or check back after the next discovery run."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {recs.map((rec) => (
            <div
              key={rec.id}
              className="bg-[#161b22] border border-[#21262d] rounded-lg overflow-hidden transition-colors duration-150 group hover:border-[#30363d]"
            >
              <div className="relative aspect-video bg-[#0d1117] overflow-hidden">
                {/* Thumbnail proxied through our API (fetches from Instagram server-side, no CORS issues) */}
                <img
                  src={`${api.files.getThumbnailUrl(rec.viral_reel_id)}?v=${Math.floor(Date.now() / 3600000)}`}
                  alt=""
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
                <div className="absolute top-2 left-2 flex gap-1.5">
                  <span className="bg-black/60 backdrop-blur-sm text-white text-[10px] font-medium px-1.5 py-0.5 rounded">
                    {formatViews(rec.view_count)} views
                  </span>
                  {rec.duration_seconds && (
                    <span className="bg-black/75 text-white text-[10px] px-1.5 py-0.5 rounded">
                      {formatDuration(rec.duration_seconds)}
                    </span>
                  )}
                </div>
                <div className="absolute top-2 right-2">
                  <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${Math.round(rec.match_score * 100) > 70 ? "bg-[#3fb950]/15 text-[#3fb950]" : "bg-[#0f2e16]/90 text-[#3fb950]"}`}>
                    {Math.round(rec.match_score * 100)}%
                  </span>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDismiss(rec);
                  }}
                  className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 bg-black/60 rounded-full p-1 text-white/70 hover:text-white transition-opacity"
                  title="Dismiss"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="p-3.5 space-y-2">
                <p className="text-[10px] text-[#58a6ff] font-medium">{rec.match_reason}</p>
                <p className="text-[13px] text-[#e6edf3] leading-snug line-clamp-2">
                  {rec.caption || "Viral Reel"}
                </p>
                <div className="flex items-center gap-2 text-[10px] text-[#484f58]">
                  {rec.source_page && <span>@{rec.source_page}</span>}
                  <span>·</span>
                  <span>{formatViews(rec.like_count)} likes</span>
                  {rec.posted_at && (
                    <>
                      <span>·</span>
                      <span>{formatDate(rec.posted_at)}</span>
                    </>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button size="sm" className="flex-1" onClick={() => handleUseReel(rec)}>
                    Use This Reel
                  </Button>
                  {rec.ig_url && (
                    <a
                      href={rec.ig_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="h-8 px-3 text-xs font-medium text-[#7d8590] bg-[#21262d] hover:bg-[#30363d] hover:text-[#e6edf3] border border-[#30363d] rounded-lg flex items-center gap-1.5 transition-colors"
                    >
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                      </svg>
                      View
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Load more */}
      {!loadingRecs && recs.length > 0 && hasMore && (
        <div className="flex justify-center py-8">
          <Button size="lg" variant="secondary" onClick={loadMore} loading={loadingMore} className="px-8">
            Load more reels
          </Button>
        </div>
      )}
      {!loadingRecs && recs.length > 0 && !hasMore && (
        <p className="text-center text-xs text-[#484f58] py-6">
          End of feed · {recs.length} reels shown
        </p>
      )}
    </div>
  );
}
