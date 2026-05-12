"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  api,
  type DiscoveryFilter,
  type DiscoveryFilterPayload,
  type DiscoveryFilterPreview,
  type DiscoverySortBy,
} from "@/lib/api";

const SORT_OPTIONS: { value: DiscoverySortBy; label: string }[] = [
  { value: "views_desc", label: "Highest views" },
  { value: "posted_at_desc", label: "Most recent" },
  { value: "engagement_desc", label: "Highest engagement rate" },
  { value: "likes_desc", label: "Most likes" },
  { value: "comments_desc", label: "Most comments" },
];

const PREVIEW_DEBOUNCE_MS = 400;


function payloadFromFilter(f: DiscoveryFilter): DiscoveryFilterPayload {
  return {
    min_views: f.min_views,
    min_likes: f.min_likes,
    min_comments: f.min_comments,
    min_engagement_rate: f.min_engagement_rate,
    max_age_days: f.max_age_days,
    sort_by: f.sort_by,
  };
}

function isDirty(saved: DiscoveryFilter | null, draft: DiscoveryFilterPayload): boolean {
  if (!saved) return true; // anything counts as dirty if nothing's saved
  // Compare field-by-field rather than JSON.stringify so a cleared-then-
  // retyped field (key deleted then re-added at the end) doesn't read as
  // dirty just because the JSON key order changed.
  return (
    draft.min_views !== saved.min_views ||
    draft.min_likes !== saved.min_likes ||
    draft.min_comments !== saved.min_comments ||
    draft.min_engagement_rate !== saved.min_engagement_rate ||
    draft.max_age_days !== saved.max_age_days ||
    draft.sort_by !== saved.sort_by
  );
}

/**
 * Editor for the per-user discovery filter, with a debounced live preview
 * call so the "X reels match" counter tracks the form in real time. Until
 * Task 1.3 lands the `reference_reels` cache the preview always reports
 * count=0; the `has_cache=false` flag drives the explainer copy below.
 */
export function DiscoveryFilterPanel() {
  const [saved, setSaved] = useState<DiscoveryFilter | null>(null);
  const [draft, setDraft] = useState<DiscoveryFilterPayload>({});
  const [preview, setPreview] = useState<DiscoveryFilterPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const current = await api.discoveryFilter.get();
      setSaved(current);
      setDraft(payloadFromFilter(current));
    } catch (e: any) {
      setError(e?.message || "Failed to load discovery filter");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Debounced live preview — fires on every draft change once initial load is done.
  useEffect(() => {
    if (loading) return;
    const t = setTimeout(async () => {
      try {
        const p = await api.discoveryFilter.preview(draft);
        setPreview(p);
      } catch {
        // A 422 here means the user typed a bad value mid-edit — show no
        // count instead of a stale one. The Save button surfaces the
        // detailed error if they try to commit.
        setPreview(null);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [draft, loading]);

  const setField = <K extends keyof DiscoveryFilterPayload>(
    key: K,
    value: DiscoveryFilterPayload[K],
  ) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  // Numeric input handler: empty string clears the field (falls back to
  // server default on save); otherwise parse as int (or float for the
  // engagement rate).
  const setNumber = (key: keyof DiscoveryFilterPayload, raw: string, asFloat = false) => {
    if (raw === "") {
      setDraft((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      return;
    }
    const v = asFloat ? Number.parseFloat(raw) : Number.parseInt(raw, 10);
    if (Number.isFinite(v)) setField(key, v as any);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const next = await api.discoveryFilter.save(draft);
      setSaved(next);
      setDraft(payloadFromFilter(next));
    } catch (e: any) {
      setError(e?.message || "Failed to save discovery filter");
    }
    setSaving(false);
  };

  const dirty = isDirty(saved, draft);

  return (
    <div>
      <h2 className="text-sm font-medium text-[#e6edf3] mb-3">
        Discovery filters
        {saved && !saved.is_default && (
          <span className="ml-2 text-xs text-[#484f58]">
            saved {new Date(saved.updated_at!).toLocaleString()}
          </span>
        )}
      </h2>
      <Card>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#7d8590] mb-1.5">
                Min views
              </label>
              <Input
                type="number"
                min={0}
                value={draft.min_views ?? ""}
                onChange={(e) => setNumber("min_views", e.target.value)}
                data-testid="filter-min-views"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#7d8590] mb-1.5">
                Min likes
              </label>
              <Input
                type="number"
                min={0}
                value={draft.min_likes ?? ""}
                onChange={(e) => setNumber("min_likes", e.target.value)}
                data-testid="filter-min-likes"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#7d8590] mb-1.5">
                Min comments
              </label>
              <Input
                type="number"
                min={0}
                value={draft.min_comments ?? ""}
                onChange={(e) => setNumber("min_comments", e.target.value)}
                data-testid="filter-min-comments"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#7d8590] mb-1.5">
                Min engagement rate (0–1)
              </label>
              <Input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={draft.min_engagement_rate ?? ""}
                onChange={(e) => setNumber("min_engagement_rate", e.target.value, true)}
                data-testid="filter-min-engagement"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#7d8590] mb-1.5">
                Max age (days, 1–365)
              </label>
              <Input
                type="number"
                min={1}
                max={365}
                value={draft.max_age_days ?? ""}
                onChange={(e) => setNumber("max_age_days", e.target.value)}
                data-testid="filter-max-age"
              />
            </div>
            <div>
              <Select
                label="Sort by"
                options={SORT_OPTIONS}
                value={draft.sort_by ?? "views_desc"}
                onChange={(v) => setField("sort_by", v as DiscoverySortBy)}
              />
            </div>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-[#21262d]">
            <div className="text-xs text-[#7d8590]" data-testid="filter-preview">
              {preview === null ? (
                <span>Adjust filters to preview matches…</span>
              ) : preview.has_cache ? (
                <span>
                  <span className="text-[#e6edf3] font-medium">
                    {preview.count.toLocaleString()}
                  </span>{" "}
                  reels match
                </span>
              ) : (
                <span className="text-[#484f58]">
                  No reels cached yet — add reference pages and run discovery
                  to populate the preview.
                </span>
              )}
            </div>
            <Button
              onClick={handleSave}
              loading={saving}
              disabled={loading || !dirty}
              data-testid="filter-save"
            >
              {dirty ? "Save filters" : "Saved"}
            </Button>
          </div>

          {error && (
            <p className="text-xs text-[#f85149]" role="alert" data-testid="filter-error">
              {error}
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}
