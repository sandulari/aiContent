"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Loading } from "@/components/shared/loading";
import { EmptyState } from "@/components/shared/empty-state";
import { api, UserPage, WeeklyDashboard, UserExport } from "@/lib/api";
import { formatViews, formatDate } from "@/lib/utils";

function Stat({
  label,
  value,
  delta,
  highlight,
}: {
  label: string;
  value: React.ReactNode;
  delta?: number | null;
  highlight?: "pos" | "neg";
}) {
  const color = highlight === "pos" ? "text-[#3fb950]" : highlight === "neg" ? "text-[#f85149]" : "text-[#7d8590]";
  return (
    <div className="bg-[#0d1117] border border-[#21262d] rounded-xl px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-[#484f58]">{label}</p>
      <p className="text-xl font-semibold text-[#e6edf3] mt-1">{value}</p>
      {delta != null && (
        <p className={`text-[11px] mt-1 ${color}`}>
          {delta >= 0 ? "+" : ""}
          {delta.toLocaleString()} this week
        </p>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [ownPages, setOwnPages] = useState<UserPage[]>([]);
  const [activePage, setActivePage] = useState<UserPage | null>(null);
  const [weekly, setWeekly] = useState<WeeklyDashboard | null>(null);
  const [weeklyLoading, setWeeklyLoading] = useState(false);
  const [exports, setExports] = useState<UserExport[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPages = useCallback(async () => {
    try {
      const own = await api.myPages.list("own");
      setOwnPages(own);
      if (own.length > 0 && !activePage) setActivePage(own[0]);
      const exp = await api.exports.list();
      setExports(exp.slice(0, 5));
    } catch (e: any) {
      console.error("Failed to fetch pages:", e?.message || "unknown error");
      setError(e?.message || "Failed to load dashboard data. Please try again.");
    }
    setLoading(false);
  }, [activePage]);

  useEffect(() => {
    fetchPages();
  }, [fetchPages]);

  useEffect(() => {
    if (!activePage) return;
    setWeeklyLoading(true);
    api.myPages
      .getWeeklyDashboard(activePage.id)
      .then(setWeekly)
      .catch(() => setWeekly(null))
      .finally(() => setWeeklyLoading(false));
  }, [activePage]);

  const handleRefresh = async () => {
    if (!activePage) return;
    setRefreshing(true);
    try {
      await api.myPages.refreshStats(activePage.id);
    } catch (e: any) {
      console.error("Failed to refresh stats:", e?.message || "unknown error");
      setError(e?.message || "Failed to refresh stats. Please try again.");
    }
    setTimeout(async () => {
      try {
        const fresh = await api.myPages.getWeeklyDashboard(activePage.id);
        setWeekly(fresh);
      } catch (e: any) {
        console.error("Failed to load weekly dashboard:", e?.message || "unknown error");
        setError(e?.message || "Failed to load weekly stats. Please try again.");
      }
      setRefreshing(false);
    }, 3000);
  };

  if (loading) return <div className="p-8"><Loading size="lg" className="py-20" /></div>;

  if (ownPages.length === 0) {
    return (
      <div className="p-8 max-w-3xl mx-auto">
        <Card>
          <EmptyState
            title="Connect your own Instagram page"
            description="Your dashboard shows weekly growth — followers gained, top reels, comment & engagement deltas. Add your page to get started."
            actionLabel="Go to Settings"
            onAction={() => router.push("/settings")}
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {error && (
        <div className="mx-4 mt-4 p-3 text-sm text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded">
          {error}
        </div>
      )}
      {/* Page selector */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          {ownPages.length > 1 ? (
            <select
              value={activePage?.id || ""}
              onChange={(e) => setActivePage(ownPages.find((p) => p.id === e.target.value) || null)}
              className="h-9 px-3 text-sm bg-[#161b22] text-[#e6edf3] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff]"
            >
              {ownPages.map((p) => <option key={p.id} value={p.id}>@{p.ig_username}</option>)}
            </select>
          ) : (
            <h1 className="text-lg font-semibold text-[#e6edf3]">@{activePage?.ig_username}</h1>
          )}
          {activePage?.niche && (
            <span className="text-xs text-[#484f58] bg-[#21262d] px-2 py-0.5 rounded-md">{activePage.niche}</span>
          )}
          {weekly?.week_key && (
            <span className="text-[11px] text-[#484f58]">Week {weekly.week_key}</span>
          )}
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={handleRefresh} loading={refreshing}>
            Refresh stats
          </Button>
          <Button size="sm" onClick={() => router.push("/discover")}>Open Discover Feed</Button>
        </div>
      </div>

      {/* Weekly stats */}
      <div className="mb-8">
        <h2 className="text-sm font-medium text-[#e6edf3] mb-3">This week</h2>
        {weeklyLoading ? (
          <Loading size="md" className="py-12" />
        ) : !weekly?.has_data ? (
          <Card>
            <EmptyState
              title="Still gathering stats"
              description="Your first weekly snapshot is being built. Check back after the next scheduled run, or hit Refresh above to kick one off now."
            />
          </Card>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <Stat
                label="Followers"
                value={weekly.follower_count != null ? formatViews(weekly.follower_count) : "—"}
                delta={weekly.follower_delta}
                highlight={weekly.follower_delta && weekly.follower_delta > 0 ? "pos" : weekly.follower_delta && weekly.follower_delta < 0 ? "neg" : undefined}
              />
              <Stat
                label="Comments gained"
                value={weekly.comments_gained_wow != null ? weekly.comments_gained_wow.toLocaleString() : "—"}
                highlight={weekly.comments_gained_wow && weekly.comments_gained_wow > 0 ? "pos" : undefined}
              />
              <Stat
                label="Week views"
                value={weekly.total_views_week != null ? formatViews(weekly.total_views_week) : "—"}
              />
              <Stat
                label="Posts"
                value={weekly.total_posts != null ? weekly.total_posts : "—"}
                delta={weekly.total_posts_delta}
                highlight={weekly.total_posts_delta && weekly.total_posts_delta > 0 ? "pos" : undefined}
              />
            </div>

            {/* Top reel of the week */}
            {weekly.top_reel && (
              <Card>
                <div className="flex items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] uppercase tracking-wide text-[#484f58] mb-1">Top reel this week</p>
                    <p className="text-sm text-[#e6edf3] line-clamp-2">{weekly.top_reel.caption || "Untitled reel"}</p>
                    <div className="flex items-center gap-4 mt-2 text-xs text-[#7d8590]">
                      <span>{formatViews(weekly.top_reel.view_count || 0)} views</span>
                      <span>{formatViews(weekly.top_reel.like_count || 0)} likes</span>
                    </div>
                  </div>
                  {weekly.top_reel.ig_url && (
                    <a
                      href={weekly.top_reel.ig_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-[#58a6ff] hover:underline shrink-0"
                    >
                      View on IG ↗
                    </a>
                  )}
                </div>
              </Card>
            )}
          </>
        )}
      </div>

      {/* Recent exports */}
      {exports.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-[#e6edf3] mb-3">Recent exports</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {exports.map((exp) => (
              <Card key={exp.id}>
                <div className="flex items-center justify-between">
                  <div className="min-w-0">
                    <p className="text-sm text-[#e6edf3] font-medium truncate">{exp.headline_text}</p>
                    <p className="text-[10px] text-[#484f58] mt-0.5">{formatDate(exp.created_at)}</p>
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => router.push(`/editor/${exp.id}`)}>
                    Edit
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
