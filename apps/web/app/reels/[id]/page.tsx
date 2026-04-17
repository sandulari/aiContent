"use client";

import { useState, useCallback, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loading } from "@/components/shared/loading";
import { Skeleton, SkeletonText } from "@/components/shared/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { api, ReelDetail, ReelSource, Template } from "@/lib/api";
import { formatViews, formatDuration, formatDate } from "@/lib/utils";
import { usePolling } from "@/hooks/use-polling";

export default function ReelDetailPage() {
  const params = useParams();
  const router = useRouter();
  const reelId = params.id as string;

  const [reel, setReel] = useState<ReelDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [findingSource, setFindingSource] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [openingEditor, setOpeningEditor] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const status = reel?.status || "discovered";
  const shouldPoll = status === "searching_source" || status === "downloading" || findingSource || downloadingId !== null;

  const fetchReel = useCallback(async () => {
    try {
      const d = await api.reels.get(reelId);
      setReel(d);
      // Reset transient UI flags whenever the backend reaches a terminal state
      // so the spinner can't outlive the actual job.
      if (d.status === "downloaded" || d.status === "done") {
        setDownloadingId(null);
        setFindingSource(false);
      }
      if (d.status === "source_found") {
        setFindingSource(false);
      }
      if (d.status === "failed") {
        setFindingSource(false);
        setDownloadingId(null);
      }
    } catch (e: any) {
      console.error("Failed to load reel:", e?.message || "unknown error");
      setError(e?.message || "Failed to load reel. Please try again.");
    }
    setLoading(false);
  }, [reelId]);

  usePolling(fetchReel, 3000, shouldPoll || loading);

  // Load templates so user can pick which one seeds the new export.
  useEffect(() => {
    (async () => {
      try {
        const ts = await api.templates.list();
        setTemplates(ts);
        const def = ts.find((t) => t.is_default) || ts[0];
        if (def) setSelectedTemplateId(def.id);
      } catch (e: any) {
        console.error("Failed to load templates:", e?.message || "unknown error");
      }
    })();
  }, []);

  const handleFindSources = async () => {
    setFindingSource(true);
    try {
      await api.reels.findSources(reelId);
      // Force one immediate refetch so polling locks onto the new status quickly
      const d = await api.reels.get(reelId);
      setReel(d);
    } catch (e: any) {
      console.error("Failed to find sources:", e?.message || "unknown error");
      setError(e?.message || "Failed to search for sources. Please try again.");
      setFindingSource(false);
    }
  };

  const handleRetrySearch = async () => {
    // Optimistically clear the failed state so the UI doesn't show stale error
    setReel((prev) => (prev ? { ...prev, status: "searching_source", sources: [] } : prev));
    setFindingSource(true);
    try {
      await api.reels.findSources(reelId);
    } catch (e: any) {
      console.error("Failed to retry search:", e?.message || "unknown error");
      setError(e?.message || "Failed to retry source search. Please try again.");
      setFindingSource(false);
    }
  };

  const handleDownload = async (sourceId: string) => {
    setDownloadingId(sourceId);
    try {
      await api.reels.download(reelId, sourceId);
    } catch (e: any) {
      console.error("Failed to download:", e?.message || "unknown error");
      setError(e?.message || "Download failed. Please try again.");
      setDownloadingId(null);
    }
  };

  const handleOpenEditor = async () => {
    if (!reel) return;
    setOpeningEditor(true);
    try {
      let tplId = selectedTemplateId;
      if (!tplId) {
        if (templates.length > 0) {
          tplId = (templates.find((t) => t.is_default) || templates[0]).id;
        } else {
          const t = await api.templates.create({ template_name: "My Template" });
          setTemplates([t]);
          setSelectedTemplateId(t.id);
          tplId = t.id;
        }
      }
      const exp = await api.exports.create({
        viral_reel_id: reel.id, template_id: tplId,
        headline_text: (reel.caption || "Your Headline").slice(0, 80),
        subtitle_text: reel.source_page ? `@${reel.source_page}` : "Your subtitle",
      });
      router.push(`/editor/${exp.id}`);
    } catch (e: any) {
      console.error("Failed to open editor:", e?.message || "unknown error");
      setError(e?.message || "Failed to create export. Please try again.");
      setOpeningEditor(false);
    }
  };

  if (loading) return <div className="p-6 max-w-5xl mx-auto space-y-5"><Skeleton className="h-4 w-16" /><div className="bg-[#161b22] border border-[#21262d] rounded-2xl p-6 space-y-4"><Skeleton className="h-6 w-64" /><SkeletonText lines={3} /><div className="flex gap-4"><Skeleton className="h-10 w-32 rounded-lg" /><Skeleton className="h-10 w-32 rounded-lg" /></div></div></div>;
  if (!reel) return <div className="p-8"><EmptyState title="Reel not found" actionLabel="Go Back" onAction={() => router.back()} /></div>;

  const hasSources = reel.sources.length > 0;
  const canEdit = ["downloaded", "done"].includes(status);
  // Once we have sources or the reel is downloading, the search step is over.
  const isDownloading = status === "downloading" || downloadingId !== null;
  const searchFailed = status === "failed" && !hasSources && !canEdit;
  const isSearching =
    !hasSources && !canEdit && !searchFailed && (status === "searching_source" || findingSource);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {error && (
        <div className="p-3 text-sm text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded">
          {error}
        </div>
      )}
      <button onClick={() => router.back()} className="text-sm text-[#7d8590] hover:text-[#e6edf3] flex items-center gap-1">
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
        Back
      </button>

      {/* Info */}
      <Card>
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm text-[#e6edf3] leading-relaxed flex-1">{reel.caption || "Viral Reel"}</p>
            <Badge status={status} />
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-[#7d8590]">
            <span>{formatViews(reel.view_count)} views</span>
            <span>{formatViews(reel.like_count)} likes</span>
            {reel.duration_seconds && <span>{formatDuration(reel.duration_seconds)}</span>}
            <span>{formatDate(reel.posted_at)}</span>
          </div>
          <div className="flex items-center gap-3">
            {reel.source_page && <span className="text-xs text-[#7d8590]">@{reel.source_page}</span>}
            {reel.ig_url && (
              <a href={reel.ig_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#58a6ff] hover:underline">View on Instagram</a>
            )}
          </div>
        </div>
      </Card>

      {/* Downloaded → Open Editor */}
      {canEdit && (
        <Card>
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <h3 className="text-sm font-semibold text-[#3fb950]">Video saved to your library</h3>
                <p className="text-xs text-[#484f58] mt-0.5">Ready to edit</p>
              </div>
              <div className="flex items-center gap-2">
                {templates.length > 1 && (
                  <select
                    value={selectedTemplateId}
                    onChange={(e) => setSelectedTemplateId(e.target.value)}
                    className="h-9 px-3 text-xs bg-[#161b22] text-[#e6edf3] border border-[#30363d] rounded-md focus:outline-none focus:border-[#58a6ff]"
                    title="Which template seeds the styling of your new export"
                  >
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.template_name}{t.is_default ? " ★" : ""}
                      </option>
                    ))}
                  </select>
                )}
                <Button onClick={handleOpenEditor} loading={openingEditor}>Open in Editor</Button>
              </div>
            </div>
            <div className="bg-black rounded-lg overflow-hidden flex justify-center">
              <video src={api.files.getVideoStreamUrl(reel.id)} controls playsInline className="max-h-[360px]" />
            </div>
          </div>
        </Card>
      )}

      {/* Downloading */}
      {isDownloading && (
        <Card>
          <div className="flex items-center gap-4 py-4">
            <Loading size="md" />
            <div>
              <p className="text-sm text-[#e6edf3] font-medium">Saving video to your library...</p>
              <p className="text-xs text-[#484f58] mt-0.5">This may take a minute.</p>
            </div>
          </div>
        </Card>
      )}

      {/* Find Sources (initial state) */}
      {!hasSources && !isSearching && !canEdit && !isDownloading && !searchFailed && (
        <Card>
          <div className="flex flex-col items-center py-8 gap-3">
            <p className="text-sm text-[#e6edf3] font-medium">Find this video on other platforms</p>
            <p className="text-xs text-[#484f58] max-w-md text-center">We'll search YouTube, TikTok, and other platforms for the same video without Instagram's fingerprint.</p>
            <Button onClick={handleFindSources} loading={findingSource} className="mt-2">Find Alternative Sources</Button>
          </div>
        </Card>
      )}

      {/* Searching (in progress) */}
      {isSearching && (
        <Card>
          <div className="flex items-center justify-center gap-3 py-8">
            <Loading size="md" />
            <div>
              <p className="text-sm text-[#e6edf3]">Searching across platforms...</p>
              <p className="text-xs text-[#484f58] mt-0.5">Checking YouTube, TikTok, Google Video</p>
            </div>
          </div>
        </Card>
      )}

      {/* Search failed (no spinner — clear failure UI with retry) */}
      {searchFailed && (
        <Card>
          <div className="flex flex-col items-center py-8 gap-4">
            <div className="text-center max-w-md">
              <p className="text-sm font-semibold text-[#f85149] mb-1">No alternative sources found</p>
              <p className="text-xs text-[#484f58] leading-relaxed">
                We couldn't match this reel to a video on YouTube, TikTok, or Google Video.
                The caption may be too generic, or the original may not have been re-uploaded
                anywhere outside Instagram.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" onClick={handleRetrySearch} loading={findingSource}>
                Try search again
              </Button>
              {reel.ig_url && (
                <a
                  href={reel.ig_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-[#58a6ff] hover:underline"
                >
                  View on Instagram ↗
                </a>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Sources */}
      {hasSources && !canEdit && !isDownloading && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-[#e6edf3]">Alternative Sources ({reel.sources.length})</h2>
          {reel.sources.map((s: ReelSource) => (
            <Card key={s.id}>
              <div className="flex items-center justify-between gap-4">
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium px-1.5 py-0.5 bg-[#58a6ff]/10 text-[#58a6ff] rounded">{s.source_type}</span>
                    {s.match_confidence != null && (
                      <span className={`text-xs font-medium ${s.match_confidence >= 0.9 ? "text-[#3fb950]" : s.match_confidence >= 0.7 ? "text-[#d29922]" : "text-[#f78166]"}`}>
                        {Math.round(s.match_confidence * 100)}% match
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-[#e6edf3] truncate">{s.source_title || "Untitled"}</p>
                  <a href={s.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#58a6ff] hover:underline">Preview</a>
                </div>
                <Button size="sm" onClick={() => handleDownload(s.id)} loading={downloadingId === s.id} disabled={isDownloading}>
                  Save to Library
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
