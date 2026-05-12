"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, type ReferencePage } from "@/lib/api";

/**
 * Settings panel for the new per-reference-page discovery flow.
 *
 * Capped at 5 entries server-side. The Add button gates locally on the same
 * cap so users see "Limit reached" without paying for a server roundtrip,
 * but the server is still the source of truth — a duplicate or capped add
 * surfaces the backend error in the inline error slot.
 */
export function ReferencePagesPanel() {
  const [items, setItems] = useState<ReferencePage[]>([]);
  const [max, setMax] = useState(5);
  const [handle, setHandle] = useState("");
  const [adding, setAdding] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setError(null);
    try {
      const list = await api.referencePages.list();
      setItems(list.items);
      setMax(list.max);
    } catch (e: any) {
      setError(e?.message || "Failed to load reference pages");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const atLimit = items.length >= max;

  const handleAdd = async () => {
    const trimmed = handle.trim();
    if (!trimmed) return;
    setAdding(true);
    setError(null);
    try {
      const created = await api.referencePages.add(trimmed);
      // Idempotent re-adds return the existing row — splice or push.
      setItems((prev) => {
        const existing = prev.findIndex((p) => p.id === created.id);
        if (existing >= 0) return prev;
        return [created, ...prev];
      });
      setHandle("");
    } catch (e: any) {
      setError(e?.message || "Could not add reference page");
    }
    setAdding(false);
  };

  const handleRemove = async (id: string) => {
    setRemovingId(id);
    setError(null);
    try {
      await api.referencePages.remove(id);
      setItems((prev) => prev.filter((p) => p.id !== id));
    } catch (e: any) {
      setError(e?.message || "Failed to remove reference page");
    }
    setRemovingId(null);
  };

  return (
    <div>
      <h2 className="text-sm font-medium text-[#e6edf3] mb-3">
        Reference pages for discovery
        <span className="ml-2 text-xs text-[#484f58]">
          ({items.length} / {max})
        </span>
      </h2>
      <Card>
        <div className="space-y-3">
          <div className="flex gap-2">
            <Input
              placeholder="Instagram username (e.g. natgeo)"
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
              disabled={atLimit || adding}
              className="flex-1"
              data-testid="ref-handle-input"
            />
            <Button
              onClick={handleAdd}
              loading={adding}
              disabled={atLimit || !handle.trim()}
              data-testid="ref-add-button"
            >
              {atLimit ? "Limit reached" : "Add"}
            </Button>
          </div>
          <p className="text-[11px] text-[#484f58] leading-relaxed">
            Add up to {max} Instagram pages we should pull recent reels from
            for the discovery feed. We rank what they post against your filters.
          </p>
          {error && (
            <p className="text-xs text-[#f85149]" role="alert" data-testid="ref-error">
              {error}
            </p>
          )}
        </div>

        {!loading && items.length === 0 && (
          <p className="text-xs text-[#484f58] py-4 text-center mt-3">
            No reference pages yet. Add one above to start discovery.
          </p>
        )}

        {items.length > 0 && (
          <div className="space-y-2 mt-3" data-testid="ref-list">
            {items.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between p-3 bg-[#0d1117] rounded-lg"
                data-testid={`ref-item-${p.ig_handle}`}
              >
                <div>
                  <span className="text-sm font-medium text-[#e6edf3]">
                    @{p.ig_handle}
                  </span>
                  {p.ig_display_name && (
                    <span className="ml-2 text-xs text-[#484f58]">
                      {p.ig_display_name}
                    </span>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => handleRemove(p.id)}
                  loading={removingId === p.id}
                  data-testid={`ref-remove-${p.ig_handle}`}
                >
                  Remove
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
