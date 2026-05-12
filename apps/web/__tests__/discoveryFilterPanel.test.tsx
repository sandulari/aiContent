/**
 * DiscoveryFilterPanel — load + edit + debounced preview + save.
 *
 * The api module is mocked module-wide so the debounced preview call is
 * observable. Real timers are used for the load assertions, then swapped
 * for fake timers in the preview-debounce test so we can advance past the
 * debounce window without sleeping.
 */
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DiscoveryFilterPanel } from "@/components/settings/discoveryFilterPanel";

vi.mock("@/lib/api", () => ({
  api: {
    discoveryFilter: {
      get: vi.fn(),
      save: vi.fn(),
      preview: vi.fn(),
    },
  },
}));

import { api } from "@/lib/api";

const filterApi = api.discoveryFilter as {
  get: Mock;
  save: Mock;
  preview: Mock;
};

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

beforeEach(() => {
  filterApi.get.mockReset();
  filterApi.save.mockReset();
  filterApi.preview.mockReset();
  // Default to "no cache" so tests that don't override see the empty state.
  filterApi.preview.mockResolvedValue({ count: 0, has_cache: false });
});

describe("DiscoveryFilterPanel", () => {
  it("loads + populates fields from the server response", async () => {
    filterApi.get.mockResolvedValue({
      ...defaultFilter,
      min_views: 5000,
      sort_by: "engagement_desc",
      is_default: false,
      updated_at: "2026-05-12T12:00:00Z",
    });

    render(<DiscoveryFilterPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("filter-min-views")).toHaveValue(5000);
    });
    expect(screen.getByTestId("filter-min-likes")).toHaveValue(10);
    expect(screen.getByTestId("filter-max-age")).toHaveValue(60);
  });

  it("renders the empty-cache explainer until /preview reports has_cache=true", async () => {
    filterApi.get.mockResolvedValue(defaultFilter);

    render(<DiscoveryFilterPanel />);

    await waitFor(() => expect(filterApi.get).toHaveBeenCalled());

    // Eventually the preview debounce fires with the loaded values.
    await waitFor(() => {
      expect(filterApi.preview).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByTestId("filter-preview")).toHaveTextContent(
        /no reels cached yet/i,
      );
    });
  });

  it("renders the live match count when /preview reports has_cache=true", async () => {
    filterApi.get.mockResolvedValue(defaultFilter);
    filterApi.preview.mockResolvedValue({ count: 42, has_cache: true });

    render(<DiscoveryFilterPanel />);

    await waitFor(() => expect(filterApi.preview).toHaveBeenCalled());
    await waitFor(() => {
      expect(screen.getByTestId("filter-preview")).toHaveTextContent(/42/);
      expect(screen.getByTestId("filter-preview")).toHaveTextContent(/reels match/i);
    });
  });

  it("Save button is disabled when the form matches what was loaded, enabled after a change", async () => {
    filterApi.get.mockResolvedValue({ ...defaultFilter, is_default: false });
    const user = userEvent.setup();

    render(<DiscoveryFilterPanel />);
    await waitFor(() => expect(filterApi.get).toHaveBeenCalled());

    const save = screen.getByTestId("filter-save");
    // Initial render with the saved values — not dirty, so button is disabled.
    await waitFor(() => expect(save).toBeDisabled());

    const minViews = screen.getByTestId("filter-min-views");
    await user.clear(minViews);
    await user.type(minViews, "2500");

    await waitFor(() => expect(save).not.toBeDisabled());
  });

  it("sends the current draft to api.discoveryFilter.save on click", async () => {
    filterApi.get.mockResolvedValue({ ...defaultFilter, is_default: false });
    filterApi.save.mockResolvedValue({
      ...defaultFilter,
      min_views: 2500,
      is_default: false,
      updated_at: "2026-05-12T13:00:00Z",
    });
    const user = userEvent.setup();

    render(<DiscoveryFilterPanel />);
    await waitFor(() => expect(filterApi.get).toHaveBeenCalled());

    const minViews = screen.getByTestId("filter-min-views");
    await user.clear(minViews);
    await user.type(minViews, "2500");

    await user.click(screen.getByTestId("filter-save"));

    await waitFor(() => {
      expect(filterApi.save).toHaveBeenCalledWith(
        expect.objectContaining({ min_views: 2500 }),
      );
    });
    // After save, the button reverts to "Saved" (disabled) because draft now matches saved.
    await waitFor(() =>
      expect(screen.getByTestId("filter-save")).toBeDisabled(),
    );
  });

  it("re-fires /preview after a field change", async () => {
    filterApi.get.mockResolvedValue(defaultFilter);
    const user = userEvent.setup();

    render(<DiscoveryFilterPanel />);
    // Initial load preview happens once on mount.
    await waitFor(() => expect(filterApi.preview).toHaveBeenCalled());
    filterApi.preview.mockClear();

    const minViews = screen.getByTestId("filter-min-views");
    await user.clear(minViews);
    await user.type(minViews, "9000");

    // After the debounce window, preview re-fires with the new value.
    await waitFor(() => {
      expect(filterApi.preview).toHaveBeenCalledWith(
        expect.objectContaining({ min_views: 9000 }),
      );
    });
  });
});
