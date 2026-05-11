"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { Card } from "@/components/ui/card";
import { SourcesFilterBar } from "@/components/sources/sourcesFilterBar";
import { SourcesGrid } from "@/components/sources/sourcesGrid";
import {
  ApiError,
  api,
  type DiscoveryItem,
  type Download,
  type DownloadStatus,
  type SimilarResponse,
} from "@/lib/api";

const REFRESH_REFETCH_MS = 6000;
const DOWNLOAD_POLL_MS = 3000;

function isTerminalStatus(s: DownloadStatus): boolean {
  return s === "done" || s === "failed";
}

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
  // Map reference_reel_id -> latest Download row. Drives the card's
  // Download button label/disable state and the polling loop below.
  const [downloads, setDownloads] = useState<Map<string, Download>>(new Map());
  // When non-null, the page renders the off-IG similar view instead of
  // the main feed. ``sourceItem`` is the IG reel the user clicked Find
  // Similar on; ``response`` is the API payload.
  const [similar, setSimilar] = useState<
    | { sourceItem: DiscoveryItem; response: SimilarResponse | null; loading: boolean }
    | null
  >(null);

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

  const handleDownload = useCallback(async (item: DiscoveryItem) => {
    if (!item.id) return; // Cache miss — nothing to download against
    try {
      const dl = await api.discovery.download(item.id);
      setDownloads((prev) => {
        const next = new Map(prev);
        next.set(dl.reference_reel_id, dl);
        return next;
      });
    } catch (e: any) {
      setError(e?.message ?? "Download failed to start");
    }
  }, []);

  const handleFindSimilar = useCallback(async (item: DiscoveryItem) => {
    if (!item.id) return;
    setSimilar({ sourceItem: item, response: null, loading: true });
    try {
      const resp = await api.discovery.findSimilar(item.id);
      setSimilar({ sourceItem: item, response: resp, loading: false });
    } catch (e: any) {
      setSimilar({
        sourceItem: item,
        response: {
          items: [],
          source: { handle: item.source_handle, permalink: item.permalink },
          query: "",
          error: e?.message ?? "Find similar failed",
        },
        loading: false,
      });
    }
  }, []);

  const exitSimilar = useCallback(() => setSimilar(null), []);

  // Poll non-terminal downloads every few seconds. Stops automatically
  // when every tracked download reaches done|failed.
  useEffect(() => {
    const inFlight = Array.from(downloads.values()).filter(
      (d) => !isTerminalStatus(d.status),
    );
    if (inFlight.length === 0) return;

    let cancelled = false;
    const t = setInterval(async () => {
      const results = await Promise.allSettled(
        inFlight.map((d) => api.discovery.downloadStatus(d.id)),
      );
      if (cancelled) return;
      setDownloads((prev) => {
        const next = new Map(prev);
        for (const r of results) {
          if (r.status === "fulfilled") {
            next.set(r.value.reference_reel_id, r.value);
          }
        }
        return next;
      });
    }, DOWNLOAD_POLL_MS);

    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [downloads]);

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

  // Similar mode renders a different surface: source banner + grid of
  // off-IG (TikTok) items. Reuses SourcesGrid so the card components
  // stay shared between the two modes.
  if (similar) {
    const errKey = similar.response?.error;
    return (
      <div className="p-8 max-w-7xl mx-auto space-y-6" data-testid="sources-similar-view">
        <header className="flex items-center justify-between gap-4">
          <div>
            <button
              onClick={exitSimilar}
              data-testid="sources-similar-back"
              className="text-xs text-[#58a6ff] hover:underline"
            >
              ← Back to feed
            </button>
            <h1 className="text-xl font-semibold text-[#e6edf3] mt-1">
              Similar elsewhere
            </h1>
            <p className="text-sm text-[#484f58] mt-1">
              TikTok results similar to{" "}
              <a
                href={similar.sourceItem.permalink}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#58a6ff] hover:underline"
              >
                @{similar.sourceItem.source_handle}'s reel
              </a>
              .
            </p>
          </div>
        </header>

        {similar.loading ? (
          <div className="py-12 text-center text-xs text-[#484f58]">Loading…</div>
        ) : errKey ? (
          <Card>
            <p className="text-xs text-[#7d8590]" data-testid="sources-similar-error">
              {errKey === "rate_limit"
                ? "Too many similar-content lookups. Try again later."
                : errKey === "no_query"
                ? "This reel has no hashtags or keywords to search by."
                : errKey === "timeout"
                ? "TikTok search timed out. Try again."
                : `TikTok search failed (${errKey}).`}
            </p>
          </Card>
        ) : similar.response && similar.response.items.length === 0 ? (
          <Card>
            <p className="text-xs text-[#484f58] text-center py-6">
              No similar content found for "{similar.response.query}".
            </p>
          </Card>
        ) : (
          similar.response && (
            <>
              <p className="text-xs text-[#7d8590]">
                Searched TikTok for{" "}
                <span className="text-[#e6edf3] font-medium">
                  "{similar.response.query}"
                </span>
              </p>
              <SourcesGrid
                items={similar.response.items}
                selectedPermalinks={selected}
                onToggleSelect={handleToggleSelect}
                onOpenOnIG={handleOpenOnIG}
                // Download targets reference_reels.id — TikTok items
                // aren't cached there, so the button stays disabled.
                // Find Similar is also omitted (no recursive search).
              />
            </>
          )
        )}
      </div>
    );
  }

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
            onDownload={handleDownload}
            onFindSimilar={handleFindSimilar}
            downloadStatuses={
              new Map(
                Array.from(downloads.entries()).map(([k, v]) => [k, v.status]),
              )
            }
          />
        </>
      )}
    </div>
  );
}
