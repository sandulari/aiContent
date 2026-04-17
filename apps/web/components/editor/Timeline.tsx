"use client";

import { useRef, useCallback, useState } from "react";

interface TimelineProps {
  duration: number;
  currentTime: number;
  trimStart: number;
  trimEnd: number;
  isPlaying: boolean;
  onSeek: (time: number) => void;
  onTrimChange: (start: number, end: number) => void;
  onPlayPause: () => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 10);
  return `${m}:${s.toString().padStart(2, "0")}.${ms}`;
}

function PlayIcon() {
  return (
    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
    </svg>
  );
}

export function Timeline({
  duration,
  currentTime,
  trimStart,
  trimEnd,
  isPlaying,
  onSeek,
  onTrimChange,
  onPlayPause,
}: TimelineProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<"scrub" | "start" | "end" | null>(null);

  const getTimeFromX = useCallback(
    (clientX: number): number => {
      if (!trackRef.current || duration <= 0) return 0;
      const rect = trackRef.current.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      return ratio * duration;
    },
    [duration]
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent, type: "scrub" | "start" | "end") => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(type);
      (e.target as HTMLElement).setPointerCapture(e.pointerId);

      const time = getTimeFromX(e.clientX);
      if (type === "scrub") {
        onSeek(Math.max(trimStart, Math.min(trimEnd, time)));
      } else if (type === "start") {
        onTrimChange(Math.min(time, trimEnd - 0.1), trimEnd);
      } else {
        onTrimChange(trimStart, Math.max(time, trimStart + 0.1));
      }
    },
    [getTimeFromX, trimStart, trimEnd, onSeek, onTrimChange]
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging) return;
      const time = getTimeFromX(e.clientX);

      if (dragging === "scrub") {
        onSeek(Math.max(trimStart, Math.min(trimEnd, time)));
      } else if (dragging === "start") {
        const newStart = Math.max(0, Math.min(time, trimEnd - 0.1));
        onTrimChange(newStart, trimEnd);
      } else if (dragging === "end") {
        const newEnd = Math.min(duration, Math.max(time, trimStart + 0.1));
        onTrimChange(trimStart, newEnd);
      }
    },
    [dragging, getTimeFromX, trimStart, trimEnd, duration, onSeek, onTrimChange]
  );

  const handlePointerUp = useCallback(() => {
    setDragging(null);
  }, []);

  const trimStartPct = duration > 0 ? (trimStart / duration) * 100 : 0;
  const trimEndPct = duration > 0 ? (trimEnd / duration) * 100 : 100;
  const currentPct = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className="bg-surface border border-border rounded-lg px-4 py-3">
      <div className="flex items-center gap-4">
        {/* Play/Pause */}
        <button
          onClick={onPlayPause}
          className="shrink-0 w-8 h-8 flex items-center justify-center rounded-full bg-primary text-white hover:bg-primary/90 transition-colors duration-150"
        >
          {isPlaying ? <PauseIcon /> : <PlayIcon />}
        </button>

        {/* Time Display */}
        <div className="shrink-0 text-xs text-text-secondary font-mono tabular-nums min-w-[100px]">
          <span className="text-text-primary">{formatTime(currentTime)}</span>
          <span className="mx-1">/</span>
          <span>{formatTime(duration)}</span>
        </div>

        {/* Scrubber Track */}
        <div
          ref={trackRef}
          className="relative flex-1 h-10 select-none cursor-pointer"
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          {/* Full track background */}
          <div className="absolute top-1/2 -translate-y-1/2 left-0 right-0 h-2 bg-border rounded-full" />

          {/* Dimmed before trim start */}
          <div
            className="absolute top-1/2 -translate-y-1/2 left-0 h-2 bg-border/60 rounded-l-full"
            style={{ width: `${trimStartPct}%` }}
          />

          {/* Active trim region */}
          <div
            className="absolute top-1/2 -translate-y-1/2 h-2 bg-primary/30 rounded-sm"
            style={{
              left: `${trimStartPct}%`,
              width: `${trimEndPct - trimStartPct}%`,
            }}
            onPointerDown={(e) => handlePointerDown(e, "scrub")}
          />

          {/* Dimmed after trim end */}
          <div
            className="absolute top-1/2 -translate-y-1/2 right-0 h-2 bg-border/60 rounded-r-full"
            style={{ width: `${100 - trimEndPct}%` }}
          />

          {/* Trim Start Handle */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-6 bg-accent rounded-sm cursor-ew-resize hover:bg-accent/80 transition-colors duration-150 -translate-x-1/2 z-10"
            style={{ left: `${trimStartPct}%` }}
            onPointerDown={(e) => handlePointerDown(e, "start")}
            title={`Trim start: ${formatTime(trimStart)}`}
          />

          {/* Trim End Handle */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-6 bg-accent rounded-sm cursor-ew-resize hover:bg-accent/80 transition-colors duration-150 -translate-x-1/2 z-10"
            style={{ left: `${trimEndPct}%` }}
            onPointerDown={(e) => handlePointerDown(e, "end")}
            title={`Trim end: ${formatTime(trimEnd)}`}
          />

          {/* Playhead */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-0.5 h-8 bg-text-primary z-20 pointer-events-none"
            style={{ left: `${currentPct}%` }}
          >
            <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-2.5 h-2.5 bg-text-primary rounded-full" />
          </div>
        </div>

        {/* Trim display */}
        <div className="shrink-0 text-xs text-text-secondary font-mono tabular-nums">
          {formatTime(trimStart)} - {formatTime(trimEnd)}
        </div>
      </div>
    </div>
  );
}
