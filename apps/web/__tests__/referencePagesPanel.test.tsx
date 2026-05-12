/**
 * Component tests for ReferencePagesPanel — exercises load, add, idempotent
 * re-add (via mocked api), cap-at-5 disable state, and remove. The api
 * client is mocked module-wide so we test the component in isolation.
 */
import { describe, expect, it, vi, beforeEach, type Mock } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ReferencePagesPanel } from "@/components/settings/referencePagesPanel";

// Replace the lib/api module with a mock so the panel's network calls are
// observable + scriptable per test.
vi.mock("@/lib/api", () => ({
  api: {
    referencePages: {
      list: vi.fn(),
      add: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

import { api } from "@/lib/api";

const refApi = api.referencePages as {
  list: Mock;
  add: Mock;
  remove: Mock;
};

const buildPage = (handle: string, id = `id-${handle}`) => ({
  id,
  ig_handle: handle,
  ig_user_id: null,
  ig_display_name: null,
  ig_profile_pic_url: null,
  added_at: "2026-05-12T00:00:00Z",
});

beforeEach(() => {
  refApi.list.mockReset();
  refApi.add.mockReset();
  refApi.remove.mockReset();
});

describe("ReferencePagesPanel", () => {
  it("renders an empty state when the server has no reference pages", async () => {
    refApi.list.mockResolvedValue({ items: [], count: 0, max: 5 });

    render(<ReferencePagesPanel />);

    await waitFor(() => {
      expect(screen.getByText(/no reference pages yet/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/0 \/ 5/)).toBeInTheDocument();
  });

  it("adds a page and prepends it to the list", async () => {
    refApi.list.mockResolvedValue({ items: [], count: 0, max: 5 });
    refApi.add.mockResolvedValue(buildPage("natgeo"));

    render(<ReferencePagesPanel />);
    await waitFor(() => expect(refApi.list).toHaveBeenCalled());

    const input = screen.getByTestId("ref-handle-input") as HTMLInputElement;
    await userEvent.type(input, "natgeo");
    await userEvent.click(screen.getByTestId("ref-add-button"));

    await waitFor(() => {
      expect(screen.getByTestId("ref-item-natgeo")).toBeInTheDocument();
    });
    expect(refApi.add).toHaveBeenCalledWith("natgeo");
    expect(input.value).toBe("");
  });

  it("does not duplicate an idempotent re-add (same id returned)", async () => {
    refApi.list.mockResolvedValue({ items: [], count: 0, max: 5 });
    refApi.add.mockResolvedValue(buildPage("natgeo"));

    render(<ReferencePagesPanel />);
    await waitFor(() => expect(refApi.list).toHaveBeenCalled());

    await userEvent.type(screen.getByTestId("ref-handle-input"), "natgeo");
    await userEvent.click(screen.getByTestId("ref-add-button"));
    await waitFor(() => screen.getByTestId("ref-item-natgeo"));

    // Re-add the same handle — server returns the same id.
    await userEvent.type(screen.getByTestId("ref-handle-input"), "natgeo");
    await userEvent.click(screen.getByTestId("ref-add-button"));

    await waitFor(() => {
      // Still only one card with this handle in the DOM.
      expect(screen.getAllByTestId("ref-item-natgeo")).toHaveLength(1);
    });
  });

  it("disables the input + button at the per-user cap", async () => {
    refApi.list.mockResolvedValue({
      items: ["a", "b", "c", "d", "e"].map((h) => buildPage(h)),
      count: 5,
      max: 5,
    });

    render(<ReferencePagesPanel />);

    await waitFor(() => {
      expect(screen.getByText(/5 \/ 5/)).toBeInTheDocument();
    });
    expect(screen.getByTestId("ref-handle-input")).toBeDisabled();
    const button = screen.getByTestId("ref-add-button");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/limit reached/i);
  });

  it("surfaces a server error inline on cap-exceeded add", async () => {
    refApi.list.mockResolvedValue({ items: [], count: 0, max: 5 });
    refApi.add.mockRejectedValue(
      new Error("At most 5 reference pages per user."),
    );

    render(<ReferencePagesPanel />);
    await waitFor(() => expect(refApi.list).toHaveBeenCalled());

    await userEvent.type(screen.getByTestId("ref-handle-input"), "ref6");
    await userEvent.click(screen.getByTestId("ref-add-button"));

    await waitFor(() => {
      expect(screen.getByTestId("ref-error")).toHaveTextContent(
        /at most 5/i,
      );
    });
  });

  it("removes a page when the row's Remove button is clicked", async () => {
    refApi.list.mockResolvedValue({
      items: [buildPage("natgeo"), buildPage("nasa")],
      count: 2,
      max: 5,
    });
    refApi.remove.mockResolvedValue(undefined);

    render(<ReferencePagesPanel />);

    await waitFor(() =>
      expect(screen.getByTestId("ref-item-natgeo")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByTestId("ref-remove-natgeo"));

    await waitFor(() => {
      expect(screen.queryByTestId("ref-item-natgeo")).not.toBeInTheDocument();
    });
    expect(refApi.remove).toHaveBeenCalledWith("id-natgeo");
    // Other rows remain.
    expect(screen.getByTestId("ref-item-nasa")).toBeInTheDocument();
  });
});
