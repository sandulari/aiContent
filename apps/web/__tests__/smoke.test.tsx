/**
 * Smoke test — proves vitest + jsdom + RTL pick up our components and tsconfig
 * path alias `@/*` resolves. If this file ever stops passing, the runner is
 * broken regardless of any feature test.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Button } from "@/components/ui/button";

describe("test framework smoke", () => {
  it("renders a primary button with its children", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("shows a loading spinner when `loading` is true", () => {
    const { container } = render(<Button loading>Save</Button>);
    expect(container.querySelector("button")).toBeDisabled();
  });
});
