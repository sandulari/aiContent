/**
 * /sources page — load, render, select, refresh, and empty states.
 *
 * The api client is fully mocked so we can script every code path: empty
 * cache, filter-doesn't-match, refresh-queued + auto-refetch, refresh
 * rate-limited (429). Selection state is tested by clicking the corner
 * toggle and asserting the running count badge updates.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SourcesPage from "@/app/sources/page";
import type { DiscoveryItem, DiscoveryItemsResponse } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      discoveryFilter: {
        get: vi.fn(),
        save: vi.fn(),
        preview: vi.fn(),
      },
      discovery: {
        items: vi.fn(),
        refresh: vi.fn(),
        download: vi.fn(),
        downloadStatus: vi.fn(),
      },
    },
  };
});

import { api, ApiError } from "@/lib/api";

const dApi = api.discovery as {
  items: Mock;
  refresh: Mock;
  download: Mock;
  downloadStatus: Mock;
};
const fApi = api.discoveryFilter as { get: Mock; save: Mock; preview: Mock };

const mkItem = (suffix: string, overrides: Partial<DiscoveryItem> = {}): DiscoveryItem => ({
  id: `id-${suffix}`,
  source_handle: "natgeo",
  permalink: `https://www.instagram.com/reel/${suffix}/`,
  media_url: null,
  thumbnail: "https://cdn/x.jpg",
  caption: `caption ${suffix}`,
  views: 5000,
  likes: 100,
  comments: 10,
  posted_at: "2026-05-01T00:00:00Z",
  duration_seconds: 30,
  score: 5000,
  ...overrides,
});

const defaultFilter = {
  min_views: 1000,
  min_likes: 10,
  min_comments: 0,
  min_engagement_rate: 0.0,
  max_age_days: 60,
  sort_by: "views_desc" as const,
  updated_at: null,
  is_default: true,
};

const itemsResponse = (items: DiscoveryItem[], hasCache = true): DiscoveryItemsResponse => ({
  items,
  total: items.length,
  filter: {
    min_views: 1000,
    min_likes: 10,
    min_comments: 0,
    min_engagement_rate: 0.0,
    max_age_days: 60,
    sort_by: "views_desc",
  },
  has_cache: hasCache,
});

beforeEach(() => {
  dApi.items.mockReset();
  dApi.refresh.mockReset();
  dApi.download.mockReset();
  dApi.downloadStatus.mockReset();
  fApi.get.mockReset();
  fApi.save.mockReset();
  fApi.preview.mockReset();
  fApi.get.mockResolvedValue(defaultFilter);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("/sources page", () => {
  it("renders empty-no-cache when has_cache is false", async () => {
    dApi.items.mockResolvedValue(itemsResponse([], false));
    render(<SourcesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("sources-empty-no-cache")).toBeInTheDocument(),
    );
  });

  it("renders empty-filter when cache exists but no items match", async () => {
    dApi.items.mockResolvedValue(itemsResponse([], true));
    render(<SourcesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("sources-empty-filter")).toBeInTheDocument(),
    );
  });

  it("renders the grid + total when items come back", async () => {
    dApi.items.mockResolvedValue(itemsResponse([mkItem("Caa"), mkItem("Cbb")]));
    render(<SourcesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("sources-grid")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("sources-total")).toHaveTextContent("2");
  });

  it("selection toggle bumps the selection count badge", async () => {
    dApi.items.mockResolvedValue(itemsResponse([mkItem("Caa"), mkItem("Cbb")]));
    const user = userEvent.setup();
    render(<SourcesPage />);

    await waitFor(() =>
      expect(screen.getByTestId("sources-grid")).toBeInTheDocument(),
    );

    expect(screen.queryByTestId("sources-selection-count")).toBeNull();

    await user.click(
      screen.getByTestId("source-select-https://www.instagram.com/reel/Caa/"),
    );
    expect(
      screen.getByTestId("sources-selection-count"),
    ).toHaveTextContent("1");

    await user.click(
      screen.getByTestId("source-select-https://www.instagram.com/reel/Cbb/"),
    );
    expect(
      screen.getByTestId("sources-selection-count"),
    ).toHaveTextContent("2");

    // Toggling off lowers the count.
    await user.click(
      screen.getByTestId("source-select-https://www.instagram.com/reel/Caa/"),
    );
    expect(
      screen.getByTestId("sources-selection-count"),
    ).toHaveTextContent("1");
  });

  it("Open on IG opens window with the permalink", async () => {
    dApi.items.mockResolvedValue(itemsResponse([mkItem("Caa")]));
    const user = userEvent.setup();
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<SourcesPage />);
    await waitFor(() => screen.getByTestId("sources-grid"));

    await user.click(
      screen.getByTestId("source-open-ig-https://www.instagram.com/reel/Caa/"),
    );
    expect(openSpy).toHaveBeenCalledWith(
      "https://www.instagram.com/reel/Caa/",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("Refresh button shows queued note then auto-refetches after the timer", async () => {
    dApi.items
      .mockResolvedValueOnce(itemsResponse([])) // initial load — empty filter
      .mockResolvedValueOnce(itemsResponse([mkItem("Caa")])); // post-refresh
    dApi.refresh.mockResolvedValue({ queued: true, page_count: 2 });

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    vi.useFakeTimers({ shouldAdvanceTime: true });

    render(<SourcesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("sources-empty-filter")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("sources-refresh"));
    await waitFor(() =>
      expect(
        screen.getByTestId("sources-refresh-note"),
      ).toHaveTextContent(/refresh queued/i),
    );

    // Auto-refetch fires after 6 seconds.
    await act(async () => {
      vi.advanceTimersByTime(6500);
    });

    await waitFor(() => {
      expect(dApi.items).toHaveBeenCalledTimes(2);
    });
  });

  it("surfaces rate-limited refresh with retry_after", async () => {
    dApi.items.mockResolvedValue(itemsResponse([]));
    dApi.refresh.mockRejectedValue(
      new ApiError(429, "rate limited", {
        detail: { code: "rate_limit", retry_after: 42 },
      }),
    );

    const user = userEvent.setup();
    render(<SourcesPage />);
    await waitFor(() => screen.getByTestId("sources-empty-filter"));

    await user.click(screen.getByTestId("sources-refresh"));
    await waitFor(() => {
      expect(screen.getByTestId("sources-refresh-note")).toHaveTextContent(
        /rate limited.*42/i,
      );
    });
  });

  it("refresh with no reference pages shows the explainer note", async () => {
    dApi.items.mockResolvedValue(itemsResponse([], false));
    dApi.refresh.mockResolvedValue({
      queued: false,
      page_count: 0,
      detail: "No reference pages to refresh — add one first.",
    });
    const user = userEvent.setup();

    render(<SourcesPage />);
    await waitFor(() => screen.getByTestId("sources-empty-no-cache"));

    await user.click(screen.getByTestId("sources-refresh"));
    await waitFor(() =>
      expect(
        screen.getByTestId("sources-refresh-note"),
      ).toHaveTextContent(/add one first/i),
    );
  });

  // Task 1.5 — download click + status reflects in the button
  it("download click calls api.discovery.download and reflects the queued status", async () => {
    const item = mkItem("Cdl");
    dApi.items.mockResolvedValue(itemsResponse([item]));
    dApi.download.mockResolvedValue({
      id: "dl-1",
      reference_reel_id: "id-Cdl",
      status: "queued",
      minio_key: null,
      file_size_bytes: null,
      error_message: null,
      created_at: "2026-05-12T00:00:00Z",
      updated_at: "2026-05-12T00:00:00Z",
    });
    const user = userEvent.setup();

    render(<SourcesPage />);
    await waitFor(() => screen.getByTestId("sources-grid"));

    const btn = screen.getByTestId(`source-download-${item.permalink}`);
    expect(btn).toHaveTextContent("Download");
    expect(btn).not.toBeDisabled();

    await user.click(btn);
    expect(dApi.download).toHaveBeenCalledWith("id-Cdl");

    await waitFor(() =>
      expect(
        screen.getByTestId(`source-download-${item.permalink}`),
      ).toHaveTextContent("Downloading"),
    );
  });
});
