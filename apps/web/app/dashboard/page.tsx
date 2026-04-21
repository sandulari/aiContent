"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SkeletonDashboard } from "@/components/shared/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { api, UserPage, DashboardData, WeeklyDashboard, UserExport } from "@/lib/api";
import { formatDate } from "@/lib/utils";

// ── Helpers ─────────────────────────────────────────────────────────────

function formatNumber(n: number | null): string {
  if (n == null) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return toISODate(new Date());
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return toISODate(d);
}

// ── Date range presets ──────────────────────────────────────────────────

interface DateRange {
  from: string;
  to: string;
}

interface DateRangePreset {
  label: string;
  getValue: (() => DateRange) | null;
}

const DATE_RANGES: DateRangePreset[] = [
  { label: "Today", getValue: () => ({ from: today(), to: today() }) },
  { label: "Last 7 days", getValue: () => ({ from: daysAgo(7), to: today() }) },
  { label: "Last 14 days", getValue: () => ({ from: daysAgo(14), to: today() }) },
  { label: "Last 30 days", getValue: () => ({ from: daysAgo(30), to: today() }) },
  { label: "Custom", getValue: null },
];

// ── Calendar helpers ────────────────────────────────────────────────────

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DAY_LABELS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function getCalendarDays(year: number, month: number) {
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const daysInPrevMonth = new Date(year, month, 0).getDate();

  const days: { date: Date; inMonth: boolean }[] = [];

  for (let i = firstDay - 1; i >= 0; i--) {
    days.push({ date: new Date(year, month - 1, daysInPrevMonth - i), inMonth: false });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    days.push({ date: new Date(year, month, d), inMonth: true });
  }
  const remaining = 42 - days.length;
  for (let d = 1; d <= remaining; d++) {
    days.push({ date: new Date(year, month + 1, d), inMonth: false });
  }
  return days;
}

