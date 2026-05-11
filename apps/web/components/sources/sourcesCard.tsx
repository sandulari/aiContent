"use client";

import clsx from "clsx";

import { Button } from "@/components/ui/button";
import type { DiscoveryItem, DownloadStatus } from "@/lib/api";

interface SourcesCardProps {
  item: DiscoveryItem;
  selected: boolean;
  onToggleSelect: (permalink: string) => void;
  onOpenOnIG: (item: DiscoveryItem) => void;
  onDownload?: (item: DiscoveryItem) => void;
  onFindSimilar?: (item: DiscoveryItem) => void;
  /** Current download status for this item, if any. Drives the Download
   * button's label + enabled state — Task 1.5. */
  downloadStatus?: DownloadStatus | null;
}

function downloadButtonLabel(status: DownloadStatus | null | undefined): string {
  if (status === "queued" || status === "downloading") return "Downloading…";
  if (status === "done") return "Downloaded";
  if (status === "failed") return "Retry";
  return "Download";
}

function downloadButtonDisabled(
  status: DownloadStatus | null | undefined,
  hasHandler: boolean,
): boolean {
  if (!hasHandler) return true; // Task 1.5 not wired by caller
  if (status === "queued" || status === "downloading" || status === "done") return true;
  return false;
}

function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

/**
 * One discovery feed card. Renders thumbnail + stats + four spec actions:
 * Select / Open on IG / Download / Find similar elsewhere. Download and
 * Find Similar are wired but disabled until their respective backend
 * tasks land (1.5, 1.6) — visible so the layout reflects the final UX,
 * disabled so we don't fire half-implemented requests.
 */
export function SourcesCard({
  item,
  selected,
  onToggleSelect,
  onOpenOnIG,
  onDownload,
  onFindSimilar,
  downloadStatus,
}: SourcesCardProps) {
  const downloadEnabled = onDownload !== undefined;
  const findSimilarEnabled = onFindSimilar !== undefined;
  const downloadDisabled = downloadButtonDisabled(downloadStatus, downloadEnabled);

  return (
    <article
      data-testid={`source-card-${item.permalink}`}
      data-selected={selected ? "true" : "false"}
      className={clsx(
        "rounded-lg border bg-[#161b22] transition-colors duration-150 overflow-hidden",
        selected
          ? "border-[#58a6ff] ring-1 ring-[#58a6ff]/40"
          : "border-[#21262d] hover:border-[#30363d]",
      )}
    >
      {/* Thumbnail */}
      <div className="relative aspect-[9/16] bg-[#0d1117]">
        {item.thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element — IG CDN
          // hosts these, Next.js Image would force us to allowlist their
          // wildcard subdomains in next.config.js.
          <img
            src={item.thumbnail}
            alt={item.caption ?? `Reel by @${item.source_handle}`}
            loading="lazy"
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[10px] text-[#484f58]">
            no thumbnail
          </div>
        )}

        {/* Select toggle — top-left, always visible */}
        <button
          type="button"
          aria-label={selected ? "Deselect" : "Select"}
          aria-pressed={selected}
          onClick={() => onToggleSelect(item.permalink)}
          data-testid={`source-select-${item.permalink}`}
          className={clsx(
            "absolute top-2 left-2 w-7 h-7 rounded-full flex items-center justify-center text-[12px] font-bold transition-colors",
            selected
              ? "bg-[#58a6ff] text-[#0d1117]"
              : "bg-[#0d1117]/80 text-[#7d8590] hover:text-[#e6edf3] border border-[#30363d]",
          )}
        >
          {selected ? "✓" : ""}
        </button>

        {/* Source handle — top-right */}
        <a
          href={`https://www.instagram.com/${item.source_handle}/`}
          target="_blank"
          rel="noopener noreferrer"
          className="absolute top-2 right-2 px-2 py-1 rounded bg-[#0d1117]/80 text-[10px] font-medium text-[#c9d1d9] hover:text-[#58a6ff] border border-[#30363d]"
        >
          @{item.source_handle}
        </a>
      </div>

      {/* Stats */}
      <div className="p-3 space-y-2">
        <div className="flex items-center gap-3 text-[11px] text-[#7d8590]">
          <span data-testid={`source-views-${item.permalink}`}>
            <span className="text-[#e6edf3] font-medium">
              {formatCompact(item.views)}
            </span>{" "}
            views
          </span>
          <span>
            <span className="text-[#e6edf3] font-medium">
              {formatCompact(item.likes)}
            </span>{" "}
            likes
          </span>
          <span>
            <span className="text-[#e6edf3] font-medium">
              {formatCompact(item.comments)}
            </span>{" "}
            comments
          </span>
        </div>

        {item.caption && (
          <p className="text-[11px] text-[#7d8590] line-clamp-2">
            {item.caption}
          </p>
        )}

        {/* Action row */}
        <div className="flex gap-2 pt-1">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onOpenOnIG(item)}
            data-testid={`source-open-ig-${item.permalink}`}
          >
            Open on IG
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={downloadDisabled}
            onClick={() => onDownload?.(item)}
            data-testid={`source-download-${item.permalink}`}
            title={
              downloadEnabled
                ? downloadStatus === "failed"
                  ? item.id
                    ? "Retry download"
                    : "Download"
                  : "Download"
                : "Download lands in Task 1.5"
            }
          >
            {downloadButtonLabel(downloadStatus)}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!findSimilarEnabled}
            onClick={() => onFindSimilar?.(item)}
            data-testid={`source-similar-${item.permalink}`}
            title={
              findSimilarEnabled
                ? "Find similar elsewhere"
                : "Find similar lands in Task 1.6"
            }
          >
            Find similar
          </Button>
        </div>
      </div>
    </article>
  );
}
