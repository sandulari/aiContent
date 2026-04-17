"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableHead, TableBody, TableRow, TableCell, TableHeaderCell } from "@/components/ui/table";
import { Loading } from "@/components/shared/loading";
import { EmptyState } from "@/components/shared/empty-state";
import { api, UserExport } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { usePolling } from "@/hooks/use-polling";

export default function ExportsPage() {
  const router = useRouter();
  const [exports, setExports] = useState<UserExport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try { setExports(await api.exports.list()); } catch (e: any) {
      console.error("Failed to fetch exports:", e?.message || "unknown error");
      setError(e?.message || "Failed to load exports. Please try again.");
    }
    setLoading(false);
  }, []);
  usePolling(fetch, 10000, true);

  if (loading) return <div className="p-8"><Loading size="lg" className="py-20" /></div>;

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {error && (
        <div className="mx-4 mt-4 p-3 text-sm text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded">
          {error}
        </div>
      )}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-[#e6edf3]">My Exports</h1>
        <p className="text-sm text-[#484f58] mt-1">Your exported reels ready to post</p>
      </div>

      {exports.length === 0 ? (
        <EmptyState title="No exports yet" description="Edit a video from your library to create your first export." actionLabel="Go to Library" onAction={() => router.push("/library")} />
      ) : (
        <Card>
          <Table>
            <TableHead>
              <TableHeaderCell>Headline</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell>Created</TableHeaderCell>
              <TableHeaderCell>Exported</TableHeaderCell>
              <TableHeaderCell />
            </TableHead>
            <TableBody>
              {exports.map((exp) => (
                <TableRow key={exp.id}>
                  <TableCell>
                    <span className="text-sm text-[#e6edf3] font-medium">{exp.headline_text || "Untitled"}</span>
                    <span className="block text-[11px] text-[#484f58] mt-0.5">{exp.subtitle_text}</span>
                  </TableCell>
                  <TableCell><Badge status={exp.export_status} /></TableCell>
                  <TableCell className="text-[#7d8590] text-xs">{formatDate(exp.created_at)}</TableCell>
                  <TableCell className="text-[#7d8590] text-xs">{exp.exported_at ? formatDate(exp.exported_at) : "—"}</TableCell>
                  <TableCell>
                    <div className="flex gap-2 justify-end">
                      {(exp.export_status === "done" || exp.export_status === "completed") && exp.export_minio_key && (
                        <Button size="sm" variant="secondary" onClick={() => window.open(api.exports.downloadUrl(exp.id), "_blank")}>
                          Download
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => router.push(`/editor/${exp.id}`)}>
                        Edit
                      </Button>
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
                      }}>
                        Delete
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}
