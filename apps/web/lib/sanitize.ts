/**
 * Frontend XSS sanitization helpers (Task 2.3).
 *
 * React's default JSX interpolation escapes text content, so
 * `<div>{userInput}</div>` is already XSS-safe. These helpers are for
 * the two cases where the default escaping doesn't apply:
 *
 *   1. `dangerouslySetInnerHTML` — anywhere we *intentionally* render
 *      HTML (rich-text captions in the future, AI-generated markdown
 *      preview, etc.) MUST pass through {@link sanitizeHtml} first.
 *
 *   2. Stripping markup from a string before passing it to a non-React
 *      sink (e.g. a window.alert, a clipboard write, a logged message).
 *      Use {@link stripHtml}.
 *
 * Wraps `isomorphic-dompurify` so both SSR and CSR work — the package
 * detects the runtime and falls back to a Node-side JSDOM
 * implementation when `window` is missing.
 *
 * Allow-list: by default, only the inline tags + minimal block tags
 * needed for content captions. NO script, style, iframe, on*-handlers,
 * data: URIs, or javascript: URIs survive sanitization.
 */
import DOMPurify from "isomorphic-dompurify";

const _ALLOWED_TAGS = ["b", "i", "em", "strong", "a", "p", "br", "ul", "ol", "li"];
const _ALLOWED_ATTR = ["href", "title", "rel", "target"];

/**
 * Sanitize an HTML string for safe rendering via
 * `dangerouslySetInnerHTML`. Strips script tags, event-handler
 * attributes, and protocol handlers like `javascript:`.
 *
 * @example
 * <div dangerouslySetInnerHTML={{ __html: sanitizeHtml(richText) }} />
 */
export function sanitizeHtml(input: string | null | undefined): string {
  if (!input) return "";
  return DOMPurify.sanitize(String(input), {
    ALLOWED_TAGS: _ALLOWED_TAGS,
    ALLOWED_ATTR: _ALLOWED_ATTR,
    ALLOW_DATA_ATTR: false,
  });
}

/**
 * Strip ALL HTML tags from a string and return plain text. Used for
 * non-React sinks (window.alert, clipboard, log messages) where there
 * is no automatic escaping. Cheap fallback when you want text-only.
 */
export function stripHtml(input: string | null | undefined): string {
  if (!input) return "";
  return DOMPurify.sanitize(String(input), { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
}
