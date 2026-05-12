"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api, type DiscoveryFilter, type DiscoverySortBy } from "@/lib/api";

const SORT_OPTIONS: { value: DiscoverySortBy; label: string }[] = [
  { value: "views_desc", label: "Most views" },
  { value: "posted_at_desc", label: "Most recent" },
  { value: "engagement_desc", label: "Highest engagement" },
  { value: "likes_desc", label: "Most likes" },
  { value: "comments_desc", label: "Most comments" },
];

interface SourcesFilterBarProps {
  /** Called after the saved filter has been updated on the server. */
  onChange: (filter: DiscoveryFilter) => void;
  /** Refresh button click handler — owns rate-limit feedback at the page level. */
  onRefresh: () => void;
  /** True while the refresh BackgroundTask is in-flight. */
  refreshing: boolean;
  /** Optional message shown next to refresh (e.g. "Rate limited — try later"). */
  refreshNote?: string | null;
}

/**
 * Inline filter bar — sort_by + min_views, auto-saves on change so the
 * /sources feed always reflects the saved filter. Full editor with all
 * thresholds lives in /settings (DiscoveryFilterPanel). Keeping the
 * inline bar minimal keeps the discovery surface uncluttered.
 */
export function SourcesFilterBar({
  onChange,
  onRefresh,
  refreshing,
  refreshNote,
}: SourcesFilterBarProps) {
  const [filter, setFilter] = useState<DiscoveryFilter | null>(null);
  const [draftMinViews, setDraftMinViews] = useState<string>("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.discoveryFilter.get().then((f) => {
      if (cancelled) return;
      setFilter(f);
      setDraftMinViews(String(f.min_views));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async (payload: Partial<DiscoveryFilter>) => {
    if (!filter) return;
    setSaving(true);
    try {
      const next = await api.discoveryFilter.save({ ...filter, ...payload });
      setFilter(next);
      setDraftMinViews(String(next.min_views));
      onChange(next);
    } catch (e) {
      // Surface via console — the page owns the user-facing error slot
      // and the bar is intentionally low-noise.
      console.error("Failed to save filter:", e);
    }
    setSaving(false);
  };

  const handleSortChange = (v: string) => {
    save({ sort_by: v as DiscoverySortBy });
  };

  const handleMinViewsCommit = () => {
    if (!filter) return;
    const parsed = Number.parseInt(draftMinViews, 10);
    if (!Number.isFinite(parsed) || parsed < 0) {
      setDraftMinViews(String(filter.min_views));
      return;
    }
    if (parsed === filter.min_views) return; // no-op
    save({ min_views: parsed });
  };

  return (
    <div className="flex items-center gap-3 flex-wrap" data-testid="sources-filter-bar">
      <div className="w-44">
        <Select
          options={SORT_OPTIONS}
          value={filter?.sort_by ?? "views_desc"}
          onChange={handleSortChange}
        />
      </div>
      <div className="w-36">
        <Input
          type="number"
          min={0}
          placeholder="Min views"
          value={draftMinViews}
          onChange={(e) => setDraftMinViews(e.target.value)}
          onBlur={handleMinViewsCommit}
          onKeyDown={(e) => e.key === "Enter" && handleMinViewsCommit()}
          data-testid="sources-min-views"
        />
      </div>
      <a
        href="/settings"
        className="text-[11px] text-[#58a6ff] hover:underline"
      >
        More filters →
      </a>
      <div className="flex-1" />
      <Button
        size="sm"
        variant="secondary"
        onClick={onRefresh}
        loading={refreshing}
        disabled={saving || refreshing}
        data-testid="sources-refresh"
      >
        Refresh
      </Button>
      {refreshNote && (
        <span
          role="status"
          data-testid="sources-refresh-note"
          className="text-[11px] text-[#7d8590]"
        >
          {refreshNote}
        </span>
      )}
    </div>
  );
}
