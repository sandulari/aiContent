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
  id: "00000000-0000-0000-0000-000000000001",
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

  // Task 1.5 — download status reflects on the button label + disabled state
  it.each([
    ["queued", "Downloading", true],
    ["downloading", "Downloading", true],
    ["done", "Downloaded", true],
    ["failed", "Retry", false],
  ] as const)(
    "downloadStatus=%s without onEdit -> label '%s' / disabled=%s",
    (statusValue, expectedLabel, expectedDisabled) => {
      render(
        <SourcesCard
          item={baseItem}
          selected={false}
          onToggleSelect={() => {}}
          onOpenOnIG={() => {}}
          onDownload={() => {}}
          downloadStatus={statusValue}
        />,
      );
      const btn = screen.getByTestId(`source-download-${baseItem.permalink}`);
      expect(btn).toHaveTextContent(expectedLabel);
      if (expectedDisabled) {
        expect(btn).toBeDisabled();
      } else {
        expect(btn).not.toBeDisabled();
      }
    },
  );

  // Task 1.7 — done + onEdit -> button morphs to "Edit" and fires onEdit
  it("downloadStatus=done with onEdit -> label 'Edit', enabled, fires onEdit", async () => {
    const onEdit = vi.fn();
    const onDownload = vi.fn();
    const user = userEvent.setup();
    render(
      <SourcesCard
        item={baseItem}
        selected={false}
        onToggleSelect={() => {}}
        onOpenOnIG={() => {}}
        onDownload={onDownload}
        onEdit={onEdit}
        downloadStatus="done"
      />,
    );
    const btn = screen.getByTestId(`source-download-${baseItem.permalink}`);
    expect(btn).toHaveTextContent("Edit");
    expect(btn).not.toBeDisabled();

    await user.click(btn);
    expect(onEdit).toHaveBeenCalledWith(baseItem);
    // The button no longer dispatches to onDownload once status is done.
    expect(onDownload).not.toHaveBeenCalled();
  });
});
