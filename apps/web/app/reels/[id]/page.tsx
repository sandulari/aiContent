"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loading } from "@/components/shared/loading";
import { SkeletonReelDetail } from "@/components/shared/skeleton";
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

  // Auto-search for sources when reel loads (if no sources found yet and not already downloaded)
  const autoSearchTriggered = useRef(false);
  useEffect(() => {
    if (!reel || autoSearchTriggered.current) return;
    if (reel.sources.length > 0 || reel.status === "downloaded" || reel.status === "done" || reel.status === "searching_source") return;
    autoSearchTriggered.current = true;
    handleFindSources();
  }, [reel]); // eslint-disable-line react-hooks/exhaustive-deps

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

  if (loading) return <SkeletonReelDetail />;
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

      {/* No sources yet and not searching — this shouldn't show because auto-search triggers on load */}

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

      {/* Search failed — clear failure UI with retry */}
      {searchFailed && (
        <Card>
          <div className="flex flex-col items-center py-8 gap-4">
            <div className="text-center max-w-md">
              <p className="text-sm font-semibold text-[#f85149] mb-1">Source search failed</p>
              <p className="text-xs text-[#484f58] leading-relaxed">
                We couldn&apos;t match this reel to a video on YouTube, TikTok, or Google Video right now.
                This can happen when the search service is busy or the caption is too generic.
                Give it another try — results often improve on a second attempt.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Button onClick={handleRetrySearch} loading={findingSource}>
                Retry Search
              </Button>
              {reel.ig_url && (
                <a
                  href={reel.ig_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-[#58a6ff] hover:underline"
                >
                  View on Instagram
                </a>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Best source — most likely the same video */}
      {hasSources && !canEdit && !isDownloading && (
        <Card>
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-[#e6edf3]">Download This Video</h3>
            <p className="text-[11px] text-[#484f58]">Found on YouTube — clean copy without Instagram fingerprint</p>
            {(() => {
              const best = reel.sources[0]; // Already sorted by confidence
              return (
                <div className="flex items-center gap-3 bg-[#0d1117] rounded-lg p-3">
                  {/* Video thumbnail — always show */}
                  <img
                    src={(() => {
                      if (best.source_thumbnail_url) return best.source_thumbnail_url;
                      const ytId = best.source_url.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)?.[1];
                      if (ytId) return `https://img.youtube.com/vi/${ytId}/mqdefault.jpg`;
                      return api.files.getThumbnailUrl(reel.id);
                    })()}
                    alt=""
                    className="w-32 h-20 object-cover rounded-md flex-shrink-0 bg-[#21262d]"
                    onError={(e) => { e.currentTarget.src = api.files.getThumbnailUrl(reel.id); }}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-[#e6edf3] font-medium line-clamp-2">{best.source_title || "Video"}</p>
                    <div className="flex items-center gap-2 mt-1 text-[10px] text-[#484f58]">
                      <span className="uppercase font-medium text-[#58a6ff]">{best.source_type}</span>
                      <span>{Math.round((best.match_confidence || 0) * 100)}% match</span>
                    </div>
                  </div>
                  <div className="flex gap-2 flex-shrink-0">
                    <a href={best.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#7d8590] hover:text-[#e6edf3] px-2 py-1.5 border border-[#30363d] rounded-md">
                      Preview
                    </a>
                    <Button size="sm" onClick={() => handleDownload(best.id)} loading={downloadingId === best.id}>
                      Download
                    </Button>
                  </div>
                </div>
              );
            })()}
          </div>
        </Card>
      )}

      {/* Similar content — alternative videos on the same topic */}
      {hasSources && reel.sources.length > 1 && !canEdit && (
        <div>
          <h3 className="text-sm font-medium text-[#e6edf3] mb-3">Similar Content</h3>
          <div className="space-y-2">
            {reel.sources.slice(1).map((source) => (
              <div key={source.id} className="flex items-center gap-3 bg-[#161b22] border border-[#21262d] rounded-lg p-3">
                <img
                  src={(() => {
                    if (source.source_thumbnail_url) return source.source_thumbnail_url;
                    const ytId = source.source_url.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)?.[1];
                    if (ytId) return `https://img.youtube.com/vi/${ytId}/default.jpg`;
                    return api.files.getThumbnailUrl(reel.id);
                  })()}
                  alt=""
                  className="w-20 h-14 object-cover rounded flex-shrink-0 bg-[#21262d]"
                  onError={(e) => { e.currentTarget.src = api.files.getThumbnailUrl(reel.id); }}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-[#e6edf3] font-medium line-clamp-1">{source.source_title || "Video"}</p>
                  <div className="flex items-center gap-2 mt-0.5 text-[10px] text-[#484f58]">
                    <span className="uppercase text-[#58a6ff]">{source.source_type}</span>
                    <span>{Math.round((source.match_confidence || 0) * 100)}% match</span>
                  </div>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <a href={source.source_url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-[#7d8590] hover:text-[#e6edf3] px-2 py-1 border border-[#30363d] rounded">
                    Preview
                  </a>
                  <Button size="sm" onClick={() => handleDownload(source.id)} loading={downloadingId === source.id}>
                    Save
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
