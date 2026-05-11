/**
 * SourcesCard — rendering, selection toggle, and the four spec actions.
 *
 * One snapshot pair (selected + unselected) covers the visual state per the
 * Task 1.4 spec. Interaction tests cover the click handlers + the
 * disabled-when-handler-missing behavior for Download / Find Similar
 * (those wire up in Tasks 1.5 / 1.6).
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SourcesCard } from "@/components/sources/sourcesCard";
import type { DiscoveryItem } from "@/lib/api";

const baseItem: DiscoveryItem = {
  source_handle: "natgeo",
  permalink: "https://www.instagram.com/reel/Caa/",
  media_url: null,
  thumbnail: "https://cdn/x.jpg",
  caption: "wild test caption",
  views: 12345,
  likes: 678,
  comments: 9,
  posted_at: "2026-05-01T00:00:00Z",
  duration_seconds: 30,
  score: 12345,
};

describe("SourcesCard", () => {
  it("snapshot: unselected vs selected", () => {
    const { container: unsel } = render(
      <SourcesCard
        item={baseItem}
        selected={false}
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
      />,
    );
    expect(unsel.firstChild).toMatchSnapshot("sources-card-unselected");

    const { container: sel } = render(
      <SourcesCard
        item={baseItem}
        selected={true}
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
      />,
    );
    expect(sel.firstChild).toMatchSnapshot("sources-card-selected");
  });

  it("renders stats in compact form and the caption", () => {
    render(
      <SourcesCard
        item={baseItem}
        selected={false}
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
      />,
    );
    // 12345 -> "12.3K"
    expect(
      screen.getByTestId(`source-views-${baseItem.permalink}`),
    ).toHaveTextContent(/12\.3K/);
    expect(screen.getByText(/wild test caption/)).toBeInTheDocument();
  });

  it("toggles selection via the corner button", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();

    render(
      <SourcesCard
        item={baseItem}
        selected={false}
        onToggleSelect={onToggle}
        onOpenOnIG={() => {}}
      />,
    );
    await user.click(screen.getByTestId(`source-select-${baseItem.permalink}`));
    expect(onToggle).toHaveBeenCalledWith(baseItem.permalink);
  });

  it("reflects the selected state on data-selected for downstream styling", () => {
    render(
      <SourcesCard
        item={baseItem}
        selected
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
      />,
    );
    expect(
      screen.getByTestId(`source-card-${baseItem.permalink}`),
    ).toHaveAttribute("data-selected", "true");
  });

  it("aria-pressed mirrors selected state on the toggle", () => {
    const { rerender } = render(
      <SourcesCard
        item={baseItem}
        selected={false}
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
      />,
    );
    expect(
      screen.getByTestId(`source-select-${baseItem.permalink}`),
    ).toHaveAttribute("aria-pressed", "false");

    rerender(
      <SourcesCard
        item={baseItem}
        selected
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
      />,
    );
    expect(
      screen.getByTestId(`source-select-${baseItem.permalink}`),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("Open on IG button calls onOpenOnIG with the item", async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();

    render(
      <SourcesCard
        item={baseItem}
        selected={false}
        onToggleSelect={() => {}}
        onOpenOnIG={onOpen}
      />,
    );
    await user.click(screen.getByTestId(`source-open-ig-${baseItem.permalink}`));
    expect(onOpen).toHaveBeenCalledWith(baseItem);
  });

  it("Download button is disabled when onDownload is not provided", () => {
    render(
      <SourcesCard
        item={baseItem}
        selected={false}
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
        // onDownload intentionally omitted (Task 1.5 not landed)
      />,
    );
    expect(
      screen.getByTestId(`source-download-${baseItem.permalink}`),
    ).toBeDisabled();
  });

  it("Find Similar button is disabled when onFindSimilar is not provided", () => {
    render(
      <SourcesCard
        item={baseItem}
        selected={false}
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
        // onFindSimilar intentionally omitted (Task 1.6 not landed)
      />,
    );
    expect(
      screen.getByTestId(`source-similar-${baseItem.permalink}`),
    ).toBeDisabled();
  });

  it("Download button fires its handler when provided", async () => {
    const onDownload = vi.fn();
    const user = userEvent.setup();
    render(
      <SourcesCard
        item={baseItem}
        selected={false}
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
        onDownload={onDownload}
      />,
    );
    await user.click(
      screen.getByTestId(`source-download-${baseItem.permalink}`),
    );
    expect(onDownload).toHaveBeenCalledWith(baseItem);
  });
});
