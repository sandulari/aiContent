"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";

interface AudioControlsProps {
  muted: boolean;
  volume: number;
  customAudioKey: string | null;
  customVolume: number;
  fadeIn: boolean;
  fadeOut: boolean;
  onMuteToggle: () => void;
  onVolumeChange: (v: number) => void;
  onAddAudio: (file: File) => void;
  onRemoveAudio: () => void;
  onCustomVolumeChange: (v: number) => void;
  onFadeInToggle: () => void;
  onFadeOutToggle: () => void;
}

function VolumeIcon({ muted }: { muted: boolean }) {
  if (muted) {
    return (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
      </svg>
    );
  }
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
    </svg>
  );
}

function MusicIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
    </svg>
  );
}

export function AudioControls({
  muted,
  volume,
  customAudioKey,
  customVolume,
  fadeIn,
  fadeOut,
  onMuteToggle,
  onVolumeChange,
  onAddAudio,
  onRemoveAudio,
  onCustomVolumeChange,
  onFadeInToggle,
  onFadeOutToggle,
}: AudioControlsProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  // Audio cap: 50 MB. Reels are short — a 30s mp3/m4a is ~1 MB, a 60s
  // wav is ~10 MB. Anything past 50 MB is almost always a wrong file.
  // Bypassing this would tie up MinIO upload + bandwidth before the
  // server's own size guard rejected.
  const MAX_AUDIO_BYTES = 50 * 1024 * 1024;
  const ALLOWED_AUDIO_TYPES = /^audio\//i;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFileError(null);
    const file = e.target.files?.[0];
    if (file) {
      if (!ALLOWED_AUDIO_TYPES.test(file.type)) {
        setFileError(`Unsupported file type: ${file.type || "unknown"}. Choose an audio file.`);
      } else if (file.size > MAX_AUDIO_BYTES) {
        setFileError(`File is ${Math.round(file.size / 1024 / 1024)} MB — limit is ${MAX_AUDIO_BYTES / 1024 / 1024} MB.`);
      } else {
        onAddAudio(file);
      }
    }
    // Reset so the same file can be re-selected
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  // Extract filename from minio key or show placeholder
  const audioFilename = customAudioKey
    ? customAudioKey.split("/").pop() || "Custom Audio"
    : null;

  return (
    <div className="bg-surface border border-border rounded-lg px-4 py-3">
      <div className="flex flex-col gap-3">
        {/* Main audio row */}
        <div className="flex items-center gap-4">
          {/* Mute Toggle */}
          <button
            onClick={onMuteToggle}
            className={`shrink-0 p-1.5 rounded transition-colors duration-150 ${
              muted
                ? "text-accent hover:text-accent/80"
                : "text-text-secondary hover:text-text-primary"
            }`}
            title={muted ? "Unmute" : "Mute"}
          >
            <VolumeIcon muted={muted} />
          </button>

          {/* Volume Slider */}
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <span className="text-xs text-text-secondary shrink-0">Volume</span>
            <input
              type="range"
              min={0}
              max={200}
              step={1}
              value={volume}
              onChange={(e) => onVolumeChange(Number(e.target.value))}
              className="flex-1 h-1.5 bg-border rounded-full appearance-none cursor-pointer accent-primary"
            />
            <span className="text-xs text-text-primary tabular-nums font-mono shrink-0 w-10 text-right">
              {volume}%
            </span>
          </div>

          {/* Add Audio Button */}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            className="shrink-0"
          >
            <MusicIcon />
            <span>Add Audio</span>
          </Button>

          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*"
            onChange={handleFileChange}
            className="hidden"
          />
        </div>

        {fileError && (
          <div className="px-3 pb-2 text-xs text-[#f87171]">{fileError}</div>
        )}

        {/* Custom Audio Track */}
        {customAudioKey && (
          <div className="flex items-center gap-4 pl-8 border-t border-border pt-3">
            <div className="flex items-center gap-2 min-w-0">
              <MusicIcon />
              <span className="text-xs text-text-primary truncate max-w-[160px]" title={audioFilename || undefined}>
                {audioFilename}
              </span>
            </div>

            <div className="flex items-center gap-2 flex-1 min-w-0">
              <span className="text-xs text-text-secondary shrink-0">Vol</span>
              <input
                type="range"
                min={0}
                max={200}
                step={1}
                value={customVolume}
                onChange={(e) => onCustomVolumeChange(Number(e.target.value))}
                className="flex-1 h-1.5 bg-border rounded-full appearance-none cursor-pointer accent-secondary"
              />
              <span className="text-xs text-text-primary tabular-nums font-mono shrink-0 w-10 text-right">
                {customVolume}%
              </span>
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={onRemoveAudio}
              className="text-danger shrink-0"
            >
              Remove
            </Button>
          </div>
        )}

        {/* Fade Controls */}
        <div className="flex items-center gap-4 pl-8">
          <button
            onClick={onFadeInToggle}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md border transition-colors duration-150 ${
              fadeIn
                ? "border-primary text-primary bg-primary/10"
                : "border-border text-text-secondary hover:text-text-primary hover:border-text-secondary"
            }`}
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            Fade In
          </button>

          <button
            onClick={onFadeOutToggle}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md border transition-colors duration-150 ${
              fadeOut
                ? "border-primary text-primary bg-primary/10"
                : "border-border text-text-secondary hover:text-text-primary hover:border-text-secondary"
            }`}
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
            </svg>
            Fade Out
          </button>
        </div>
      </div>
    </div>
  );
}
