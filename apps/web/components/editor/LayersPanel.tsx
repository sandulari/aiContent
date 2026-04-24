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
  // Dynamic text-layer support. When provided (non-null), the panel
  // replaces the legacy headline+subtitle entries coming from `layers`
  // with the dynamic list and exposes add/delete/reorder controls.
  textLayers?: Layer[] | null;
  onAddTextLayer?: () => void;
  onDeleteTextLayer?: (id: string) => void;
  onMoveTextLayer?: (id: string, direction: "up" | "down") => void;
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
  handle: (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h8" />
    </svg>
  ),
  account_name: (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h8" />
    </svg>
  ),
  custom: (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h12" />
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

function ChevronUpIcon() {
  return (
    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M1 7h22M9 7V4a1 1 0 011-1h4a1 1 0 011 1v3" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
    </svg>
  );
}

export function LayersPanel({
  layers,
  selectedLayerId,
  onSelectLayer,
  onToggleVisibility,
  textLayers,
  onAddTextLayer,
  onDeleteTextLayer,
  onMoveTextLayer,
}: LayersPanelProps) {
  // When dynamic textLayers are provided and non-empty, drop the
  // legacy headline/subtitle entries from the static list so we
  // don't show duplicates. Fall back to showing them when the
  // dynamic list is null or empty (legacy exports).
  const useDynamicText = Array.isArray(textLayers) && textLayers.length > 0;
  const baseLayers = useDynamicText
    ? layers.filter((l) => l.type !== "headline" && l.type !== "subtitle")
    : layers;

  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-text-primary">Layers</h3>
      </div>

      <div className="divide-y divide-border">
        {baseLayers.length === 0 && !useDynamicText && (
          <div className="px-4 py-6">
            <p className="text-xs text-text-secondary text-center">No layers</p>
          </div>
        )}

        {baseLayers.map((layer) => (
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

            <span
              className={clsx(
                "flex-1 text-sm truncate",
                layer.visible ? "text-text-primary" : "text-text-secondary/40"
              )}
            >
              {layer.name}
            </span>

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

        {useDynamicText &&
          textLayers!.map((layer, idx) => {
            const isFirst = idx === 0;
            const isLast = idx === textLayers!.length - 1;
            return (
              <div
                key={layer.id}
                className={clsx(
                  "flex items-center gap-2 px-4 py-2.5 cursor-pointer transition-colors duration-150",
                  selectedLayerId === layer.id
                    ? "bg-primary/10 border-l-2 border-l-primary"
                    : "hover:bg-background border-l-2 border-l-transparent"
                )}
                onClick={() => onSelectLayer(layer.id)}
              >
                <span
                  className={clsx(
                    "shrink-0",
                    layer.visible ? "text-text-secondary" : "text-text-secondary/40"
                  )}
                >
                  {typeIcons[layer.type] || typeIcons.custom}
                </span>

                <span
                  className={clsx(
                    "flex-1 text-sm truncate",
                    layer.visible ? "text-text-primary" : "text-text-secondary/40"
                  )}
                >
                  {layer.name}
                </span>

                <div className="flex items-center gap-0.5 shrink-0">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (!isFirst) onMoveTextLayer?.(layer.id, "up");
                    }}
                    disabled={isFirst}
                    className={clsx(
                      "p-1 rounded transition-colors duration-150",
                      isFirst
                        ? "text-text-secondary/20 cursor-not-allowed"
                        : "text-text-secondary hover:text-text-primary"
                    )}
                    title="Move up"
                  >
                    <ChevronUpIcon />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (!isLast) onMoveTextLayer?.(layer.id, "down");
                    }}
                    disabled={isLast}
                    className={clsx(
                      "p-1 rounded transition-colors duration-150",
                      isLast
                        ? "text-text-secondary/20 cursor-not-allowed"
                        : "text-text-secondary hover:text-text-primary"
                    )}
                    title="Move down"
                  >
                    <ChevronDownIcon />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm(`Delete "${layer.name}"?`)) {
                        onDeleteTextLayer?.(layer.id);
                      }
                    }}
                    className="p-1 rounded text-text-secondary hover:text-[#f85149] transition-colors duration-150"
                    title="Delete layer"
                  >
                    <TrashIcon />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleVisibility(layer.id);
                    }}
                    className={clsx(
                      "p-1 rounded transition-colors duration-150",
                      layer.visible
                        ? "text-text-secondary hover:text-text-primary"
                        : "text-text-secondary/30 hover:text-text-secondary"
                    )}
                    title={layer.visible ? "Hide layer" : "Show layer"}
                  >
                    {layer.visible ? <EyeIcon /> : <EyeOffIcon />}
                  </button>
                </div>
              </div>
            );
          })}

        {onAddTextLayer && (
          <div className="px-3 py-2">
            <button
              onClick={onAddTextLayer}
              className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs text-[#58a6ff] border border-dashed border-[#30363d] rounded hover:border-[#58a6ff] hover:bg-[#58a6ff]/5 transition-colors"
            >
              <PlusIcon />
              Add text layer
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
