/**
 * Frontend XSS sanitization (Task 2.3).
 *
 * Verifies that {@link sanitizeHtml} keeps allow-listed inline markup
 * but strips everything dangerous (script tags, event-handler attrs,
 * `javascript:` URIs). {@link stripHtml} returns plain text.
 */
import { describe, expect, it } from "vitest";

import { sanitizeHtml, stripHtml } from "@/lib/sanitize";

describe("sanitizeHtml", () => {
  it("strips <script> tags entirely", () => {
    const out = sanitizeHtml("<p>hello</p><script>alert(1)</script>");
    expect(out).toContain("<p>hello</p>");
    expect(out).not.toContain("<script>");
    expect(out).not.toContain("alert(1)");
  });

  it("strips event-handler attributes", () => {
    const out = sanitizeHtml('<a href="x" onclick="alert(1)">click</a>');
    expect(out).toContain("href=");
    expect(out).not.toContain("onclick");
  });

  it("strips javascript: URIs in href", () => {
    const out = sanitizeHtml('<a href="javascript:alert(1)">x</a>');
    expect(out).not.toContain("javascript:");
  });

  it("preserves allow-listed inline tags", () => {
    const out = sanitizeHtml("<b>bold</b> and <i>italic</i>");
    expect(out).toContain("<b>bold</b>");
    expect(out).toContain("<i>italic</i>");
  });

  it("returns empty string for null/undefined/empty", () => {
    expect(sanitizeHtml(null)).toBe("");
    expect(sanitizeHtml(undefined)).toBe("");
    expect(sanitizeHtml("")).toBe("");
  });
});

describe("stripHtml", () => {
  it("removes all tags", () => {
    expect(stripHtml("<b>hello</b> <i>world</i>")).toBe("hello world");
  });

  it("removes script content", () => {
    expect(stripHtml("<script>alert(1)</script>safe")).not.toContain("alert(1)");
  });

  it("returns empty for nullish", () => {
    expect(stripHtml(null)).toBe("");
    expect(stripHtml(undefined)).toBe("");
  });
});
