"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api, UserExport } from "@/lib/api";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loading } from "@/components/shared/loading";

interface ExportDialogProps {
  exportId: string;
  captionText?: string | null;
  onClose: () => void;
}

type ExportPhase = "settings" | "rendering" | "done" | "error";

export function ExportDialog({ exportId, captionText, onClose }: ExportDialogProps) {
  const [phase, setPhase] = useState<ExportPhase>("settings");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [captionCopied, setCaptionCopied] = useState(false);
  const [filename, setFilename] = useState<string>("");
  const [fetchedInitial, setFetchedInitial] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  // Load the current filename + status when the dialog opens.
  // If the export is already rendered, jump straight to `done` mode
  // so the user can rename + re-download without re-rendering.
  useEffect(() => {
    (async () => {
      try {
        const status: UserExport = await api.exports.getStatus(exportId);
        const current =
          (status as any).download_filename ||
          (status.headline_text || "")
            .trim()
            .slice(0, 60)
            .replace(/[^\w\s-]/g, "")
            .replace(/\s+/g, "-") ||
          `export-${exportId.slice(0, 8)}`;
        setFilename(current);
        if (status.export_status === "done") {
          setPhase("done");
          setProgress(100);
          setDownloadUrl(api.exports.downloadUrl(exportId));
        }
      } catch {}
      setFetchedInitial(true);
    })();
  }, [exportId]);

  const pollStatus = useCallback(async () => {
    try {
      const status: UserExport = await api.exports.getStatus(exportId);

      if (status.export_status === "rendering" || status.export_status === "exporting") {
        setProgress((prev) => Math.min(prev + 5, 90));
      } else if (status.export_status === "done" || status.export_status === "completed") {
        setProgress(100);
        setPhase("done");
        stopPolling();
        setDownloadUrl(api.exports.downloadUrl(exportId));
      } else if (status.export_status === "failed" || status.export_status === "error") {
        setPhase("error");
        setError("Export failed. Please try again.");
        stopPolling();
      }
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Failed to check export status");
      stopPolling();
    }
  }, [exportId, stopPolling]);

  // Filename validation matches the hint shown next to the input.
  // Returns null if valid, an error message otherwise. Empty string is
  // treated as valid (server falls back to export_<id>.mp4).
  const validateFilename = useCallback((raw: string): string | null => {
    const clean = raw.trim();
    if (!clean) return null;
    if (clean.length > 180) return "Filename must be 180 characters or fewer.";
    if (!/^[\w\s-]+$/.test(clean))
      return "Filename can only contain letters, numbers, spaces, dashes, underscores.";
    return null;
  }, []);

  // Persist the filename to the export row before kicking off a render
  // or a download. Returns true on success or no-op (empty), false on
  // failure so callers can abort instead of shipping a stale name.
  const persistFilename = useCallback(async (): Promise<boolean> => {
    const clean = filename.trim();
    if (!clean) return true;
    try {
      await api.exports.update(exportId, { download_filename: clean });
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save filename");
      return false;
    }
  }, [exportId, filename]);

  const handleStartExport = async () => {
    const fnErr = validateFilename(filename);
    if (fnErr) {
      setError(fnErr);
      return;
    }
    setError(null);
    if (!(await persistFilename())) return;

    setPhase("rendering");
    setProgress(0);
    try {
      await api.exports.render(exportId);
      pollRef.current = setInterval(pollStatus, 2000);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Failed to start render");
    }
  };

  const handleDownload = async () => {
    // Persist the latest filename so the Content-Disposition header is
    // right on the server side too.
    await persistFilename();
    try {
      const url = downloadUrl || api.exports.downloadUrl(exportId);
      window.open(url, "_blank");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get download link");
    }
  };

  const handleCopyCaption = async () => {
    if (!captionText) return;
    // navigator.clipboard rejects on non-https origins and on Safari
    // permission denial. Fall back to execCommand so the button works
    // everywhere instead of failing silently with an unhandled rejection.
    try {
      await navigator.clipboard.writeText(captionText);
    } catch {
      try {
        const ta = document.createElement("textarea");
        ta.value = captionText;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      } catch {
        setError("Couldn't copy caption — copy manually from the Caption field.");
        return;
      }
    }
    setCaptionCopied(true);
    setTimeout(() => setCaptionCopied(false), 2000);
  };

  // The "go back and keep editing" action — available after a render
  // completes. Closes the dialog and returns the user to the canvas
  // without touching any state.
  const handleKeepEditing = () => {
    onClose();
  };

  const handleRender = async () => {
    // Re-render with whatever the current canvas state is. The user
    // hits this after they've made more edits and want a fresh MP4.
    const fnErr = validateFilename(filename);
    if (fnErr) {
      setError(fnErr);
      return;
    }
    setError(null);
    if (!(await persistFilename())) return;

    setPhase("rendering");
    setProgress(0);
    try {
      await api.exports.render(exportId);
      pollRef.current = setInterval(pollStatus, 2000);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Failed to start render");
    }
  };

  return (
    <Modal isOpen={true} onClose={onClose} title="Export Video">
      <div className="space-y-5">
        {/* Filename — editable in settings + done phases */}
        {(phase === "settings" || phase === "done") && fetchedInitial && (
          <div>
            <p className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-2">
              Filename
            </p>
            <div className="flex items-center gap-2">
              <Input
                value={filename}
                onChange={(e) => setFilename(e.target.value)}
                placeholder="my-awesome-reel"
                className="flex-1"
              />
              <span className="text-xs text-text-secondary font-mono">.mp4</span>
            </div>
            <p className="text-[10px] text-text-secondary mt-1">
              Letters, numbers, spaces, dashes, underscores. Max 180 chars.
            </p>
          </div>
        )}

        {/* Output Settings (always visible) */}
        <div>
          <p className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-2">
            Output Settings
          </p>
          <div className="rounded-md bg-background border border-border p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-text-secondary">Resolution</span>
              <span className="text-xs text-text-primary font-mono">1080 x 1920</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-text-secondary">Codec</span>
              <span className="text-xs text-text-primary font-mono">H.264</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-text-secondary">Format</span>
              <span className="text-xs text-text-primary font-mono">MP4</span>
            </div>
          </div>
        </div>

        {/* Progress Bar */}
        {phase === "rendering" && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-text-secondary">Rendering…</span>
              <span className="text-xs text-text-primary font-mono tabular-nums">{progress}%</span>
            </div>
            <div className="w-full h-2 bg-border rounded-full overflow-hidden">
              <div
                className="h-full bg-primary rounded-full transition-all duration-300 ease-out"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="mt-3 flex justify-center">
              <Loading size="sm" />
            </div>
          </div>
        )}

        {/* Error */}
        {phase === "error" && error && (
          <div className="rounded-md bg-danger/10 border border-danger/30 p-3">
            <p className="text-xs text-danger">{error}</p>
          </div>
        )}

        {/* Done — make it clear the render is complete AND the canvas isn't touched */}
        {phase === "done" && (
          <div className="rounded-md bg-primary/10 border border-primary/30 p-3 space-y-1">
            <p className="text-xs text-primary font-medium">Export ready</p>
            <p className="text-[11px] text-text-secondary leading-relaxed">
              Download below. Your editor is unchanged — you can keep editing and re-render
              anytime. Each render replaces the last export file.
            </p>
          </div>
        )}

        {/* Caption Section */}
        {captionText && (phase === "settings" || phase === "done") && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-medium text-text-secondary uppercase tracking-wide">
                AI Caption
              </p>
              <button
                onClick={handleCopyCaption}
                className="text-xs text-primary hover:text-primary/80 transition-colors duration-150"
              >
                {captionCopied ? "Copied" : "Copy"}
              </button>
            </div>
            <div className="rounded-md bg-background border border-border p-3">
              <p className="text-xs text-text-primary leading-relaxed whitespace-pre-wrap">
                {captionText}
              </p>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 pt-1">
          {phase === "settings" && (
            <>
              <Button variant="secondary" size="md" onClick={onClose} className="flex-1">
                Cancel
              </Button>
              <Button variant="primary" size="md" onClick={handleStartExport} className="flex-1">
                Start Export
              </Button>
            </>
          )}

          {phase === "rendering" && (
            <Button variant="secondary" size="md" onClick={onClose} className="flex-1" disabled>
              Rendering…
            </Button>
          )}

          {phase === "done" && (
            <>
              <Button variant="secondary" size="md" onClick={handleKeepEditing} className="flex-1">
                Keep editing
              </Button>
              <Button variant="ghost" size="md" onClick={handleRender} className="flex-1">
                Re-render
              </Button>
              <Button variant="primary" size="md" onClick={handleDownload} className="flex-1">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download
              </Button>
            </>
          )}

          {phase === "error" && (
            <>
              <Button variant="secondary" size="md" onClick={onClose} className="flex-1">
                Close
              </Button>
              <Button variant="primary" size="md" onClick={handleStartExport} className="flex-1">
                Retry
              </Button>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}
