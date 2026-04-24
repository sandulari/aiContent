"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Loading } from "@/components/shared/loading";
import { EmptyState } from "@/components/shared/empty-state";
import {
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableHeaderCell,
} from "@/components/ui/table";
import {
  api,
  ApiError,
  ScheduledReel,
  ScheduledReelStatus,
  ScheduledReelsList,
  UserExport,
} from "@/lib/api";
import { ScheduleReelDialog } from "@/components/scheduler/ScheduleReelDialog";
import { usePolling } from "@/hooks/use-polling";
import clsx from "clsx";

type TabKey = "all" | ScheduledReelStatus;
const TAB_ORDER: TabKey[] = [
  "all",
  "queued",
  "processing",
  "published",
  "failed",
  "cancelled",
];

const TAB_LABEL: Record<TabKey, string> = {
  all: "All",
  queued: "Queued",
  processing: "Processing",
  published: "Published",
  failed: "Failed",
  cancelled: "Cancelled",
};

const STATUS_STYLE: Record<ScheduledReelStatus, string> = {
  queued: "bg-[#0a1a2e] text-[#4a9eff]",
  processing: "bg-[#1a1500] text-[#eab308]",
  published: "bg-[#0a1a0a] text-[#4ade80]",
  failed: "bg-[#1a0a0a] text-[#f87171]",
  cancelled: "bg-[#1a1a1a] text-[#7d8590]",
};

function StatusPill({ status }: { status: ScheduledReelStatus }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
        STATUS_STYLE[status],
      )}
    >
      {status}
    </span>
  );
}

/** Friendly relative-future formatter (e.g. "Tomorrow at 2:00 PM", "in 3 days"). */
function formatWhen(iso: string, status: ScheduledReelStatus): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const now = new Date();
  const diffMs = d.getTime() - now.getTime();
  const absMin = Math.round(Math.abs(diffMs) / 60_000);
  const absHr = Math.round(absMin / 60);
  const absDay = Math.round(absHr / 24);

  const timeStr = d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  const sameDay = d.toDateString() === now.toDateString();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  const isTomorrow = d.toDateString() === tomorrow.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();

  if (status === "published") {
    // Past tense.
    if (absMin < 1) return "Published just now";
    if (absMin < 60) return `Published ${absMin} minute${absMin !== 1 ? "s" : ""} ago`;
    if (absHr < 24) return `Published ${absHr} hour${absHr !== 1 ? "s" : ""} ago`;
    if (isYesterday) return `Published yesterday at ${timeStr}`;
    if (absDay < 7) return `Published ${absDay} day${absDay !== 1 ? "s" : ""} ago`;
    return `Published ${d.toLocaleDateString()} ${timeStr}`;
  }

  if (diffMs < 0) {
    // Past-due, non-published (e.g. failed).
    if (absMin < 1) return "Moments ago";
    if (absMin < 60) return `${absMin} minute${absMin !== 1 ? "s" : ""} ago`;
    if (absHr < 24) return `${absHr} hour${absHr !== 1 ? "s" : ""} ago`;
    if (absDay < 7) return `${absDay} day${absDay !== 1 ? "s" : ""} ago`;
    return `${d.toLocaleDateString()} ${timeStr}`;
  }

  if (sameDay) return `Today at ${timeStr}`;
  if (isTomorrow) return `Tomorrow at ${timeStr}`;
  if (absDay < 7) return `in ${absDay} day${absDay !== 1 ? "s" : ""} (${timeStr})`;
  return `${d.toLocaleDateString()} ${timeStr}`;
}

function truncateCaption(c: string | null, max = 80): string {
  if (!c) return "—";
  const s = c.replace(/\s+/g, " ").trim();
  if (s.length <= max) return s;
  return s.slice(0, max - 1).trimEnd() + "…";
}

interface InsightsMetrics {
  reach: number;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saved: number;
  total_interactions: number;
}

interface InsightsCacheEntry {
  metrics?: InsightsMetrics;
  fetchedAt?: string;
  loading: boolean;
  error?: string;
  /** When true, the saved error means "reconnect IG" — show reconnect link. */
  needsReconnect?: boolean;
}

