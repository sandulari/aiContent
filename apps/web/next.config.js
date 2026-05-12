/** @type {import('next').NextConfig} */

// Task 2.6 — Content-Security-Policy for the Next.js frontend.
//
// Looser than the API's `default-src 'none'` because the browser
// needs to fetch + execute the bundle, render images from IG/CDNs,
// call our API via XHR, etc. Every directive is the minimum needed:
//
//   - script-src 'self' 'unsafe-inline' 'unsafe-eval' — Next inlines
//     the runtime bootstrap script and uses eval in dev for HMR. The
//     right long-term fix is a per-request nonce via middleware
//     (FOUND-ISSUES #9). For now the wider allowance is documented
//     and bounded to 'self'.
//   - style-src 'self' 'unsafe-inline' — Tailwind compiles utility
//     classes that some components inject inline.
//   - img-src 'self' data: blob: https: — IG thumbnails / OAuth
//     avatars come from arbitrary CDN hosts.
//   - connect-src includes NEXT_PUBLIC_API_URL so the frontend can
//     XHR to the API. Falls back to localhost dev.
//   - frame-ancestors 'none' — the frontend itself is never iframed.
//   - base-uri / form-action 'self' — defense against <base>
//     hijacking and form-action redirection attacks.

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const CSP = [
  `default-src 'self'`,
  `script-src 'self' 'unsafe-inline' 'unsafe-eval'`,
  `style-src 'self' 'unsafe-inline'`,
  `img-src 'self' data: blob: https:`,
  `font-src 'self' data:`,
  `connect-src 'self' ${API_URL}`,
  `frame-ancestors 'none'`,
  `base-uri 'self'`,
  `form-action 'self'`,
  `object-src 'none'`,
].join('; ');

const nextConfig = {
  output: "standalone",
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'Content-Security-Policy', value: CSP },
          { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-XSS-Protection', value: '1; mode=block' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=(), payment=(), usb=()' },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
