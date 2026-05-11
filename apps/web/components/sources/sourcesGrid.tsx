"use client";

import type { DiscoveryItem, DownloadStatus } from "@/lib/api";

import { SourcesCard } from "./sourcesCard";

interface SourcesGridProps {
  items: DiscoveryItem[];
  selectedPermalinks: Set<string>;
  onToggleSelect: (permalink: string) => void;
  onOpenOnIG: (item: DiscoveryItem) => void;
  onDownload?: (item: DiscoveryItem) => void;
  onFindSimilar?: (item: DiscoveryItem) => void;
  /** Map of reference_reel_id -> current DownloadStatus. */
  downloadStatuses?: Map<string, DownloadStatus>;
}

/**
 * Grid layout for discovery cards. Responsive: 2 columns on narrow,
 * 3 on medium, 4+ on wide. Empty state handling lives in the page —
 * this component just renders what it's given.
 */
export function SourcesGrid({
  items,
  selectedPermalinks,
  onToggleSelect,
  onOpenOnIG,
  onDownload,
  onFindSimilar,
  downloadStatuses,
}: SourcesGridProps) {
  return (
    <div
      className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
      data-testid="sources-grid"
    >
      {items.map((item) => (
        <SourcesCard
          key={item.permalink}
          item={item}
          selected={selectedPermalinks.has(item.permalink)}
          onToggleSelect={onToggleSelect}
          onOpenOnIG={onOpenOnIG}
          onDownload={onDownload}
          onFindSimilar={onFindSimilar}
          downloadStatus={item.id ? downloadStatuses?.get(item.id) ?? null : null}
        />
      ))}
    </div>
  );
}
