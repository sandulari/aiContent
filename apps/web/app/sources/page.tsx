"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { Card } from "@/components/ui/card";
import { SourcesFilterBar } from "@/components/sources/sourcesFilterBar";
import { SourcesGrid } from "@/components/sources/sourcesGrid";
import { ApiError, api, type DiscoveryItem } from "@/lib/api";

const REFRESH_REFETCH_MS = 6000;

/**
 * Per-reference-page discovery feed. Reads from the ``reference_reels``
 * cache populated by ``POST /api/discovery/refresh``. The filter bar
 * persists changes to the saved discovery_filter, so going to /settings
 * shows the same values.
 *
 * Refresh flow: click → POST /refresh → "Queued" note → 6s timer fires
 * loadItems() so the grid reflects whatever the BackgroundTask managed
 * to fetch. The user can click again if items haven't appeared yet.
 */
export default function SourcesPage() {
  const [items, setItems] = useState<DiscoveryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [hasCache, setHasCache] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  const loadItems = useCallback(async () => {
    setError(null);
    try {
      const r = await api.discovery.items();
      setItems(r.items);
      setTotal(r.total);
      setHasCache(r.has_cache);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load discovery feed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  // Auto-refetch after a refresh kicks off so the grid catches up to the
  // BackgroundTask without forcing a manual reload.
  useEffect(() => {
    if (!refreshNote?.startsWith("Refresh queued")) return;
    const t = setTimeout(() => {
      loadItems();
      setRefreshNote(null);
    }, REFRESH_REFETCH_MS);
    return () => clearTimeout(t);
  }, [refreshNote, loadItems]);

  const handleToggleSelect = useCallback((permalink: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(permalink)) next.delete(permalink);
      else next.add(permalink);
      return next;
    });
  }, []);

  const handleOpenOnIG = useCallback((item: DiscoveryItem) => {
    // window.open instead of <a target=_blank> so the same UX works from
    // a button click (the card has its own selection click area).
    window.open(item.permalink, "_blank", "noopener,noreferrer");
  }, []);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    setRefreshNote(null);
    try {
      const r = await api.discovery.refresh();
      if (!r.queued) {
        setRefreshNote(r.detail ?? "Nothing to refresh.");
      } else {
        setRefreshNote(`Refresh queued for ${r.page_count} pages…`);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        const retry =
          (e.body as { detail?: { retry_after?: number } })?.detail
            ?.retry_after ?? 60;
        setRefreshNote(`Rate limited — try again in ${retry}s.`);
      } else {
        setRefreshNote(
          e instanceof Error ? e.message : "Refresh failed.",
        );
      }
    }
    setRefreshing(false);
  }, []);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[#e6edf3]">Sources</h1>
          <p className="text-sm text-[#484f58] mt-1">
            Recent reels from your reference pages, ranked by your filter.
          </p>
        </div>
        {selected.size > 0 && (
          <div
            className="text-xs text-[#7d8590]"
            data-testid="sources-selection-count"
          >
            <span className="text-[#e6edf3] font-medium">{selected.size}</span>{" "}
            selected
          </div>
        )}
      </header>

      <SourcesFilterBar
        onChange={() => loadItems()}
        onRefresh={handleRefresh}
        refreshing={refreshing}
        refreshNote={refreshNote}
      />

      {loading ? (
        <div className="py-12 text-center text-xs text-[#484f58]">Loading…</div>
      ) : error ? (
        <Card>
          <p
            role="alert"
            data-testid="sources-error"
            className="text-xs text-[#f85149]"
          >
            {error}
          </p>
        </Card>
      ) : !hasCache ? (
        <Card>
          <div
            className="py-8 text-center space-y-2"
            data-testid="sources-empty-no-cache"
          >
            <p className="text-sm text-[#e6edf3]">No reels cached yet.</p>
            <p className="text-xs text-[#484f58]">
              Add reference pages in{" "}
              <Link href="/settings" className="text-[#58a6ff] hover:underline">
                Settings
              </Link>
              , then click Refresh.
            </p>
          </div>
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <div
            className="py-8 text-center space-y-2"
            data-testid="sources-empty-filter"
          >
            <p className="text-sm text-[#e6edf3]">
              No reels match your current filter.
            </p>
            <p className="text-xs text-[#484f58]">
              Loosen the filter or click Refresh to fetch new content.
            </p>
          </div>
        </Card>
      ) : (
        <>
          <p className="text-xs text-[#7d8590]" data-testid="sources-total">
            <span className="text-[#e6edf3] font-medium">
              {total.toLocaleString()}
            </span>{" "}
            matching reels
          </p>
          <SourcesGrid
            items={items}
            selectedPermalinks={selected}
            onToggleSelect={handleToggleSelect}
            onOpenOnIG={handleOpenOnIG}
            // Download + Find Similar wiring lands in Tasks 1.5 and 1.6.
            // Leaving the props off renders the buttons disabled with a
            // tooltip rather than firing a half-built backend.
          />
        </>
      )}
    </div>
  );
}
