"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/shared/loading";
import { EmptyState } from "@/components/shared/empty-state";
import { api, UserExport } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { usePolling } from "@/hooks/use-polling";

export default function LibraryPage() {
  const router = useRouter();
  const [exports, setExports] = useState<UserExport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try { setExports(await api.exports.list()); } catch (e: any) {
      console.error("Failed to fetch library:", e?.message || "unknown error");
      setError(e?.message || "Failed to load library. Please try again.");
    }
    setLoading(false);
  }, []);
  usePolling(fetch, 15000, true);

  if (loading) return <div className="p-8"><Loading size="lg" className="py-20" /></div>;

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {error && (
        <div className="mx-4 mt-4 p-3 text-sm text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded">
          {error}
        </div>
      )}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-[#e6edf3]">My Library</h1>
          <p className="text-sm text-[#484f58] mt-1">Your edited and exported reels</p>
        </div>
        <Button variant="secondary" onClick={() => router.push("/dashboard")}>Find More Reels</Button>
      </div>

      {exports.length === 0 ? (
        <EmptyState title="Your library is empty" description="Use reels from your dashboard to start creating." actionLabel="Go to Dashboard" onAction={() => router.push("/dashboard")} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {exports.map((exp) => (
            <Card key={exp.id}>
              <div className="space-y-3">
                <div>
                  <p className="text-sm text-[#e6edf3] font-medium line-clamp-2">{exp.headline_text}</p>
                  <p className="text-xs text-[#7d8590] mt-0.5">{exp.subtitle_text}</p>
                </div>
                <div className="flex items-center justify-between text-xs text-[#484f58]">
                  <span>{formatDate(exp.created_at)}</span>
                  <span className="capitalize">{exp.export_status}</span>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" className="flex-1" variant="ghost" onClick={() => router.push(`/editor/${exp.id}`)}>Edit</Button>
                  {(exp.export_status === "done" || exp.export_status === "completed") && exp.export_minio_key && (
                    <Button size="sm" variant="secondary" onClick={() => window.open(api.exports.downloadUrl(exp.id), "_blank")}>Download</Button>
                  )}
                  <Button size="sm" variant="danger" loading={deletingId === exp.id} onClick={async () => {
                    if (!confirm("Delete this export? This cannot be undone.")) return;
                    setDeletingId(exp.id);
                    try {
                      await api.exports.delete(exp.id);
                      setExports((prev) => prev.filter((e) => e.id !== exp.id));
                    } catch (e: any) {
                      console.error("Failed to delete export:", e?.message || "unknown error");
                      setError(e?.message || "Failed to delete export.");
                    }
                    setDeletingId(null);
                  }}>Delete</Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