function sameDay(a: Date | null, b: Date | null): boolean {
  if (!a || !b) return false;
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function isBetween(d: Date, start: Date | null, end: Date | null): boolean {
  if (!start || !end) return false;
  const t = d.getTime();
  return t > start.getTime() && t < end.getTime();
}

// ── DateRangePicker ─────────────────────────────────────────────────────

function DateRangePicker({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (r: DateRange) => void;
}) {
  const [open, setOpen] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(1); // default "Last 7 days"
  const ref = useRef<HTMLDivElement>(null);

  // Calendar state
  const now = new Date();
  const [displayMonth, setDisplayMonth] = useState(now.getMonth());
  const [displayYear, setDisplayYear] = useState(now.getFullYear());
  const [rangeStart, setRangeStart] = useState<Date | null>(null);
  const [rangeEnd, setRangeEnd] = useState<Date | null>(null);
  const [pickingState, setPickingState] = useState<"start" | "end">("start");

  // close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const activeLabel = DATE_RANGES[selectedIdx]?.label ?? "Last 7 days";

  function selectPreset(idx: number) {
    setSelectedIdx(idx);
    const preset = DATE_RANGES[idx];
    if (preset.getValue) {
      const r = preset.getValue();
      onChange(r);
      setRangeStart(null);
      setRangeEnd(null);
      setPickingState("start");
      setOpen(false);
    }
    // If "Custom" (getValue is null), just show the calendar
  }

  function prevMonth() {
    if (displayMonth === 0) {
      setDisplayMonth(11);
      setDisplayYear(displayYear - 1);
    } else {
      setDisplayMonth(displayMonth - 1);
    }
  }

  function nextMonth() {
    if (displayMonth === 11) {
      setDisplayMonth(0);
      setDisplayYear(displayYear + 1);
    } else {
      setDisplayMonth(displayMonth + 1);
    }
  }

  function handleDayClick(date: Date) {
    if (pickingState === "start") {
      setRangeStart(date);
      setRangeEnd(null);
      setPickingState("end");
    } else {
      // If clicked date is before start, swap
      let start = rangeStart!;
      let end = date;
      if (end.getTime() < start.getTime()) {
        const tmp = start;
        start = end;
        end = tmp;
      }
      setRangeStart(start);
      setRangeEnd(end);
      setPickingState("start");
      setSelectedIdx(4); // "Custom"
      onChange({ from: toISODate(start), to: toISODate(end) });
      setOpen(false);
    }
  }

  function applyQuickAction(preset: "today" | "yesterday" | "last7") {
    let r: DateRange;
    if (preset === "today") {
      r = { from: today(), to: today() };
      setSelectedIdx(0);
    } else if (preset === "yesterday") {
      r = { from: daysAgo(1), to: daysAgo(1) };
      setSelectedIdx(4);
    } else {
      r = { from: daysAgo(7), to: today() };
      setSelectedIdx(1);
    }
    onChange(r);
    setRangeStart(null);
    setRangeEnd(null);
    setPickingState("start");
    setOpen(false);
  }

  const calendarDays = getCalendarDays(displayYear, displayMonth);
  const todayDate = new Date();

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="h-9 px-3 text-sm bg-[#161b22] text-[#e6edf3] border border-[#21262d] rounded-lg hover:border-[#30363d] transition-colors flex items-center gap-2"
      >
        <svg className="w-3.5 h-3.5 text-[#7d8590]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        <span>{activeLabel}</span>
        <svg className="w-3 h-3 text-[#484f58]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 z-50 w-72 bg-[#161b22] border border-[#21262d] rounded-xl shadow-2xl shadow-black/40 overflow-hidden">
          {/* Preset buttons */}
          {DATE_RANGES.map((preset, idx) => (
            <button
              key={preset.label}
              onClick={() => selectPreset(idx)}
              className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
                selectedIdx === idx
                  ? "bg-[#1f6feb]/15 text-[#58a6ff]"
                  : "text-[#e6edf3] hover:bg-[#21262d]"
              }`}
            >
              {preset.label}
            </button>
          ))}

          {/* Calendar (shown when Custom is selected) */}
          {selectedIdx === 4 && (
            <div className="border-t border-[#21262d] px-3 pt-3 pb-2">
              {/* Month header */}
              <div className="flex items-center justify-between mb-2">
                <button
                  onClick={prevMonth}
                  className="w-7 h-7 flex items-center justify-center rounded-md text-[#7d8590] hover:bg-[#21262d] hover:text-[#e6edf3] transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <span className="text-sm font-medium text-[#e6edf3]">
                  {MONTH_NAMES[displayMonth]} {displayYear}
                </span>
                <button
                  onClick={nextMonth}
                  disabled={displayYear === now.getFullYear() && displayMonth === now.getMonth()}
                  className={`w-7 h-7 flex items-center justify-center rounded-md transition-colors ${displayYear === now.getFullYear() && displayMonth === now.getMonth() ? "text-[#21262d] cursor-not-allowed" : "text-[#7d8590] hover:bg-[#21262d] hover:text-[#e6edf3]"}`}
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </div>

              {/* Day labels */}
              <div className="grid grid-cols-7 mb-1">
                {DAY_LABELS.map((dl) => (
                  <div key={dl} className="w-9 h-6 flex items-center justify-center text-[10px] font-medium text-[#484f58] uppercase">
                    {dl}
                  </div>
                ))}
              </div>

              {/* Day grid */}
              <div className="grid grid-cols-7">
                {calendarDays.map((day, i) => {
                  const isStart = sameDay(day.date, rangeStart);
                  const isEnd = sameDay(day.date, rangeEnd);
                  const isSelected = isStart || isEnd;
                  const isInRange = isBetween(day.date, rangeStart, rangeEnd);
                  const isToday = sameDay(day.date, todayDate);
                  const isFuture = day.date.getTime() > new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate() + 1).getTime() - 1;

                  // Connected range strip
                  const stripBg = isInRange || isStart || isEnd
                    ? isStart && isEnd ? ""
                    : isStart ? "bg-[#d4a843]/10 rounded-l-lg"
                    : isEnd ? "bg-[#d4a843]/10 rounded-r-lg"
                    : "bg-[#d4a843]/10"
                    : "";

                  return (
                    <div key={i} className={`relative flex items-center justify-center ${stripBg} transition-all duration-200`}>
                      <button
                        onClick={() => !isFuture && handleDayClick(day.date)}
                        disabled={isFuture}
                        className={[
                          "w-9 h-9 text-sm rounded-lg transition-all duration-200 relative z-10",
                          isFuture ? "text-[#21262d] cursor-not-allowed" : "",
                          !day.inMonth && !isFuture ? "text-[#30363d]" : "",
                          day.inMonth && !isSelected && !isInRange && !isFuture ? "text-[#e6edf3] hover:bg-[#21262d]" : "",
                          isStart ? "bg-[#d4a843] text-[#0d1117] font-bold shadow-lg shadow-[#d4a843]/25" : "",
                          isEnd ? "bg-[#d4a843] text-[#0d1117] font-bold shadow-lg shadow-[#d4a843]/25" : "",
                          isInRange && !isStart && !isEnd ? "text-[#d4a843] font-medium" : "",
                          isToday && !isSelected ? "bg-[#21262d] text-[#e6edf3] font-medium" : "",
                        ].filter(Boolean).join(" ")}
                      >
                        {day.date.getDate()}
                      </button>
                    </div>
                  );
                })}
              </div>

              {/* Quick actions */}
              <div className="flex items-center gap-3 pt-2 mt-1 border-t border-[#21262d]">
                <button
                  onClick={() => applyQuickAction("today")}
                  className="text-xs text-[#7d8590] hover:text-[#e6edf3] transition-colors"
                >
                  Today
                </button>
                <button
                  onClick={() => applyQuickAction("yesterday")}
                  className="text-xs text-[#7d8590] hover:text-[#e6edf3] transition-colors"
                >
                  Yesterday
                </button>
                <button
                  onClick={() => applyQuickAction("last7")}
                  className="text-xs text-[#7d8590] hover:text-[#e6edf3] transition-colors"
                >
                  Last 7 days
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── StatCard ────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  delta,
  deltaPct,
  format = "number",
}: {
  label: string;
  value: number | null;
  delta: number | null;
  deltaPct?: number | null;
  format?: "number" | "percent";
}) {
  const isPositive = delta != null && delta > 0;
  const isNegative = delta != null && delta < 0;
  const isZero = delta === 0 || delta == null;

  return (
    <div className="bg-[#161b22] border border-[#21262d] rounded-xl p-5">
      <p className="text-[11px] text-[#7d8590] uppercase tracking-wider mb-2">{label}</p>
      <p className="text-2xl font-bold text-[#e6edf3] tabular-nums">
        {format === "percent" ? `${(value ?? 0).toFixed(1)}%` : formatNumber(value)}
      </p>
      {!isZero && (
        <div className={`flex items-center gap-1 mt-1.5 text-xs ${isPositive ? "text-[#3fb950]" : "text-[#f85149]"}`}>
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d={isPositive ? "M5 15l7-7 7 7" : "M19 9l-7 7-7-7"}
            />
          </svg>
          <span>{deltaPct != null ? `${Math.abs(deltaPct).toFixed(1)}%` : formatNumber(Math.abs(delta!))}</span>
          <span className="text-[#484f58]">vs prev period</span>
        </div>
      )}
      {isZero && <p className="text-[11px] text-[#484f58] mt-1.5">No change</p>}
    </div>
  );
}

// ── ReelsTable (sortable) ───────────────────────────────────────────────

type ReelSortKey = "date" | "views" | "likes" | "comments";

function ReelsTable({ reels }: { reels: NonNullable<DashboardData["reels"]> }) {
  const [sortBy, setSortBy] = useState<ReelSortKey>("date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  function toggleSort(key: ReelSortKey) {
    if (sortBy === key) {
      setSortDir(sortDir === "desc" ? "asc" : "desc");
    } else {
      setSortBy(key);
      setSortDir("desc");
    }
  }

  const sorted = [...reels].sort((a, b) => {
    let diff = 0;
    switch (sortBy) {
      case "date":
        diff = (new Date(a.posted_at || 0).getTime()) - (new Date(b.posted_at || 0).getTime());
        break;
      case "views":
        diff = a.view_count - b.view_count;
        break;
      case "likes":
        diff = a.like_count - b.like_count;
        break;
      case "comments":
        diff = a.comment_count - b.comment_count;
        break;
    }
    return sortDir === "desc" ? -diff : diff;
  });

  const SortIcon = ({ active, dir }: { active: boolean; dir: "asc" | "desc" }) => (
    <svg className={`w-3 h-3 inline-block ml-0.5 ${active ? "text-[#58a6ff]" : "text-[#30363d]"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d={active && dir === "asc" ? "M5 15l7-7 7 7" : "M19 9l-7 7-7-7"} />
    </svg>
  );

  const ColHeader = ({ label, sortKey }: { label: string; sortKey: ReelSortKey }) => (
    <button
      onClick={() => toggleSort(sortKey)}
      className={`text-right flex items-center justify-end gap-0.5 hover:text-[#e6edf3] transition-colors ${sortBy === sortKey ? "text-[#58a6ff]" : ""}`}
    >
      {label}
      <SortIcon active={sortBy === sortKey} dir={sortDir} />
    </button>
  );

  return (
    <div className="mb-8">
      <h2 className="text-sm font-medium text-[#e6edf3] mb-3">
        Reels in This Period
        <span className="ml-2 text-[#484f58] font-normal">({reels.length})</span>
      </h2>
      <div className="bg-[#161b22] border border-[#21262d] rounded-xl overflow-hidden">
        <div className="grid grid-cols-[1fr_80px_80px_80px_100px] gap-2 px-4 py-2.5 border-b border-[#21262d] text-[10px] text-[#484f58] uppercase tracking-wider font-medium">
          <span>Caption</span>
          <ColHeader label="Views" sortKey="views" />
          <ColHeader label="Likes" sortKey="likes" />
          <ColHeader label="Comments" sortKey="comments" />
          <ColHeader label="Posted" sortKey="date" />
        </div>
        {sorted.map((reel, i) => (
          <a
            key={reel.ig_code}
            href={reel.ig_url}
            target="_blank"
            rel="noopener noreferrer"
            className={`grid grid-cols-[1fr_80px_80px_80px_100px] gap-2 px-4 py-3 items-center hover:bg-[#1c2129] transition-colors ${i !== sorted.length - 1 ? "border-b border-[#21262d]/50" : ""}`}
          >
            <span className="text-xs text-[#e6edf3] truncate">{reel.caption || "Untitled"}</span>
            <span className="text-xs text-[#e6edf3] text-right font-medium tabular-nums">{formatNumber(reel.view_count)}</span>
            <span className="text-xs text-[#e6edf3] text-right tabular-nums">{formatNumber(reel.like_count)}</span>
            <span className="text-xs text-[#7d8590] text-right tabular-nums">{formatNumber(reel.comment_count)}</span>
            <span className="text-[10px] text-[#484f58] text-right">{reel.posted_at ? formatDate(reel.posted_at) : "—"}</span>
          </a>
        ))}
      </div>
    </div>
  );
}

// ── Dashboard ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const router = useRouter();

  // Page data
  const [ownPages, setOwnPages] = useState<UserPage[]>([]);
  const [activePage, setActivePage] = useState<UserPage | null>(null);
  const [exports, setExports] = useState<UserExport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dashboard data
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashLoading, setDashLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Date range - default to Last 7 days
  const [dateRange, setDateRange] = useState<DateRange>(() => ({
    from: daysAgo(7),
    to: today(),
  }));

  // ── Fetch pages ─────────────────────────────────────────────────────

  const fetchPages = useCallback(async () => {
    try {
      const own = await api.myPages.list("own");
      setOwnPages(own);
      if (own.length > 0 && !activePage) setActivePage(own[0]);
      const exp = await api.exports.list();
      setExports(exp.slice(0, 3));
    } catch (e: any) {
      console.error("Failed to fetch pages:", e?.message || "unknown error");
      setError(e?.message || "Failed to load dashboard data. Please try again.");
    }
    setLoading(false);
  }, [activePage]);

  useEffect(() => {
    fetchPages();
  }, [fetchPages]);

  // ── Fetch dashboard data ────────────────────────────────────────────

  const fetchDashboard = useCallback(async (pageId: string, range: DateRange) => {
    setDashLoading(true);
    setError(null);
    try {
      // Try the new dashboard endpoint first
      const data = await api.myPages.getDashboard(pageId, {
        from_date: range.from,
        to_date: range.to,
      });
      setDashboard(data);
    } catch (newErr: any) {
      // Fallback to the old weekly-dashboard endpoint
      try {
        const weekly: WeeklyDashboard = await api.myPages.getWeeklyDashboard(pageId);
        // Map WeeklyDashboard to DashboardData shape
        setDashboard({
          page_id: weekly.page_id,
          ig_username: weekly.ig_username,
          period: { from_date: range.from, to_date: range.to, days: 7 },
          followers: weekly.follower_count,
          followers_delta: weekly.follower_delta,
          followers_delta_pct: null,
          views: weekly.total_views_week,
          views_delta: null,
          views_delta_pct: null,
          likes: weekly.total_likes_week,
          likes_delta: null,
          likes_delta_pct: null,
          comments: weekly.total_comments_week,
          comments_delta: weekly.comments_gained_wow,
          comments_delta_pct: null,
          posts_count: weekly.total_posts,
          posts_delta: weekly.total_posts_delta,
          engagement_rate: null,
          engagement_delta: weekly.engagement_rate_delta,
          top_reel: weekly.top_reel
            ? {
                ig_video_id: weekly.top_reel.ig_video_id,
                ig_url: weekly.top_reel.ig_url,
                view_count: weekly.top_reel.view_count ?? 0,
                like_count: weekly.top_reel.like_count ?? 0,
                caption: weekly.top_reel.caption,
                posted_at: null,
              }
            : null,
          daily_snapshots: [],
          has_data: weekly.has_data,
        });
      } catch {
        // Both failed - set empty dashboard
        setDashboard({
          page_id: pageId,
          ig_username: activePage?.ig_username ?? "",
          period: { from_date: range.from, to_date: range.to, days: 7 },
          followers: null,
          followers_delta: null,
          followers_delta_pct: null,
          views: null,
          views_delta: null,
          views_delta_pct: null,
          likes: null,
          likes_delta: null,
          likes_delta_pct: null,
          comments: null,
          comments_delta: null,
          comments_delta_pct: null,
          posts_count: null,
          posts_delta: null,
          engagement_rate: null,
          engagement_delta: null,
          top_reel: null,
          daily_snapshots: [],
          has_data: false,
        });
      }
    }
    setDashLoading(false);
  }, [activePage]);

  useEffect(() => {
    if (!activePage) return;
    fetchDashboard(activePage.id, dateRange);
  }, [activePage, dateRange, fetchDashboard]);

  // ── Refresh stats ───────────────────────────────────────────────────

  const handleRefresh = async () => {
    if (!activePage) return;
    setRefreshing(true);
    try {
      await api.myPages.refreshStats(activePage.id);
    } catch (e: any) {
      console.error("Failed to refresh stats:", e?.message || "unknown error");
      setError(e?.message || "Failed to refresh stats. Please try again.");
      setRefreshing(false);
      return;
    }
    // Wait 3 seconds then re-fetch
    setTimeout(() => {
      fetchDashboard(activePage.id, dateRange);
      setRefreshing(false);
    }, 3000);
  };

  // ── Loading state ───────────────────────────────────────────────────

  if (loading) return <SkeletonDashboard />;

  // ── No pages connected ──────────────────────────────────────────────

  if (ownPages.length === 0) {
    return (
      <div className="min-h-screen bg-[#0d1117] p-8">
        <div className="max-w-3xl mx-auto">
          <Card>
            <EmptyState
              title="Connect your own Instagram page"
              description="Your dashboard shows growth stats, top reels, and engagement deltas. Add your page to get started."
              actionLabel="Go to Settings"
              onAction={() => router.push("/settings")}
            />
          </Card>
        </div>
      </div>
    );
  }

  // ── Main dashboard ──────────────────────────────────────────────────

  const d = dashboard;
  const showNoDataBanner = d && !d.has_data;

  return (
    <div className="min-h-screen bg-[#0d1117]">
      <div className="p-6 max-w-6xl mx-auto">
        {/* Error banner */}
        {error && (
          <div className="mb-4 p-3 text-sm text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded-lg">
            {error}
          </div>
        )}

        {/* Header row */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold text-[#e6edf3]">Dashboard</h1>
            {activePage?.niche && (
              <span className="text-[11px] text-[#7d8590] bg-[#21262d] px-2.5 py-1 rounded-md">{activePage.niche}</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Page selector */}
            {ownPages.length > 1 ? (
              <select
                value={activePage?.id || ""}
                onChange={(e) => setActivePage(ownPages.find((p) => p.id === e.target.value) || null)}
                className="h-9 px-3 text-sm bg-[#161b22] text-[#e6edf3] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff]"
              >
                {ownPages.map((p) => (
                  <option key={p.id} value={p.id}>
                    @{p.ig_username}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-sm font-medium text-[#e6edf3]">@{activePage?.ig_username}</span>
            )}

            {/* Date range picker */}
            <DateRangePicker value={dateRange} onChange={setDateRange} />

            {/* Refresh button */}
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="h-9 w-9 flex items-center justify-center bg-[#161b22] border border-[#21262d] rounded-lg hover:border-[#30363d] transition-colors disabled:opacity-50"
              title="Refresh stats"
            >
              <svg
                className={`w-4 h-4 text-[#7d8590] ${refreshing ? "animate-spin" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
            </button>
          </div>
        </div>

        {/* Refreshing banner */}
        {refreshing && (
          <div className="mb-4 p-3 text-sm text-[#58a6ff] bg-[#1f6feb]/10 border border-[#1f6feb]/30 rounded-lg flex items-center gap-2">
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refreshing stats...
          </div>
        )}

        {/* No data banner */}
        {showNoDataBanner && (
          <div className="mb-6 p-4 bg-[#161b22] border border-[#21262d] rounded-xl">
            <p className="text-sm text-[#7d8590]">
              Connect your Instagram page and post your first reel to start tracking growth.
            </p>
          </div>
        )}

        {/* Stat cards - loading state */}
        {dashLoading && !dashboard ? (
          <SkeletonDashboard />
        ) : (
          <div className={`transition-opacity duration-300 ${dashLoading ? "opacity-50 pointer-events-none" : "opacity-100"}`}>
            {/* Primary stat cards row */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
              <div className="bg-[#161b22] border border-[#21262d] rounded-xl p-5">
                <p className="text-[11px] text-[#7d8590] uppercase tracking-wider mb-2">New Followers</p>
                <p className="text-2xl font-bold text-[#e6edf3] tabular-nums">
                  {d?.followers_delta != null ? (d.followers_delta >= 0 ? `+${formatNumber(d.followers_delta)}` : formatNumber(d.followers_delta)) : "—"}
                </p>
                <p className="text-[11px] text-[#484f58] mt-1.5">Total: {formatNumber(d?.followers ?? 0)}</p>
              </div>
              <StatCard
                label="Views"
                value={d?.views ?? 0}
                delta={d?.views_delta ?? null}
                deltaPct={d?.views_delta_pct ?? null}
              />
              <StatCard
                label="Likes"
                value={d?.likes ?? 0}
                delta={d?.likes_delta ?? null}
                deltaPct={d?.likes_delta_pct ?? null}
              />
              <StatCard
                label="Comments"
                value={d?.comments ?? 0}
                delta={d?.comments_delta ?? null}
                deltaPct={d?.comments_delta_pct ?? null}
              />
            </div>

            {/* Secondary stat cards row */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-8">
              <StatCard
                label="Posts"
                value={d?.posts_count ?? 0}
                delta={d?.posts_delta ?? null}
              />
              <StatCard
                label="Engagement Rate"
                value={d?.engagement_rate ?? 0}
                delta={d?.engagement_delta ?? null}
                format="percent"
              />
              <div className="bg-[#161b22] border border-[#21262d] rounded-xl p-5">
                <p className="text-[11px] text-[#7d8590] uppercase tracking-wider mb-2">New Leads</p>
                <p className="text-2xl font-bold text-[#e6edf3] tabular-nums">—</p>
                <p className="text-[11px] text-[#484f58] mt-1.5">Connect ManyChat in Settings</p>
              </div>
            </div>

            {/* Top performing reel */}
            {d?.top_reel && (
              <div className="mb-8">
                <h2 className="text-sm font-medium text-[#e6edf3] mb-3">Top Performing Reel</h2>
                <div className="bg-[#161b22] border border-[#21262d] rounded-xl p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-[#e6edf3] line-clamp-2 mb-3">
                        {d.top_reel.caption || "Untitled reel"}
                      </p>
                      <div className="flex items-center gap-5 text-xs">
                        <div className="flex items-center gap-1.5">
                          <svg className="w-3.5 h-3.5 text-[#7d8590]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                            <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                          </svg>
                          <span className="text-[#e6edf3] font-medium">{formatNumber(d.top_reel.view_count)} views</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <svg className="w-3.5 h-3.5 text-[#7d8590]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
                          </svg>
                          <span className="text-[#e6edf3] font-medium">{formatNumber(d.top_reel.like_count)} likes</span>
                        </div>
                        {d.top_reel.posted_at && (
                          <span className="text-[#484f58]">Posted {formatDate(d.top_reel.posted_at)}</span>
                        )}
                      </div>
                    </div>
                    {d.top_reel.ig_url && (
                      <a
                        href={d.top_reel.ig_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="shrink-0 text-xs text-[#58a6ff] hover:underline font-medium"
                      >
                        View on IG
                      </a>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* All reels in period — sortable */}
            {d?.reels && d.reels.length > 0 && (
              <ReelsTable reels={d.reels} />
            )}

            {/* Recent exports */}
            {exports.length > 0 && (
              <div>
                <h2 className="text-sm font-medium text-[#e6edf3] mb-3">Recent Exports</h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {exports.map((exp) => (
                    <div
                      key={exp.id}
                      className="bg-[#161b22] border border-[#21262d] rounded-xl p-4 flex items-center justify-between"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-[#e6edf3] font-medium truncate">{exp.headline_text}</p>
                        <p className="text-[10px] text-[#484f58] mt-0.5">{formatDate(exp.created_at)}</p>
                      </div>
                      <Button size="sm" variant="ghost" onClick={() => router.push(`/editor/${exp.id}`)}>
                        Edit
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
