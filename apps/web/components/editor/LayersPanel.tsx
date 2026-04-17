"use client";

import clsx from "clsx";

interface Layer {
  id: string;
  name: string;
  type: string;
  visible: boolean;
}

interface LayersPanelProps {
  layers: Layer[];
  selectedLayerId: string | null;
  onSelectLayer: (id: string) => void;
  onToggleVisibility: (id: string) => void;
}

const typeIcons: Record<string, React.ReactNode> = {
  video: (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
    </svg>
  ),
  headline: (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h8" />
    </svg>
  ),
  subtitle: (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h8" />
    </svg>
  ),
  logo: (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
};

function EyeIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L6.59 6.59m7.532 7.532l3.29 3.29M3 3l18 18" />
    </svg>
  );
}

export function LayersPanel({
  layers,
  selectedLayerId,
  onSelectLayer,
  onToggleVisibility,
}: LayersPanelProps) {
  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-text-primary">Layers</h3>
      </div>

      <div className="divide-y divide-border">
        {layers.length === 0 && (
          <div className="px-4 py-6">
            <p className="text-xs text-text-secondary text-center">No layers</p>
          </div>
        )}

        {layers.map((layer) => (
          <div
            key={layer.id}
            className={clsx(
              "flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors duration-150",
              selectedLayerId === layer.id
                ? "bg-primary/10 border-l-2 border-l-primary"
                : "hover:bg-background border-l-2 border-l-transparent"
            )}
            onClick={() => onSelectLayer(layer.id)}
          >
            {/* Type Icon */}
            <span
              className={clsx(
                "shrink-0",
                layer.visible ? "text-text-secondary" : "text-text-secondary/40"
              )}
            >
              {typeIcons[layer.type] || (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              )}
            </span>

            {/* Name */}
            <span
              className={clsx(
                "flex-1 text-sm truncate",
                layer.visible ? "text-text-primary" : "text-text-secondary/40"
              )}
            >
              {layer.name}
            </span>

            {/* Visibility Toggle */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onToggleVisibility(layer.id);
              }}
              className={clsx(
                "shrink-0 p-1 rounded transition-colors duration-150",
                layer.visible
                  ? "text-text-secondary hover:text-text-primary"
                  : "text-text-secondary/30 hover:text-text-secondary"
              )}
              title={layer.visible ? "Hide layer" : "Show layer"}
            >
              {layer.visible ? <EyeIcon /> : <EyeOffIcon />}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
