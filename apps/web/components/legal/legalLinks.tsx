import clsx from "clsx";

/**
 * Legal links shown at the foot of every public page (auth, onboarding)
 * and in the app sidebar. The content engine has no legal pages of its
 * own, so every link points at the main Shadow Pages site.
 */
const LEGAL_BASE = "https://start.shadowpages.io";

export const LEGAL_URLS = {
  terms: `${LEGAL_BASE}/terms`,
  privacy: `${LEGAL_BASE}/privacy`,
  cookies: `${LEGAL_BASE}/cookies`,
  disclaimer: `${LEGAL_BASE}/disclaimer`,
  refund: `${LEGAL_BASE}/refund`,
  impressum: `${LEGAL_BASE}/impressum`,
} as const;

const LINKS: { label: string; href: string }[] = [
  { label: "Terms", href: LEGAL_URLS.terms },
  { label: "Privacy", href: LEGAL_URLS.privacy },
  { label: "Cookies", href: LEGAL_URLS.cookies },
  { label: "Earnings Disclaimer", href: LEGAL_URLS.disclaimer },
  { label: "Refund Policy", href: LEGAL_URLS.refund },
  { label: "Impressum", href: LEGAL_URLS.impressum },
];

export function LegalLinks({
  className,
  compact = false,
}: {
  className?: string;
  /** Sidebar variant: smaller type, left-aligned, no copyright line. */
  compact?: boolean;
}) {
  return (
    <nav aria-label="Legal" className={clsx(compact ? "text-left" : "text-center", className)}>
      <ul
        className={clsx(
          "flex flex-wrap gap-y-1",
          compact ? "gap-x-3 text-[10px]" : "justify-center gap-x-4 text-[11px]",
        )}
      >
        {LINKS.map((l) => (
          <li key={l.label}>
            <a
              href={l.href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#484f58] hover:text-[#c9d1d9] transition-colors duration-150"
            >
              {l.label}
            </a>
          </li>
        ))}
      </ul>
      {!compact && (
        <p className="mt-2 text-[11px] text-[#333]">
          © {new Date().getFullYear()} Ares Online S.R.L., trading as Shadow Pages
        </p>
      )}
    </nav>
  );
}
