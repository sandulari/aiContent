"use client";

import { useEffect, useRef, useCallback, useState, useLayoutEffect } from "react";

interface CanvasLayer {
  id: string;
  type: string;
  visible: boolean;
  props: Record<string, any>;
}

interface CanvasProps {
  layers: CanvasLayer[];
  selectedLayerId: string | null;
  videoUrl: string | null;
  logoUrl?: string | null;
  videoRef: React.RefObject<HTMLVideoElement>;
  onSelectLayer: (id: string) => void;
  onUpdateLayerProps: (id: string, props: Record<string, any>) => void;
  backgroundColor?: string;
}

// Design canvas (the logical 9:16 reel size used for saving)
const CANVAS_W = 360;
const CANVAS_H = 640;

type HandlePos = "tl" | "tr" | "bl" | "br" | "t" | "b" | "l" | "r" | "move";

export function Canvas({
  layers,
  selectedLayerId,
  videoUrl,
  logoUrl,
  videoRef,
  onSelectLayer,
  onUpdateLayerProps,
  backgroundColor,
}: CanvasProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{
    id: string;
    handle: HandlePos;
    startX: number;
    startY: number;
    orig: Record<string, any>;
  } | null>(null);
  // Which text layer is in inline-edit mode (null = none)
  const [editingText, setEditingText] = useState<string | null>(null);
  // Active alignment guides during drag (Canva-style snap lines)
  const [guides, setGuides] = useState<{ v: boolean; h: boolean }>({
    v: false,
    h: false,
  });
  // How close to center counts as "snap" — 1.8% of each axis
  const SNAP_THRESHOLD = 1.8;

  // ── Responsive scaling ──────────────────────────────────────────────
  // Measure the available wrapper size and pick the largest integer-ish
  // scale that still fits the logical 360×640 canvas inside. No more
  // needing to scroll on small monitors.
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const compute = () => {
      const rect = el.getBoundingClientRect();
      const padX = 48; // breathing room
      const padY = 24;
      const maxW = Math.max(180, rect.width - padX);
      const maxH = Math.max(320, rect.height - padY);
      const next = Math.min(maxW / CANVAS_W, maxH / CANVAS_H, 2.5);
      setScale(Math.max(0.6, +next.toFixed(3)));
    };
    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    window.addEventListener("resize", compute);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", compute);
    };
  }, []);

  const getLayer = (id: string) => layers.find((l) => l.id === id);

  // ── Drag ─────────────────────────────────────────────────────────────
  // Important: all coordinate math happens in the *logical* 360×640 space.
  // The on-screen scale only visually zooms the container, so we divide
  // mouse deltas by `scale` before applying them to layer props.
  const startDrag = (e: React.MouseEvent, id: string, handle: HandlePos) => {
    e.stopPropagation();
    e.preventDefault();
    onSelectLayer(id);
    const layer = getLayer(id);
    if (!layer) return;
    setDrag({
      id,
      handle,
      startX: e.clientX,
      startY: e.clientY,
      orig: { ...layer.props },
    });
  };

  const onMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!drag) return;
      const dx = (e.clientX - drag.startX) / scale;
      const dy = (e.clientY - drag.startY) / scale;
      const o = drag.orig;

      if (drag.id === "video") {
        const origW = o.w ?? CANVAS_W;
        const origH = o.h ?? CANVAS_H;
        const origX = o.x ?? 0;
        const origY = o.y ?? 0;
        // Clamp so the user can't fling the video off-canvas or blow
        // it up past 3x the canvas (matches the exporter-side clamps
        // in lib/video_proc.py _build_video_filter_chain).
        const MIN_WH = 50;
        const MAX_W = CANVAS_W * 3;
        const MAX_H = CANVAS_H * 3;
        const clampW = (w: number) => Math.max(MIN_WH, Math.min(MAX_W, w));
        const clampH = (h: number) => Math.max(MIN_WH, Math.min(MAX_H, h));
        const clampX = (x: number, w: number) =>
          Math.max(-w + 40, Math.min(CANVAS_W - 40, x));
        const clampY = (y: number, h: number) =>
          Math.max(-h + 40, Math.min(CANVAS_H - 40, y));
        const dispatch = (next: { x?: number; y?: number; w?: number; h?: number }) => {
          const w = next.w !== undefined ? clampW(next.w) : undefined;
          const h = next.h !== undefined ? clampH(next.h) : undefined;
          const effW = w ?? origW;
          const effH = h ?? origH;
          const out: Record<string, number> = {};
          if (w !== undefined) out.w = w;
          if (h !== undefined) out.h = h;
          if (next.x !== undefined) out.x = clampX(next.x, effW);
          if (next.y !== undefined) out.y = clampY(next.y, effH);
          onUpdateLayerProps("video", out);
        };
        switch (drag.handle) {
          case "move":
            dispatch({ x: origX + dx, y: origY + dy });
            break;
          case "r":
            dispatch({ w: origW + dx });
            break;
          case "l":
            dispatch({ w: origW - dx, x: origX + dx });
            break;
          case "b":
            dispatch({ h: origH + dy });
            break;
          case "t":
            dispatch({ h: origH - dy, y: origY + dy });
            break;
          case "br":
            dispatch({ w: origW + dx, h: origH + dy });
            break;
          case "bl":
            dispatch({ w: origW - dx, h: origH + dy, x: origX + dx });
            break;
          case "tr":
            dispatch({ w: origW + dx, h: origH - dy, y: origY + dy });
            break;
          case "tl":
            dispatch({
              w: origW - dx,
              h: origH - dy,
              x: origX + dx,
              y: origY + dy,
            });
            break;
        }
      } else {
        if (drag.handle === "move") {
          let nx = Math.max(0, Math.min(100, (o.x || 50) + (dx / CANVAS_W) * 100));
          let ny = Math.max(0, Math.min(100, (o.y || 50) + (dy / CANVAS_H) * 100));
          // Canva-style center snap: within SNAP_THRESHOLD% of 50% on
          // either axis, force to exactly 50 and light up the guide.
          const nearV = Math.abs(nx - 50) < SNAP_THRESHOLD;
          const nearH = Math.abs(ny - 50) < SNAP_THRESHOLD;
          if (nearV) nx = 50;
          if (nearH) ny = 50;
          setGuides({ v: nearV, h: nearH });
          onUpdateLayerProps(drag.id, { x: nx, y: ny });
        } else {
          const layer = getLayer(drag.id);
          if (layer?.type === "logo") {
            // Logo corner handle = uniform scale
            if (drag.handle === "r" || drag.handle === "br") {
              onUpdateLayerProps(drag.id, {
                size: Math.max(20, Math.min(260, (o.size || 56) + dx * 0.5)),
              });
            }
          } else {
            // Text box width handles. The box stays centered on its
            // anchor point (Canva-style), so the width grows
            // symmetrically from the midpoint. `r` handle = positive
            // dx grows the box; `l` handle = negative dx grows it.
            const origW = o.w ?? CANVAS_W * 0.85;
            let newW = origW;
            if (drag.handle === "r") {
              newW = origW + dx * 2;
            } else if (drag.handle === "l") {
              newW = origW - dx * 2;
            }
            newW = Math.max(60, Math.min(CANVAS_W - 8, newW));
            onUpdateLayerProps(drag.id, { w: newW });
          }
        }
      }
    },
    [drag, scale, onUpdateLayerProps]
  );

  const onMouseUp = useCallback(() => {
    setDrag(null);
    setGuides({ v: false, h: false });
  }, []);

  useEffect(() => {
    if (!drag) return;
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [drag, onMouseMove, onMouseUp]);

  const videoLayer = getLayer("video");
  const logoLayer = getLayer("logo");
  const headlineLayer = getLayer("headline");
  const subtitleLayer = getLayer("subtitle");
  const isSel = (id: string) => selectedLayerId === id;

  const vx = videoLayer?.props.x ?? 0;
  const vy = videoLayer?.props.y ?? 0;
  const vw = videoLayer?.props.w ?? CANVAS_W;
  const vh = videoLayer?.props.h ?? CANVAS_H;

  const handleCursors: Record<HandlePos, string> = {
    tl: "nwse-resize",
    tr: "nesw-resize",
    bl: "nesw-resize",
    br: "nwse-resize",
    t: "ns-resize",
    b: "ns-resize",
    l: "ew-resize",
    r: "ew-resize",
    move: "grab",
  };

  const Handle = ({ pos, x, y }: { pos: HandlePos; x: number; y: number }) => (
    <div
      onMouseDown={(e) => startDrag(e, "video", pos)}
      className="absolute w-3 h-3 bg-[#58a6ff] border-2 border-[#0d1117] rounded-sm z-40"
      style={{ left: x - 6, top: y - 6, cursor: handleCursors[pos] }}
    />
  );

  const EdgeHandle = ({ pos, style }: { pos: HandlePos; style: React.CSSProperties }) => (
    <div
      onMouseDown={(e) => startDrag(e, "video", pos)}
      className="absolute z-40 bg-[#58a6ff]/20 hover:bg-[#58a6ff]/50"
      style={{ ...style, cursor: handleCursors[pos] }}
    />
  );

  const textStyle = (p: Record<string, any>): React.CSSProperties => ({
    fontFamily: p.fontFamily || "Inter",
    fontSize: `${p.fontSize || 48}px`,
    fontWeight: p.fontWeight || 700,
    color: p.color || "#FFFFFF",
    textAlign: (p.alignment || "center") as any,
    letterSpacing: `${p.letterSpacing || 0}px`,
    textTransform: p.textTransform !== "none" ? p.textTransform : undefined,
    opacity: (p.opacity || 100) / 100,
    textShadow: p.shadowEnabled
      ? `${p.shadowX || 0}px ${p.shadowY || 2}px ${p.shadowBlur || 6}px ${p.shadowColor || "#000"}`
      : "none",
    WebkitTextStroke: p.strokeEnabled
      ? `${p.strokeWidth || 1}px ${p.strokeColor || "#000"}`
      : undefined,
    lineHeight: 1.15,
    whiteSpace: "pre-wrap",
  });

  // ── Inline text editing ─────────────────────────────────────────────
  // Double-click any text layer to enter contenteditable mode. Enter
  // commits and exits; Escape cancels; blur commits.
  const commitTextEdit = (layerId: string, el: HTMLDivElement | null) => {
    if (!el) return;
    const newText = el.innerText.trim();
    onUpdateLayerProps(layerId, { text: newText });
    setEditingText(null);
  };

  const handleTextKeyDown = (e: React.KeyboardEvent<HTMLDivElement>, layerId: string) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      commitTextEdit(layerId, e.currentTarget);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setEditingText(null);
    }
  };

  // ── Root background click: clear selection when the user clicks
  // empty canvas. Passing an empty string so the Properties panel
  // switches back to its "click an element" prompt — not auto-selecting
  // the video layer, which used to silently hijack the properties.
  const handleCanvasBgClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      onSelectLayer("");
    }
  };

  return (
    <div
      ref={wrapperRef}
      className="flex items-center justify-center w-full h-full overflow-hidden"
    >
      <div
        ref={containerRef}
        className="relative select-none"
        style={{
          width: CANVAS_W,
          height: CANVAS_H,
          background: backgroundColor || "#000",
          borderRadius: 10,
          boxShadow: "0 0 0 1px #30363d, 0 8px 60px rgba(0,0,0,0.4)",
          overflow: "hidden",
          cursor: drag ? "grabbing" : "default",
          transform: `scale(${scale})`,
          transformOrigin: "center center",
        }}
        onClick={handleCanvasBgClick}
      >
        {/* ── Video layer ───────────────────────────────────────────── */}
        {videoLayer?.visible && (
          <>
            {videoUrl ? (
              <div
                onMouseDown={(e) => startDrag(e, "video", "move")}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectLayer("video");
                }}
                className="absolute"
                style={{
                  left: vx,
                  top: vy,
                  width: vw,
                  height: vh,
                  cursor:
                    drag?.id === "video" && drag.handle === "move" ? "grabbing" : "grab",
                }}
              >
                <video
                  ref={videoRef}
                  src={videoUrl}
                  className="w-full h-full pointer-events-none"
                  style={{
                    objectFit: "fill",
                    transform: videoLayer.props.flipH ? "scaleX(-1)" : undefined,
                  }}
                  playsInline
                  muted
                />
              </div>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center bg-[#0d1117]">
                <div className="text-center">
                  <svg
                    className="w-12 h-12 mx-auto text-[#30363d] mb-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={1}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
                    />
                  </svg>
                  <p className="text-xs text-[#484f58]">No video loaded</p>
                </div>
              </div>
            )}
            {isSel("video") && videoUrl && (
              <>
                <Handle pos="tl" x={vx} y={vy} />
                <Handle pos="tr" x={vx + vw} y={vy} />
                <Handle pos="bl" x={vx} y={vy + vh} />
                <Handle pos="br" x={vx + vw} y={vy + vh} />
                <EdgeHandle
                  pos="t"
                  style={{ left: vx + 12, top: vy - 3, width: vw - 24, height: 6 }}
                />
                <EdgeHandle
                  pos="b"
                  style={{ left: vx + 12, top: vy + vh - 3, width: vw - 24, height: 6 }}
                />
                <EdgeHandle
                  pos="l"
                  style={{ left: vx - 3, top: vy + 12, width: 6, height: vh - 24 }}
                />
                <EdgeHandle
                  pos="r"
                  style={{ left: vx + vw - 3, top: vy + 12, width: 6, height: vh - 24 }}
                />
                <div
                  className="absolute pointer-events-none border-2 border-[#58a6ff]"
                  style={{ left: vx, top: vy, width: vw, height: vh }}
                />
                <div
                  className="absolute z-50 pointer-events-none"
                  style={{ left: vx + vw + 8, top: vy + vh / 2 - 10 }}
                >
                  <span className="text-[10px] text-[#58a6ff] bg-[#0d1117]/90 px-1.5 py-0.5 rounded whitespace-nowrap">
                    {Math.round(vw)} x {Math.round(vh)}
                  </span>
                </div>
              </>
            )}
          </>
        )}

        {/* ── Logo ───────────────────────────────────────────────────── */}
        {logoLayer?.visible &&
          (() => {
            const lp = logoLayer.props;
            const size = lp.size || 56;
            const shape = (lp.shape as string) || "circle";
            const radius =
              shape === "circle" ? "50%" : shape === "rounded" ? "12px" : "0px";
            const objectFit = (lp.objectFit as string) || "contain";
            const borderWidth = lp.borderWidth ?? 0;
            const borderColor = lp.borderColor || "transparent";
            const showBg = lp.transparent === false;
            return (
              <div
                onMouseDown={(e) => startDrag(e, "logo", "move")}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectLayer("logo");
                }}
                className="absolute z-20"
                style={{
                  width: size,
                  height: size,
                  left: `calc(${lp.x ?? 50}% - ${size / 2}px)`,
                  top: `calc(${lp.y ?? 6}% - ${size / 2}px)`,
                  opacity: (lp.opacity ?? 100) / 100,
                  cursor: drag?.id === "logo" ? "grabbing" : "grab",
                }}
              >
                <div
                  className="w-full h-full flex items-center justify-center overflow-hidden"
                  style={{
                    borderRadius: radius,
                    background: showBg ? lp.backgroundColor || "#1a1a2e" : "transparent",
                    border:
                      borderWidth > 0 ? `${borderWidth}px solid ${borderColor}` : "none",
                    boxShadow: isSel("logo") ? "0 0 0 2px #58a6ff" : "none",
                  }}
                >
                  {logoUrl ? (
                    <img
                      src={logoUrl}
                      alt="Logo"
                      className="w-full h-full pointer-events-none"
                      style={{ objectFit: objectFit as any, borderRadius: radius }}
                    />
                  ) : (
                    <span className="text-[9px] text-[#8b949e] font-medium pointer-events-none">
                      LOGO
                    </span>
                  )}
                </div>
                {isSel("logo") && (
                  <div
                    onMouseDown={(e) => startDrag(e, "logo", "br")}
                    className="absolute -bottom-1 -right-1 w-4 h-4 bg-[#58a6ff] rounded-full cursor-nwse-resize border-2 border-[#0d1117]"
                  />
                )}
              </div>
            );
          })()}

        {/* ── Text layers (headline + subtitle) ────────────────────────
            Canva-style text boxes: each has an EXPLICIT fixed width
            (logical pixels, saved per-layer as `w`). Dragging moves the
            box's center; it never changes the box's width or how the
            text wraps inside. Resize handle on the right edge drags
            the box's width (not font size). Font size is controlled
            separately in the properties panel. */}
        {[headlineLayer, subtitleLayer].map((layer) => {
          if (!layer?.visible) return null;
          const isHeadline = layer === headlineLayer;
          const layerId = isHeadline ? "headline" : "subtitle";
          const p = layer.props;
          const isEditing = editingText === layerId;
          const style = textStyle(p);
          // Default text-box width is 85% of the canvas. Users can
          // resize via the edge handle; the value persists in the
          // layer's `w` prop so moving never reflows the text.
          const boxW = Math.max(60, Math.min(CANVAS_W - 8, p.w ?? CANVAS_W * 0.85));

          return (
            <div
              key={layerId}
              onMouseDown={(e) => {
                if (isEditing) return;
                startDrag(e, layerId, "move");
              }}
              onClick={(e) => {
                e.stopPropagation();
                onSelectLayer(layerId);
              }}
              onDoubleClick={(e) => {
                e.stopPropagation();
                onSelectLayer(layerId);
                setEditingText(layerId);
              }}
              className="absolute z-30"
              style={{
                left: `${p.x ?? 50}%`,
                top: `${p.y ?? (isHeadline ? 68 : 80)}%`,
                transform: "translate(-50%, -50%)",
                width: boxW,
                cursor: isEditing
                  ? "text"
                  : drag?.id === layerId
                    ? "grabbing"
                    : "grab",
              }}
            >
              <div
                contentEditable={isEditing}
                suppressContentEditableWarning
                onBlur={(e) => commitTextEdit(layerId, e.currentTarget)}
                onKeyDown={(e) => handleTextKeyDown(e, layerId)}
                style={{
                  ...style,
                  padding: "4px 8px",
                  borderRadius: 4,
                  border: isSel(layerId)
                    ? isEditing
                      ? "1px solid #58a6ff"
                      : "1px dashed #58a6ff"
                    : "1px dashed transparent",
                  background: isSel(layerId) ? "rgba(88,166,255,0.06)" : "transparent",
                  outline: "none",
                  // block-level, full width of the parent box — text
                  // wraps within `boxW` regardless of position.
                  width: "100%",
                  boxSizing: "border-box",
                  wordBreak: "break-word",
                }}
                ref={(el) => {
                  if (el && isEditing && document.activeElement !== el) {
                    el.focus();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    const sel = window.getSelection();
                    sel?.removeAllRanges();
                    sel?.addRange(range);
                  }
                }}
              >
                {p.text || (isHeadline ? "Headline" : "Subtitle")}
              </div>
              {isSel(layerId) && !isEditing && (
                <>
                  {/* Width resize handles on the left + right edges */}
                  <div
                    onMouseDown={(e) => startDrag(e, layerId, "l")}
                    className="absolute top-1/2 -translate-y-1/2 -left-1.5 w-3 h-6 bg-[#58a6ff] rounded cursor-ew-resize border-2 border-[#0d1117]"
                    title="Drag to resize box width"
                  />
                  <div
                    onMouseDown={(e) => startDrag(e, layerId, "r")}
                    className="absolute top-1/2 -translate-y-1/2 -right-1.5 w-3 h-6 bg-[#58a6ff] rounded cursor-ew-resize border-2 border-[#0d1117]"
                    title="Drag to resize box width"
                  />
                </>
              )}
            </div>
          );
        })}

        {/* ── Alignment guides (Canva-style) ───────────────────────
            Magenta dashed lines through the canvas center, only
            visible while dragging and within the snap threshold. */}
        {drag && drag.handle === "move" && drag.id !== "video" && (
          <>
            {guides.v && (
              <div
                className="absolute pointer-events-none z-[45]"
                style={{
                  left: "50%",
                  top: 0,
                  bottom: 0,
                  width: 0,
                  borderLeft: "1px dashed #ff3fa4",
                  boxShadow: "0 0 4px rgba(255, 63, 164, 0.6)",
                  transform: "translateX(-0.5px)",
                }}
              />
            )}
            {guides.h && (
              <div
                className="absolute pointer-events-none z-[45]"
                style={{
                  top: "50%",
                  left: 0,
                  right: 0,
                  height: 0,
                  borderTop: "1px dashed #ff3fa4",
                  boxShadow: "0 0 4px rgba(255, 63, 164, 0.6)",
                  transform: "translateY(-0.5px)",
                }}
              />
            )}
          </>
        )}

        {/* ── Status hint ──────────────────────────────────────────── */}
        {selectedLayerId && !drag && editingText === null && (
          <div className="absolute bottom-2 left-0 right-0 text-center pointer-events-none">
            <span className="text-[9px] text-[#58a6ff]/80 bg-[#0d1117]/80 px-2 py-0.5 rounded">
              {selectedLayerId === "video"
                ? "Drag to move · Corners to resize"
                : selectedLayerId === "logo"
                  ? "Drag to move · Blue dot to resize"
                  : "Drag to move · Double-click to edit text"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
