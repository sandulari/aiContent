"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import {
  api,
  ApiError,
  ScheduledReel,
  ScheduledReelUserTag,
  ScheduleCreatePayload,
  ScheduleUpdatePayload,
} from "@/lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: (result: ScheduledReel) => void;
  exportId?: string;
  editing?: ScheduledReel;
}

const MAX_CAPTION = 2200;
const MAX_HASHTAGS = 30;
const MAX_TAGS = 20;
const MIN_MINUTES_AHEAD = 2;
const MAX_DAYS_AHEAD = 60;

const HASHTAG_RE = /\B#\w+/g;

function detectTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** Format a Date into the value string expected by `<input type="datetime-local">` in local tz. */
function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** Parse a datetime-local string (interpreted in user's local tz) into an ISO8601 w/ offset. */
function localInputToIso(value: string): string | null {
  if (!value) return null;
  // The value is a naive local-time string; `new Date(...)` with that string
  // is interpreted in the browser's local tz, which is what we want.
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

function defaultInitialWhen(): string {
  const now = new Date();
  // now + 10 min, rounded up to 5-min.
  const target = new Date(now.getTime() + 10 * 60 * 1000);
  const ms = 5 * 60 * 1000;
  const rounded = new Date(Math.ceil(target.getTime() / ms) * ms);
  rounded.setSeconds(0, 0);
  return toLocalInputValue(rounded);
}

function countHashtags(text: string): number {
  const m = text.match(HASHTAG_RE);
  return m ? m.length : 0;
}

function fieldErrorsFromApi(err: ApiError): Record<string, string> {
  const out: Record<string, string> = {};
  const body: any = err.body;
  if (!body) return out;
  if (Array.isArray(body.detail)) {
    for (const d of body.detail) {
      if (d && typeof d === "object") {
        const loc = Array.isArray(d.loc) ? d.loc : [];
        // loc typically: ["body", "field"]
        const field = String(loc[loc.length - 1] ?? "form");
        out[field] = d.msg || "Invalid value";
      }
    }
  }
  return out;
}

export function ScheduleReelDialog({
  open,
  onClose,
  onSuccess,
  exportId,
  editing,
}: Props) {
  const tz = useMemo(() => detectTz(), []);
  const isEdit = Boolean(editing);

  const [when, setWhen] = useState<string>("");
  const [caption, setCaption] = useState<string>("");
  const [tags, setTags] = useState<ScheduledReelUserTag[]>([]);
  const [tagsOpen, setTagsOpen] = useState<boolean>(false);
  const [shareToFeed, setShareToFeed] = useState<boolean>(true);

  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [needsIgConnect, setNeedsIgConnect] = useState(false);

  // (Re)initialise whenever dialog opens / editing target changes.
  useEffect(() => {
    if (!open) return;
    setFieldErrors({});
    setFormError(null);
    setNeedsIgConnect(false);
    if (editing) {
      // Convert editing.scheduled_at into local input value.
      const d = new Date(editing.scheduled_at);
      setWhen(Number.isNaN(d.getTime()) ? defaultInitialWhen() : toLocalInputValue(d));
      setCaption(editing.caption ?? "");
      setTags(editing.user_tags ?? []);
      setTagsOpen(Boolean(editing.user_tags && editing.user_tags.length > 0));
      setShareToFeed(editing.share_to_feed);
    } else {
      setWhen(defaultInitialWhen());
      setCaption("");
      setTags([]);
      setTagsOpen(false);
      setShareToFeed(true);
    }
  }, [open, editing]);

  const captionLen = caption.length;
  const hashtagCount = countHashtags(caption);
  const captionOverLimit = captionLen > MAX_CAPTION;
  const hashtagsOverLimit = hashtagCount > MAX_HASHTAGS;
  const tooManyTags = tags.length > MAX_TAGS;

  const addTag = useCallback(() => {
    setTags((prev) => (prev.length >= MAX_TAGS ? prev : [...prev, { username: "" }]));
    setTagsOpen(true);
  }, []);

  const updateTag = useCallback((idx: number, username: string) => {
    setTags((prev) => prev.map((t, i) => (i === idx ? { ...t, username } : t)));
  }, []);

  const removeTag = useCallback((idx: number) => {
    setTags((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const validateLocal = useCallback((): string | null => {
    if (!when) return "Pick a date & time.";
    const whenIso = localInputToIso(when);
    if (!whenIso) return "Invalid date.";
    const whenMs = new Date(whenIso).getTime();
    const now = Date.now();
    if (whenMs < now + MIN_MINUTES_AHEAD * 60 * 1000) {
      return `Schedule must be at least ${MIN_MINUTES_AHEAD} minutes in the future.`;
    }
    if (whenMs > now + MAX_DAYS_AHEAD * 24 * 60 * 60 * 1000) {
      return `Schedule must be within ${MAX_DAYS_AHEAD} days.`;
    }
    if (captionOverLimit) return `Caption exceeds ${MAX_CAPTION} characters.`;
    if (hashtagsOverLimit) return `Too many hashtags (max ${MAX_HASHTAGS}).`;
    if (tooManyTags) return `Too many user tags (max ${MAX_TAGS}).`;
    for (const t of tags) {
      const u = (t.username || "").trim();
      if (u === "") return "Every user tag needs a username (or remove empty rows).";
      if (!/^[A-Za-z0-9._]+$/.test(u)) return `Invalid username "${u}".`;
    }
    if (!isEdit && !exportId) return "Missing export.";
    return null;
  }, [when, captionOverLimit, hashtagsOverLimit, tooManyTags, tags, isEdit, exportId]);

  const handleSubmit = useCallback(async () => {
    setFieldErrors({});
    setFormError(null);
    setNeedsIgConnect(false);

    const localErr = validateLocal();
    if (localErr) {
      setFormError(localErr);
      return;
    }
    const whenIso = localInputToIso(when);
    if (!whenIso) return;

    const normalizedTags: ScheduledReelUserTag[] = tags
      .map((t) => ({ ...t, username: (t.username || "").trim() }))
      .filter((t) => t.username !== "");

    setSubmitting(true);
    try {
      let result: ScheduledReel;
      if (isEdit && editing) {
        const patch: ScheduleUpdatePayload = {
          scheduled_at: whenIso,
          caption: caption || null,
          user_tags: normalizedTags.length ? normalizedTags : null,
          share_to_feed: shareToFeed,
        };
        result = await api.scheduled.update(editing.id, patch);
      } else {
        const payload: ScheduleCreatePayload = {
          user_export_id: exportId!,
          scheduled_at: whenIso,
          timezone: tz,
          caption: caption || null,
          user_tags: normalizedTags.length ? normalizedTags : null,
          share_to_feed: shareToFeed,
        };
        result = await api.scheduled.create(payload);
      }
      onSuccess(result);
      onClose();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          setNeedsIgConnect(true);
          setFormError(e.message || "Instagram isn't connected or can't publish.");
        } else if (e.status === 400 || e.status === 422) {
          const fe = fieldErrorsFromApi(e);
          if (Object.keys(fe).length > 0) {
            setFieldErrors(fe);
            setFormError(e.message || "Please fix the highlighted fields.");
          } else {
            setFormError(e.message || "Request was rejected.");
          }
        } else {
          setFormError(e.message || "Something went wrong.");
        }
      } else {
        setFormError((e as any)?.message || "Something went wrong.");
      }
    } finally {
      setSubmitting(false);
    }
  }, [
    validateLocal,
    when,
    tags,
    isEdit,
    editing,
    caption,
    shareToFeed,
    exportId,
    tz,
    onSuccess,
    onClose,
  ]);

  return (
    <Modal
      isOpen={open}
      onClose={submitting ? () => {} : onClose}
      title={isEdit ? "Edit scheduled reel" : "Schedule reel"}
      className="max-w-lg"
    >
      <div className="space-y-5">
        {/* Date/time */}
        <div>
          <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">
            When to publish
          </label>
          <input
            type="datetime-local"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            className={
              "w-full h-11 px-4 text-sm bg-[#161b22] text-[#c9d1d9] border rounded-lg " +
              "focus:outline-none " +
              (fieldErrors["scheduled_at"]
                ? "border-[#dc2626] focus:border-[#dc2626]"
                : "border-[#21262d] focus:border-[#58a6ff]")
            }
            disabled={submitting}
          />
          <p className="mt-1.5 text-[11px] text-[#7d8590]">
            Your local time: <span className="text-[#c9d1d9]">{tz}</span>
          </p>
          {fieldErrors["scheduled_at"] && (
            <p className="mt-1 text-xs text-[#dc2626]">{fieldErrors["scheduled_at"]}</p>
          )}
        </div>

        {/* Caption */}
        <div>
          <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">
            Caption
          </label>
          <textarea
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            rows={5}
            className={
              "w-full px-4 py-3 text-sm bg-[#161b22] text-[#c9d1d9] border rounded-lg " +
              "placeholder:text-[#484f58] focus:outline-none " +
              (fieldErrors["caption"] || captionOverLimit || hashtagsOverLimit
                ? "border-[#dc2626] focus:border-[#dc2626]"
                : "border-[#21262d] focus:border-[#58a6ff]")
            }
            placeholder="Write your caption… include hashtags like #reels"
            disabled={submitting}
          />
          <div className="mt-1.5 flex items-center justify-between text-[11px]">
            <span className={hashtagsOverLimit ? "text-[#dc2626]" : "text-[#7d8590]"}>
              {hashtagCount} / {MAX_HASHTAGS} hashtags
            </span>
            <span className={captionOverLimit ? "text-[#dc2626]" : "text-[#7d8590]"}>
              {captionLen} / {MAX_CAPTION}
            </span>
          </div>
          {fieldErrors["caption"] && (
            <p className="mt-1 text-xs text-[#dc2626]">{fieldErrors["caption"]}</p>
          )}
        </div>

        {/* User tags */}
        <div>
          {!tagsOpen && tags.length === 0 ? (
            <button
              type="button"
              onClick={addTag}
              disabled={submitting}
              className="text-[11px] text-[#58a6ff] hover:underline disabled:opacity-40"
            >
              + Add user tag
            </button>
          ) : (
            <div>
              <label className="block text-[11px] font-medium text-[#555] uppercase tracking-wider mb-2">
                User tags ({tags.length} / {MAX_TAGS})
              </label>
              <div className="space-y-2">
                {tags.map((t, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <span className="text-[#7d8590] text-sm">@</span>
                    <input
                      type="text"
                      value={t.username}
                      onChange={(e) => updateTag(idx, e.target.value.replace(/^@+/, ""))}
                      placeholder="username"
                      className="flex-1 h-9 px-3 text-sm bg-[#161b22] text-[#c9d1d9] border border-[#21262d] rounded-lg focus:outline-none focus:border-[#58a6ff] placeholder:text-[#484f58]"
                      disabled={submitting}
                    />
                    <button
                      type="button"
                      onClick={() => removeTag(idx)}
                      disabled={submitting}
                      className="text-[#7d8590] hover:text-[#dc2626] text-xs px-2"
                      aria-label="Remove tag"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={addTag}
                disabled={submitting || tags.length >= MAX_TAGS}
                className="mt-2 text-[11px] text-[#58a6ff] hover:underline disabled:opacity-40"
              >
                + Add another
              </button>
              {fieldErrors["user_tags"] && (
                <p className="mt-1 text-xs text-[#dc2626]">{fieldErrors["user_tags"]}</p>
              )}
            </div>
          )}
        </div>

        {/* Share to feed */}
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={shareToFeed}
            onChange={(e) => setShareToFeed(e.target.checked)}
            disabled={submitting}
            className="w-4 h-4 accent-[#238636]"
          />
          <span className="text-sm text-[#c9d1d9]">Also share to feed</span>
        </label>

        {/* Form-level errors */}
        {formError && (
          <div className="p-3 text-xs text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded">
            <p>{formError}</p>
            {needsIgConnect && (
              <Link
                href="/settings/instagram"
                className="mt-1 inline-block text-[#58a6ff] hover:underline"
              >
                Go to Instagram settings →
              </Link>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            loading={submitting}
            disabled={
              submitting ||
              captionOverLimit ||
              hashtagsOverLimit ||
              tooManyTags
            }
          >
            {isEdit ? "Save changes" : "Schedule reel"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default ScheduleReelDialog;