function fmtInt(n: number): string {
  return (n ?? 0).toLocaleString();
}

export default function ScheduledPage() {
  const router = useRouter();
  const [data, setData] = useState<ScheduledReelsList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [actingId, setActingId] = useState<string | null>(null);
  const [expandedError, setExpandedError] = useState<Record<string, boolean>>({});
  // Per-row insights cache. Clicking "View insights" toggles visibility —
  // we only hit the API the first time or when "Refresh" is clicked.
  const [insightsState, setInsightsState] = useState<Record<string, InsightsCacheEntry>>({});
  const [insightsOpen, setInsightsOpen] = useState<Record<string, boolean>>({});

  // Modal state
  const [pickOpen, setPickOpen] = useState(false);
  const [pickExports, setPickExports] = useState<UserExport[] | null>(null);
  const [pickLoading, setPickLoading] = useState(false);
  const [pickError, setPickError] = useState<string | null>(null);

  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [scheduleExportId, setScheduleExportId] = useState<string | undefined>();
  const [editing, setEditing] = useState<ScheduledReel | undefined>(undefined);

  const fetchList = useCallback(async () => {
    try {
      const res = await api.scheduled.list(
        activeTab === "all" ? {} : { status: activeTab },
      );
      setData(res);
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Failed to load scheduled reels.");
    } finally {
      setLoading(false);
    }
  }, [activeTab]);

  // Refetch whenever the tab changes (also re-runs via polling).
  useEffect(() => {
    setLoading(true);
    fetchList();
  }, [fetchList]);

  usePolling(fetchList, 15000, true);

  const items = data?.items ?? [];
  const counts = data?.counts ?? {
    queued: 0,
    processing: 0,
    published: 0,
    failed: 0,
    cancelled: 0,
  };

  const openSchedulePicker = useCallback(async () => {
    // Pre-flight: ensure IG is connected + publishable.
    try {
      const status = await api.ig.status();
      if (!status.can_publish) {
        const msg = status.connected
          ? "Your Instagram account can't publish reels. Please reconnect or use a Business/Creator account."
          : "Connect Instagram first to schedule reels.";
        if (window.confirm(`${msg}\n\nOpen Instagram settings?`)) {
          router.push("/settings/instagram");
        }
        return;
      }
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message || "Could not verify Instagram status."
          : "Could not verify Instagram status.";
      if (window.confirm(`${msg}\n\nOpen Instagram settings?`)) {
        router.push("/settings/instagram");
      }
      return;
    }

    setPickOpen(true);
    if (pickExports === null) {
      setPickLoading(true);
      setPickError(null);
      try {
        const all = await api.exports.list();
        const done = all.filter((e) => e.export_status === "done" && !!e.export_minio_key);
        setPickExports(done);
      } catch (e: any) {
        setPickError(e?.message || "Failed to load exports.");
      } finally {
        setPickLoading(false);
      }
    }
  }, [pickExports, router]);

  const handlePickExport = useCallback((exportId: string) => {
    setScheduleExportId(exportId);
    setEditing(undefined);
    setPickOpen(false);
    setScheduleOpen(true);
  }, []);

  const handleEdit = useCallback((row: ScheduledReel) => {
    setEditing(row);
    setScheduleExportId(undefined);
    setScheduleOpen(true);
  }, []);

  const handleCancel = useCallback(
    async (row: ScheduledReel) => {
      if (!window.confirm("Cancel this scheduled reel? It will not be published.")) return;
      setActingId(row.id);
      try {
        await api.scheduled.cancel(row.id);
        await fetchList();
      } catch (e: any) {
        setError(e?.message || "Failed to cancel.");
      } finally {
        setActingId(null);
      }
    },
    [fetchList],
  );

  const handleRetry = useCallback(
    async (row: ScheduledReel) => {
      setActingId(row.id);
      try {
        await api.scheduled.retry(row.id);
        await fetchList();
      } catch (e: any) {
        setError(e?.message || "Failed to retry.");
      } finally {
        setActingId(null);
      }
    },
    [fetchList],
  );

  const loadInsights = useCallback(async (rowId: string) => {
    setInsightsState((prev) => ({
      ...prev,
      [rowId]: { ...(prev[rowId] || {}), loading: true, error: undefined, needsReconnect: false },
    }));
    try {
      const res = await api.scheduled.insights(rowId);
      setInsightsState((prev) => ({
        ...prev,
        [rowId]: {
          metrics: res.metrics,
          fetchedAt: res.fetched_at,
          loading: false,
        },
      }));
    } catch (e) {
      let msg = "Failed to load insights.";
      let needsReconnect = false;
      if (e instanceof ApiError) {
        msg = e.message || msg;
        // Backend returns {detail: {code: "ig_token_invalid", detail: "..."}}
        // on 401 when the token is rejected by Meta. Also treat
        // ig_not_connected / ig_token_expired as reconnect prompts.
        const body = e.body as any;
        const code = body?.detail?.code ?? body?.code;
        if (e.status === 401 && typeof code === "string" &&
            ["ig_token_invalid", "ig_not_connected", "ig_token_expired"].includes(code)) {
          needsReconnect = true;
          msg = body?.detail?.detail || body?.detail || "Instagram token invalid — reconnect required.";
        } else if (typeof body?.detail?.detail === "string") {
          msg = body.detail.detail;
        }
      }
      setInsightsState((prev) => ({
        ...prev,
        [rowId]: {
          ...(prev[rowId] || {}),
          loading: false,
          error: msg,
          needsReconnect,
          metrics: undefined,
        },
      }));
    }
  }, []);

  const toggleInsights = useCallback(
    (rowId: string) => {
      const isOpen = !!insightsOpen[rowId];
      setInsightsOpen((prev) => ({ ...prev, [rowId]: !isOpen }));
      // Fetch only on first expand when we don't already have metrics.
      if (!isOpen) {
        const cached = insightsState[rowId];
        if (!cached?.metrics && !cached?.loading) {
          loadInsights(rowId);
        }
      }
    },
    [insightsOpen, insightsState, loadInsights],
  );

  const refreshInsights = useCallback(
    (rowId: string) => {
      loadInsights(rowId);
    },
    [loadInsights],
  );

  const onScheduleSuccess = useCallback(() => {
    fetchList();
  }, [fetchList]);

  const rateUsed = data?.publishes_last_24h ?? 0;

  return (
    <div className="p-8 max-w-6xl mx-auto">
      {error && (
        <div className="mb-4 p-3 text-sm text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-[#e6edf3]">Scheduled Reels</h1>
          <p className="text-sm text-[#484f58] mt-1">
            Queue, edit, and track your upcoming Instagram posts.
          </p>
        </div>
        <Button onClick={openSchedulePicker}>Schedule new</Button>
      </div>

      {/* Rate-limit banner */}
      <div className="mb-5 p-3 rounded-lg bg-[#0d1117] border border-[#21262d] flex items-center justify-between">
        <p className="text-xs text-[#c9d1d9]">
          <span className="text-[#e6edf3] font-semibold">{rateUsed}</span> of 100
          Instagram publishes used in the last 24h.
        </p>
        {data && (
          <p className="text-[11px] text-[#7d8590]">
            {data.publishes_remaining_today} remaining today
          </p>
        )}
      </div>

      {/* Tabs */}
      <div className="mb-5 flex flex-wrap gap-1 border-b border-[#21262d]">
        {TAB_ORDER.map((tab) => {
          const active = activeTab === tab;
          const count = tab === "all" ? undefined : counts[tab as ScheduledReelStatus];
          return (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={clsx(
                "px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px",
                active
                  ? "border-[#58a6ff] text-[#e6edf3]"
                  : "border-transparent text-[#7d8590] hover:text-[#c9d1d9]",
              )}
            >
              {TAB_LABEL[tab]}
              {count !== undefined && (
                <span className="ml-1.5 text-[10px] text-[#484f58]">({count})</span>
              )}
            </button>
          );
        })}
      </div>

      {loading && !data ? (
        <div className="py-16">
          <Loading size="lg" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title={activeTab === "all" ? "No scheduled reels yet" : `No ${activeTab} reels`}
          description={
            activeTab === "all"
              ? "Pick an exported reel and choose when it should publish to Instagram."
              : "Try a different status tab."
          }
          actionLabel={activeTab === "all" ? "Schedule your first reel" : undefined}
          onAction={activeTab === "all" ? openSchedulePicker : undefined}
        />
      ) : (
        <Card>
          <Table>
            <TableHead>
              <TableHeaderCell>Reel</TableHeaderCell>
              <TableHeaderCell>Scheduled</TableHeaderCell>
              <TableHeaderCell>Caption</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell />
            </TableHead>
            <TableBody>
              {items.map((row) => (
                <Fragment key={row.id}>
                  <TableRow>
                    <TableCell>
                      <span className="text-sm text-[#c9d1d9] font-mono">
                        {row.user_export_id.slice(0, 8)}
                      </span>
                    </TableCell>
                    <TableCell className="text-[#c9d1d9] text-xs">
                      {formatWhen(
                        row.status === "published" && row.published_at
                          ? row.published_at
                          : row.scheduled_at,
                        row.status,
                      )}
                      <span className="block text-[10px] text-[#484f58] mt-0.5">
                        {row.timezone}
                      </span>
                    </TableCell>
                    <TableCell className="text-[#7d8590] text-xs max-w-[260px]">
                      {truncateCaption(row.caption, 80)}
                    </TableCell>
                    <TableCell>
                      <StatusPill status={row.status} />
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2 justify-end">
                        {row.status === "queued" && (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleEdit(row)}
                              disabled={actingId === row.id}
                            >
                              Edit
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              loading={actingId === row.id}
                              onClick={() => handleCancel(row)}
                            >
                              Cancel
                            </Button>
                          </>
                        )}
                        {row.status === "processing" && (
                          <span className="text-[11px] text-[#7d8590]">
                            Publishing…
                          </span>
                        )}
                        {row.status === "published" && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => toggleInsights(row.id)}
                          >
                            {insightsOpen[row.id] ? "Hide insights" : "View insights"}
                          </Button>
                        )}
                        {row.status === "failed" && (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() =>
                                setExpandedError((prev) => ({
                                  ...prev,
                                  [row.id]: !prev[row.id],
                                }))
                              }
                            >
                              {expandedError[row.id] ? "Hide error" : "Show error"}
                            </Button>
                            <Button
                              size="sm"
                              variant="secondary"
                              loading={actingId === row.id}
                              onClick={() => handleRetry(row)}
                            >
                              Retry
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                  {row.status === "failed" && expandedError[row.id] && (
                    <TableRow>
                      <TableCell className="pt-0" />
                      <TableCell className="pt-0" colSpan={4}>
                        <div className="p-3 text-[11px] text-[#f87171] bg-[#1a0a0a] border border-[#f87171]/30 rounded whitespace-pre-wrap">
                          {row.last_error || "No error message recorded."}
                          {row.attempt_count > 0 && (
                            <span className="block mt-1 text-[10px] text-[#7d8590]">
                              Attempts: {row.attempt_count}
                            </span>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                  {row.status === "published" && insightsOpen[row.id] && (
                    <TableRow>
                      <TableCell className="pt-0" />
                      <TableCell className="pt-0" colSpan={4}>
                        {(() => {
                          const s = insightsState[row.id];
                          if (!s || s.loading) {
                            return (
                              <div className="p-3 text-[11px] text-[#7d8590] bg-[#0d1117] border border-[#21262d] rounded flex items-center gap-2">
                                <Loading size="sm" />
                                <span>Loading insights…</span>
                              </div>
                            );
                          }
                          if (s.error) {
                            return (
                              <div className="p-3 text-[11px] text-[#f87171] bg-[#1a0a0a] border border-[#f87171]/30 rounded">
                                <div>{s.error}</div>
                                <div className="mt-2 flex gap-3">
                                  {s.needsReconnect && (
                                    <button
                                      onClick={() => router.push("/settings/instagram")}
                                      className="text-[#58a6ff] hover:underline"
                                    >
                                      Reconnect Instagram
                                    </button>
                                  )}
                                  <button
                                    onClick={() => refreshInsights(row.id)}
                                    className="text-[#58a6ff] hover:underline"
                                  >
                                    Retry
                                  </button>
                                </div>
                              </div>
                            );
                          }
                          const m = s.metrics;
                          if (!m) return null;
                          return (
                            <div className="p-3 text-[11px] text-[#c9d1d9] bg-[#0d1117] border border-[#21262d] rounded flex flex-wrap items-center gap-x-3 gap-y-1">
                              <span>Reach: <span className="text-[#e6edf3] font-semibold">{fmtInt(m.reach)}</span></span>
                              <span className="text-[#484f58]">•</span>
                              <span>Views: <span className="text-[#e6edf3] font-semibold">{fmtInt(m.views)}</span></span>
                              <span className="text-[#484f58]">•</span>
                              <span>Likes: <span className="text-[#e6edf3] font-semibold">{fmtInt(m.likes)}</span></span>
                              <span className="text-[#484f58]">•</span>
                              <span>Comments: <span className="text-[#e6edf3] font-semibold">{fmtInt(m.comments)}</span></span>
                              <span className="text-[#484f58]">•</span>
                              <span>Shares: <span className="text-[#e6edf3] font-semibold">{fmtInt(m.shares)}</span></span>
                              <span className="text-[#484f58]">•</span>
                              <span>Saves: <span className="text-[#e6edf3] font-semibold">{fmtInt(m.saved)}</span></span>
                              <span className="ml-auto flex items-center gap-2">
                                {s.fetchedAt && (
                                  <span className="text-[10px] text-[#484f58]">
                                    Updated {new Date(s.fetchedAt).toLocaleTimeString()}
                                  </span>
                                )}
                                <button
                                  onClick={() => refreshInsights(row.id)}
                                  className="text-[10px] text-[#58a6ff] hover:underline"
                                >
                                  Refresh
                                </button>
                              </span>
                            </div>
                          );
                        })()}
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      {/* Picker modal: choose an export */}
      <Modal
        isOpen={pickOpen}
        onClose={() => setPickOpen(false)}
        title="Pick an exported reel"
        className="max-w-lg"
      >
        {pickLoading ? (
          <div className="py-8">
            <Loading />
          </div>
        ) : pickError ? (
          <div className="p-3 text-xs text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded">
            {pickError}
          </div>
        ) : !pickExports || pickExports.length === 0 ? (
          <EmptyState
            title="No exports ready to schedule"
            description="Only completed exports can be scheduled. Edit and export a reel first."
            actionLabel="Go to Library"
            onAction={() => {
              setPickOpen(false);
              router.push("/library");
            }}
          />
        ) : (
          <div className="space-y-2 max-h-[60vh] overflow-y-auto">
            {pickExports.map((exp) => (
              <button
                key={exp.id}
                onClick={() => handlePickExport(exp.id)}
                className="w-full text-left p-3 rounded-lg bg-[#0d1117] border border-[#21262d] hover:border-[#58a6ff] transition-colors"
              >
                <p className="text-sm text-[#e6edf3] font-medium line-clamp-1">
                  {exp.headline_text || "Untitled"}
                </p>
                {exp.subtitle_text && (
                  <p className="text-[11px] text-[#7d8590] mt-0.5 line-clamp-1">
                    {exp.subtitle_text}
                  </p>
                )}
                <p className="text-[10px] text-[#484f58] mt-1 font-mono">
                  {exp.id.slice(0, 8)}
                </p>
              </button>
            ))}
          </div>
        )}
      </Modal>

      {/* Create / edit dialog */}
      <ScheduleReelDialog
        open={scheduleOpen}
        onClose={() => setScheduleOpen(false)}
        onSuccess={onScheduleSuccess}
        exportId={scheduleExportId}
        editing={editing}
      />
    </div>
  );
}
