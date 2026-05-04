"use client";

import { Suspense, useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, IgStatus, ApiError } from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────

function humanizeErrorCode(code: string): string {
  return code
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Returns a relative time phrase and a severity level based on the diff.
 * severity: "ok" (>14d), "warn" (<=14d), "danger" (<=1d or expired).
 */
function formatRelative(iso: string | null): { label: string; severity: "ok" | "warn" | "danger" } {
  if (!iso) return { label: "unknown", severity: "warn" };

  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return { label: "unknown", severity: "warn" };

  const now = Date.now();
  const diffMs = target - now;
  const expired = diffMs < 0;
  const absMs = Math.abs(diffMs);

  const sec = Math.round(absMs / 1000);
  const min = Math.round(sec / 60);
  const hr = Math.round(min / 60);
  const day = Math.round(hr / 24);

  let phrase: string;
  if (sec < 60) phrase = `${sec} second${sec === 1 ? "" : "s"}`;
  else if (min < 60) phrase = `${min} minute${min === 1 ? "" : "s"}`;
  else if (hr < 48) phrase = `${hr} hour${hr === 1 ? "" : "s"}`;
  else phrase = `${day} day${day === 1 ? "" : "s"}`;

  const label = expired ? `expired ${phrase} ago` : `in ${phrase}`;

  let severity: "ok" | "warn" | "danger";
  if (expired) severity = "danger";
  else if (absMs <= 24 * 60 * 60 * 1000) severity = "danger";
  else if (absMs <= 14 * 24 * 60 * 60 * 1000) severity = "warn";
  else severity = "ok";

  return { label, severity };
}

function formatConnectedDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function isTokenExpired(iso: string | null): boolean {
  if (!iso) return false;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return false;
  return t < Date.now();
}

// ── Page ─────────────────────────────────────────────────────────────────

function InstagramSettingsInner() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [status, setStatus] = useState<IgStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Banner flags derived from URL params; dismissable via local state.
  const connectedFlag = searchParams?.get("connected");
  const errorCode = searchParams?.get("error");
  const [bannerDismissed, setBannerDismissed] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const s = await api.ig.status();
      setStatus(s);
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
          ? e.message
          : "Failed to load Instagram status.";
      setFetchError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Clear URL params after we've captured them once so a refresh doesn't re-show the banner.
  useEffect(() => {
    if ((connectedFlag || errorCode) && !bannerDismissed) {
      // leave them in place for the initial render, but strip on dismiss
    }
  }, [connectedFlag, errorCode, bannerDismissed]);

  const handleConnect = async () => {
    setStarting(true);
    setActionError(null);
    try {
      const res = await api.ig.start();
      if (!res?.authorize_url) {
        throw new Error("Missing authorize_url in response.");
      }
      window.location.href = res.authorize_url;
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
          ? e.message
          : "Could not start Instagram connection.";
      setActionError(msg);
      setStarting(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await api.ig.refresh();
      setActionSuccess(
        res?.expires_at
          ? `Token refreshed — now expires ${formatRelative(res.expires_at).label}.`
          : "Token refreshed."
      );
      await fetchStatus();
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
          ? e.message
          : "Failed to refresh token.";
      setActionError(msg);
    } finally {
      setRefreshing(false);
    }
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      await api.ig.disconnect();
      setConfirmOpen(false);
      setActionSuccess("Instagram disconnected.");
      await fetchStatus();
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
          ? e.message
          : "Failed to disconnect.";
      setActionError(msg);
    } finally {
      setDisconnecting(false);
    }
  };

  const dismissBanner = useCallback(() => {
    setBannerDismissed(true);
    router.replace("/settings/instagram");
  }, [router]);

  const successBanner = useMemo(() => {
    if (bannerDismissed) return null;
    if (connectedFlag !== "1") return null;
    const handle = status?.ig_username ? `@${status.ig_username}` : null;
    return (
      <div className="flex items-start gap-3 p-4 rounded-lg border border-[#238636]/40 bg-[#0a1a0a]">
        <div className="mt-0.5 w-4 h-4 rounded-full bg-[#3fb950] flex items-center justify-center flex-shrink-0">
          <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 20 20" fill="currentColor">
            <path
              fillRule="evenodd"
              d="M16.7 5.3a1 1 0 010 1.4l-8 8a1 1 0 01-1.4 0l-4-4a1 1 0 111.4-1.4L8 12.58l7.3-7.3a1 1 0 011.4 0z"
              clipRule="evenodd"
            />
          </svg>
        </div>
        <div className="flex-1 text-sm text-[#4ade80]">
          Instagram connected{handle ? ` — ${handle}` : ""}.
        </div>
        <button
          onClick={dismissBanner}
          className="text-[#3fb950] hover:text-[#4ade80] text-xs uppercase tracking-wider"
        >
          Dismiss
        </button>
      </div>
    );
  }, [bannerDismissed, connectedFlag, status?.ig_username, dismissBanner]);

  const errorBanner = useMemo(() => {
    if (bannerDismissed) return null;
    if (!errorCode) return null;

    const isPersonal = errorCode === "personal_account_not_supported";
    const isMissingScope = errorCode === "missing_publish_scope";
    let message: string;
    if (isPersonal) {
      message = "Your Instagram account is set to Personal. Publishing requires a Business or Creator account. Switch in the IG app: Settings → Account type and tools → Switch to professional account.";
    } else if (isMissingScope) {
      message = "Connection succeeded but you didn't grant the publish permission. Click \"Try again\" and make sure \"Create content\" is enabled on Instagram's consent screen.";
    } else {
      message = `${humanizeErrorCode(errorCode)}. Please try connecting again.`;
    }

    return (
      <div className="flex items-start gap-3 p-4 rounded-lg border border-[#f85149]/40 bg-[#1a0a0a]">
        <div className="mt-0.5 w-4 h-4 rounded-full bg-[#f85149] flex items-center justify-center flex-shrink-0">
          <span className="text-[10px] font-bold text-white leading-none">!</span>
        </div>
        <div className="flex-1 space-y-2">
          <div className="text-sm text-[#f87171]">{message}</div>
          {!isPersonal && (
            <Button size="sm" onClick={handleConnect} loading={starting}>
              Try again
            </Button>
          )}
        </div>
        <button
          onClick={dismissBanner}
          className="text-[#f85149] hover:text-[#f87171] text-xs uppercase tracking-wider"
        >
          Dismiss
        </button>
      </div>
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bannerDismissed, errorCode, starting, dismissBanner]);

  // ── Render states ──────────────────────────────────────────────────────

  const renderHeader = () => (
    <div>
      <h1 className="text-xl font-semibold text-[#e6edf3]">Instagram</h1>
      <p className="text-sm text-[#484f58] mt-1">
        Connect your Instagram Business or Creator account to publish reels directly from this app.
      </p>
    </div>
  );

  // Loading skeleton
  if (loading) {
    return (
      <div className="p-8 max-w-3xl mx-auto space-y-8">
        {renderHeader()}
        <Card>
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <div className="skeleton-shimmer w-14 h-14 rounded-full" />
              <div className="flex-1 space-y-2">
                <div className="skeleton-shimmer h-4 w-32 rounded" />
                <div className="skeleton-shimmer h-3 w-48 rounded" />
              </div>
            </div>
            <div className="flex gap-2 pt-2">
              <div className="skeleton-shimmer h-10 w-32 rounded-lg" />
              <div className="skeleton-shimmer h-10 w-28 rounded-lg" />
            </div>
          </div>
        </Card>
      </div>
    );
  }

  // Fetch error
  if (fetchError) {
    return (
      <div className="p-8 max-w-3xl mx-auto space-y-8">
        {renderHeader()}
        <div className="flex items-start gap-3 p-4 rounded-lg border border-[#f85149]/40 bg-[#1a0a0a]">
          <div className="mt-0.5 w-4 h-4 rounded-full bg-[#f85149] flex items-center justify-center flex-shrink-0">
            <span className="text-[10px] font-bold text-white leading-none">!</span>
          </div>
          <div className="flex-1 space-y-2">
            <div className="text-sm text-[#f87171]">
              Couldn’t load your Instagram connection status.
            </div>
            <div className="text-xs text-[#8b949e]">{fetchError}</div>
            <Button size="sm" variant="secondary" onClick={fetchStatus}>
              Retry
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const connected = !!status?.connected;
  const canPublish = !!status?.can_publish;
  const expired = isTokenExpired(status?.ig_token_expires_at || null);
  const accountType = (status?.ig_account_type || "").toUpperCase();
  const isPersonalType =
    accountType === "PERSONAL" ||
    accountType === "PERSONAL_ACCOUNT" ||
    (accountType !== "" &&
      accountType !== "BUSINESS" &&
      accountType !== "CREATOR" &&
      accountType !== "MEDIA_CREATOR");

  // ── NOT CONNECTED ──
  if (!connected) {
    return (
      <div className="p-8 max-w-3xl mx-auto space-y-8">
        {renderHeader()}
        {successBanner}
        {errorBanner}

        <Card>
          <div className="space-y-5">
            <div>
              <h2 className="text-sm font-medium text-[#e6edf3] mb-1.5">Connect Instagram</h2>
              <p className="text-xs text-[#8b949e] leading-relaxed">
                Authorize this app to publish reels on your behalf. We use Instagram’s official
                Graph API — your account stays in your control and you can disconnect at any time.
                Business or Creator accounts are required for publishing.
              </p>
            </div>

            <div>
              <Button
                onClick={handleConnect}
                loading={starting}
                className="!bg-[#2563eb] hover:!bg-[#1d4ed8] !text-white"
                size="lg"
              >
                {starting ? "Starting…" : "Connect Instagram"}
              </Button>
            </div>

            {actionError && (
              <p className="text-xs text-[#f85149]">{actionError}</p>
            )}
          </div>
        </Card>
      </div>
    );
  }

  // ── CONNECTED ──
  const expiry = formatRelative(status?.ig_token_expires_at || null);
  const expiryColor =
    expiry.severity === "ok"
      ? "text-[#3fb950]"
      : expiry.severity === "warn"
      ? "text-[#d29922]"
      : "text-[#f85149]";

  const accountTypeBadgeColor =
    accountType === "BUSINESS"
      ? "bg-[#0a1a2e] text-[#4a9eff]"
      : accountType === "CREATOR" || accountType === "MEDIA_CREATOR"
      ? "bg-[#150a1a] text-[#c084fc]"
      : "bg-[#1a0a0a] text-[#f87171]";

  const profileCard = (
    <div className="flex items-center gap-4">
      {status?.ig_profile_picture_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={status.ig_profile_picture_url}
          alt={status.ig_username ? `@${status.ig_username}` : "Instagram profile"}
          className="w-14 h-14 rounded-full object-cover border border-[#21262d] bg-[#0d1117]"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      ) : (
        <div className="w-14 h-14 rounded-full bg-[#0d1117] border border-[#21262d] flex items-center justify-center">
          <span className="text-lg font-semibold text-[#484f58]">
            {status?.ig_username ? status.ig_username.charAt(0).toUpperCase() : "?"}
          </span>
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-[#e6edf3] truncate">
            @{status?.ig_username ?? "unknown"}
          </span>
          {accountType && (
            <span
              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${accountTypeBadgeColor}`}
            >
              {accountType.replace(/_/g, " ")}
            </span>
          )}
        </div>
        <div className="text-[11px] text-[#484f58] mt-1">
          Connected on {formatConnectedDate(status?.ig_connected_at || null)}
        </div>
        <div className={`text-[11px] mt-0.5 ${expiryColor}`}>
          Token expires {expiry.label}
        </div>
      </div>
    </div>
  );

  const buttons = (
    <div className="flex gap-2">
      <Button variant="secondary" onClick={handleRefresh} loading={refreshing}>
        Refresh token
      </Button>
      <Button variant="danger" onClick={() => setConfirmOpen(true)}>
        Disconnect
      </Button>
    </div>
  );

  const confirmDialog = confirmOpen && (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={() => !disconnecting && setConfirmOpen(false)}
    >
      <div
        className="w-full max-w-sm bg-[#161b22] border border-[#21262d] rounded-lg p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <h3 className="text-sm font-semibold text-[#e6edf3]">Disconnect Instagram?</h3>
          <p className="text-xs text-[#8b949e] mt-1.5">
            You’ll need to reconnect before you can publish or schedule any more reels. Existing
            scheduled reels may fail to publish.
          </p>
        </div>
        {actionError && <p className="text-xs text-[#f85149]">{actionError}</p>}
        <div className="flex gap-2 justify-end">
          <Button variant="ghost" onClick={() => setConfirmOpen(false)} disabled={disconnecting}>
            Cancel
          </Button>
          <Button variant="danger" onClick={handleDisconnect} loading={disconnecting}>
            Disconnect
          </Button>
        </div>
      </div>
    </div>
  );

  // Connected but cannot publish (expired token OR flipped to PERSONAL)
  if (!canPublish) {
    const reason = expired
      ? "Your Instagram token expired — refresh it."
      : isPersonalType
      ? "Your Instagram account is now Personal — switch back to Business/Creator in the IG app."
      : "We can’t publish to this account right now.";

    return (
      <div className="p-8 max-w-3xl mx-auto space-y-8">
        {renderHeader()}
        {successBanner}
        {errorBanner}

        <Card>
          <div className="space-y-5">
            {profileCard}

            <div className="flex items-start gap-3 p-3 rounded-lg border border-[#f85149]/40 bg-[#1a0a0a]">
              <div className="mt-0.5 w-4 h-4 rounded-full bg-[#f85149] flex items-center justify-center flex-shrink-0">
                <span className="text-[10px] font-bold text-white leading-none">!</span>
              </div>
              <div className="flex-1 text-xs text-[#f87171]">
                This account can’t publish. {reason}
              </div>
            </div>

            {actionSuccess && (
              <p className="text-xs text-[#3fb950]">{actionSuccess}</p>
            )}
            {actionError && !confirmOpen && (
              <p className="text-xs text-[#f85149]">{actionError}</p>
            )}

            {buttons}
          </div>
        </Card>

        {confirmDialog}
      </div>
    );
  }

  // Connected + can publish
  return (
    <div className="p-8 max-w-3xl mx-auto space-y-8">
      {renderHeader()}
      {successBanner}
      {errorBanner}

      <Card>
        <div className="space-y-5">
          {profileCard}

          {actionSuccess && (
            <p className="text-xs text-[#3fb950]">{actionSuccess}</p>
          )}
          {actionError && !confirmOpen && (
            <p className="text-xs text-[#f85149]">{actionError}</p>
          )}

          {buttons}

          <p className="text-[11px] text-[#484f58] leading-relaxed pt-1">
            Your access token auto-extends when you refresh it. We never display or expose the token
            itself — all publishing happens server-side over Instagram’s official Graph API.
          </p>
        </div>
      </Card>

      {confirmDialog}
    </div>
  );
}

// ── Suspense wrapper ─────────────────────────────────────────────────────
// useSearchParams() requires a Suspense boundary in Next 14's app router.

function InstagramSettingsFallback() {
  return (
    <div className="p-8 max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-[#e6edf3]">Instagram</h1>
        <p className="text-sm text-[#484f58] mt-1">
          Connect your Instagram Business or Creator account to publish reels directly from this app.
        </p>
      </div>
      <div className="bg-[#161b22] border border-[#21262d] rounded-lg p-5">
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <div className="skeleton-shimmer w-14 h-14 rounded-full" />
            <div className="flex-1 space-y-2">
              <div className="skeleton-shimmer h-4 w-32 rounded" />
              <div className="skeleton-shimmer h-3 w-48 rounded" />
            </div>
          </div>
          <div className="flex gap-2 pt-2">
            <div className="skeleton-shimmer h-10 w-32 rounded-lg" />
            <div className="skeleton-shimmer h-10 w-28 rounded-lg" />
          </div>
        </div>
      </div>
    </div>
  );
}

export default function InstagramSettingsPage() {
  return (
    <Suspense fallback={<InstagramSettingsFallback />}>
      <InstagramSettingsInner />
    </Suspense>
  );
}
