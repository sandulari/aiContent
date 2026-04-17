"use client";

import { useCallback } from "react";
import { Select } from "@/components/ui/select";

interface SelectedLayer {
  id: string;
  type: string;
  props: Record<string, any>;
}

interface PropertiesPanelProps {
  selectedLayer: SelectedLayer | null;
  onUpdateProps: (layerId: string, props: Record<string, any>) => void;
}

const FONTS = [
  { value: "Inter", label: "Inter" },
  { value: "Roboto", label: "Roboto" },
  { value: "Open Sans", label: "Open Sans" },
  { value: "Lato", label: "Lato" },
  { value: "Poppins", label: "Poppins" },
  { value: "Montserrat", label: "Montserrat" },
  { value: "Oswald", label: "Oswald" },
  { value: "Playfair Display", label: "Playfair Display" },
  { value: "Bebas Neue", label: "Bebas Neue" },
  { value: "Raleway", label: "Raleway" },
  { value: "Nunito", label: "Nunito" },
  { value: "Anton", label: "Anton" },
  { value: "DM Sans", label: "DM Sans" },
  { value: "Space Grotesk", label: "Space Grotesk" },
  { value: "Outfit", label: "Outfit" },
];

const WEIGHTS = [
  { value: "300", label: "Light (300)" },
  { value: "400", label: "Regular (400)" },
  { value: "500", label: "Medium (500)" },
  { value: "600", label: "Semi Bold (600)" },
  { value: "700", label: "Bold (700)" },
  { value: "800", label: "Extra Bold (800)" },
  { value: "900", label: "Black (900)" },
];

const ALIGNS = [
  { value: "left", label: "Left" },
  { value: "center", label: "Center" },
  { value: "right", label: "Right" },
];

const TRANSFORMS = [
  { value: "none", label: "Normal" },
  { value: "uppercase", label: "UPPERCASE" },
  { value: "lowercase", label: "lowercase" },
];

const SWATCHES = ["#ffffff","#c9d1d9","#8b949e","#000000","#58a6ff","#79c0ff","#f78166","#d29922","#3fb950","#f85149","#bc8cff","#ff7b72"];

function Label({ children }: { children: React.ReactNode }) {
  return <span className="block text-[11px] text-[#8b949e] mb-1">{children}</span>;
}

function Slider({ label, value, min, max, step = 1, unit = "", onChange }: {
  label: string; value: number; min: number; max: number; step?: number; unit?: string; onChange: (v: number) => void;
}) {
  const span = max - min;
  const pct = span > 0 ? Math.max(0, Math.min(100, ((value - min) / span) * 100)) : 0;
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <span className="text-[11px] text-[#8b949e]">{label}</span>
        <span className="text-[11px] text-[#c9d1d9] tabular-nums">{value}{unit}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ ["--fill-pct" as any]: `${pct}%` }}
      />
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-[#8b949e]">{label}</span>
      <button onClick={() => onChange(!checked)}
        className={`relative w-8 rounded-full transition-colors ${checked ? "bg-[#58a6ff]" : "bg-[#30363d]"}`}
        style={{ height: 18, minWidth: 32 }}>
        <span className={`absolute top-0.5 left-0.5 w-3.5 h-3.5 rounded-full bg-white transition-transform ${checked ? "translate-x-3.5" : ""}`}
          style={{ width: 14, height: 14 }} />
      </button>
    </div>
  );
}

function NumInput({ label, value, onChange, min, max }: { label: string; value: number; onChange: (v: number) => void; min?: number; max?: number }) {
  return (
    <div>
      <Label>{label}</Label>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") { onChange(0); return; }
          const n = Number(raw);
          if (!Number.isFinite(n)) return;
          let clamped = n;
          if (typeof min === "number") clamped = Math.max(min, clamped);
          if (typeof max === "number") clamped = Math.min(max, clamped);
          onChange(clamped);
        }}
        className="w-full px-2 py-1 text-xs bg-[#0d1117] text-[#c9d1d9] border border-[#30363d] rounded focus:outline-none focus:border-[#58a6ff]"
      />
    </div>
  );
}

// ─── Text Controls (headline / subtitle) ─────────────────────────────────
// Uses FLAT prop names matching Canvas: fontFamily, fontSize, fontWeight, color,
// alignment, letterSpacing, textTransform, shadowEnabled, shadowX, shadowY,
// shadowBlur, shadowColor, strokeEnabled, strokeWidth, strokeColor, opacity, x, y

function TextControls({ p, update }: { p: Record<string, any>; update: (props: Record<string, any>) => void }) {
  return (
    <div className="space-y-3">
      <Select label="Font" options={FONTS} value={p.fontFamily || "Inter"} onChange={(v) => update({ fontFamily: v })} />
      <Slider label="Size" value={p.fontSize ?? 48} min={12} max={120} unit="px" onChange={(v) => update({ fontSize: v })} />
      <Select label="Weight" options={WEIGHTS} value={String(p.fontWeight ?? 700)} onChange={(v) => update({ fontWeight: Number(v) })} />

      <div>
        <Label>Color</Label>
        <div className="flex items-center gap-2 mb-2">
          <input type="color" value={p.color || "#ffffff"} onChange={(e) => update({ color: e.target.value })}
            className="w-7 h-7 rounded border border-[#30363d] cursor-pointer bg-transparent" />
          <input type="text" value={p.color || "#ffffff"} onChange={(e) => update({ color: e.target.value })}
            className="flex-1 px-2 py-1 text-xs bg-[#0d1117] text-[#c9d1d9] border border-[#30363d] rounded focus:outline-none focus:border-[#58a6ff] font-mono" />
        </div>
        <div className="flex flex-wrap gap-1">
          {SWATCHES.map((c) => (
            <button key={c} onClick={() => update({ color: c })}
              className={`w-5 h-5 rounded border ${p.color === c ? "border-[#58a6ff] ring-1 ring-[#58a6ff]" : "border-[#30363d]"}`}
              style={{ backgroundColor: c }} />
          ))}
        </div>
      </div>

      <Select label="Align" options={ALIGNS} value={p.alignment || "center"} onChange={(v) => update({ alignment: v })} />
      <Slider label="Spacing" value={p.letterSpacing ?? 0} min={-5} max={20} step={0.5} unit="px" onChange={(v) => update({ letterSpacing: v })} />
      <Select label="Transform" options={TRANSFORMS} value={p.textTransform || "none"} onChange={(v) => update({ textTransform: v })} />

      <Toggle label="Shadow" checked={p.shadowEnabled ?? false} onChange={(v) => update({ shadowEnabled: v })} />
      {p.shadowEnabled && (
        <div className="pl-2 border-l-2 border-[#30363d] space-y-2">
          <div className="grid grid-cols-3 gap-1">
            <NumInput label="X" value={p.shadowX ?? 0} onChange={(v) => update({ shadowX: v })} />
            <NumInput label="Y" value={p.shadowY ?? 2} onChange={(v) => update({ shadowY: v })} />
            <NumInput label="Blur" value={p.shadowBlur ?? 6} onChange={(v) => update({ shadowBlur: v })} />
          </div>
        </div>
      )}

      <Toggle label="Stroke" checked={p.strokeEnabled ?? false} onChange={(v) => update({ strokeEnabled: v })} />
      {p.strokeEnabled && (
        <div className="pl-2 border-l-2 border-[#30363d] space-y-2">
          <Slider label="Width" value={p.strokeWidth ?? 1} min={1} max={5} unit="px" onChange={(v) => update({ strokeWidth: v })} />
        </div>
      )}

      <Slider label="Opacity" value={p.opacity ?? 100} min={0} max={100} unit="%" onChange={(v) => update({ opacity: v })} />

      <div>
        <Label>Position (%)</Label>
        <div className="grid grid-cols-2 gap-2">
          <NumInput label="X" value={Math.round(p.x ?? 50)} onChange={(v) => update({ x: v })} />
          <NumInput label="Y" value={Math.round(p.y ?? 50)} onChange={(v) => update({ y: v })} />
        </div>
      </div>
    </div>
  );
}

// ─── Logo Controls ──────────────────────────────────────────────────────

const LOGO_SHAPES = [
  { value: "circle", label: "Circle" },
  { value: "rounded", label: "Rounded" },
  { value: "square", label: "Square" },
];

const LOGO_FITS = [
  { value: "contain", label: "Fit (show whole logo)" },
  { value: "cover", label: "Fill (crop to shape)" },
];

function LogoControls({ p, update }: { p: Record<string, any>; update: (props: Record<string, any>) => void }) {
  return (
    <div className="space-y-3">
      <Slider label="Size" value={p.size ?? 56} min={20} max={240} unit="px" onChange={(v) => update({ size: v })} />
      <Slider label="Opacity" value={p.opacity ?? 100} min={0} max={100} unit="%" onChange={(v) => update({ opacity: v })} />
      <Select label="Shape" options={LOGO_SHAPES} value={p.shape || "circle"} onChange={(v) => update({ shape: v })} />
      <Select label="Fit" options={LOGO_FITS} value={p.objectFit || "contain"} onChange={(v) => update({ objectFit: v })} />
      <Toggle
        label="Solid background"
        checked={p.transparent === false}
        onChange={(v) => update({ transparent: !v })}
      />
      {p.transparent === false && (
        <div>
          <Label>Background</Label>
          <input
            type="color"
            value={p.backgroundColor || "#1a1a2e"}
            onChange={(e) => update({ backgroundColor: e.target.value })}
            className="w-full h-8 rounded border border-[#30363d] cursor-pointer bg-transparent"
          />
        </div>
      )}
      <Slider label="Border" value={p.borderWidth ?? 0} min={0} max={10} unit="px" onChange={(v) => update({ borderWidth: v })} />
      {p.borderWidth > 0 && (
        <div>
          <Label>Border color</Label>
          <input
            type="color"
            value={p.borderColor || "#484f58"}
            onChange={(e) => update({ borderColor: e.target.value })}
            className="w-full h-8 rounded border border-[#30363d] cursor-pointer bg-transparent"
          />
        </div>
      )}
      <div>
        <Label>Position (%)</Label>
        <div className="grid grid-cols-2 gap-2">
          <NumInput label="X" value={Math.round(p.x ?? 50)} onChange={(v) => update({ x: v })} />
          <NumInput label="Y" value={Math.round(p.y ?? 6)} onChange={(v) => update({ y: v })} />
        </div>
      </div>
    </div>
  );
}

// ─── Video Controls ─────────────────────────────────────────────────────

function VideoControls({ p, update }: { p: Record<string, any>; update: (props: Record<string, any>) => void }) {
  const CANVAS_W = 360;
  const CANVAS_H = 640;

  const fitCanvas = () => {
    update({ x: 0, y: 0, w: CANVAS_W, h: CANVAS_H, flipH: p.flipH ?? false });
  };

  const fitWidth = () => {
    // Fill full width, preserve the current aspect ratio
    const curW = p.w ?? CANVAS_W;
    const curH = p.h ?? CANVAS_H;
    const ratio = curW > 0 ? curH / curW : 1;
    const newH = CANVAS_W * ratio;
    update({
      x: 0,
      y: Math.round((CANVAS_H - newH) / 2),
      w: CANVAS_W,
      h: Math.round(newH),
    });
  };

  const isDefault = p.x === 0 && p.y === 0 && p.w === CANVAS_W && p.h === CANVAS_H;

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-[#8b949e] leading-snug">
        Drag the video on canvas to reposition. Corners = resize, edges = crop.
      </p>

      {/* Reset + fit controls */}
      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={fitCanvas}
          className="text-[10px] py-1.5 px-2 rounded border border-[#30363d] text-[#c9d1d9] hover:border-[#58a6ff] hover:bg-[#58a6ff]/5 transition-colors"
          title="Reset video to fill the entire 9:16 canvas"
        >
          Fit to canvas
        </button>
        <button
          onClick={fitWidth}
          className="text-[10px] py-1.5 px-2 rounded border border-[#30363d] text-[#c9d1d9] hover:border-[#58a6ff] hover:bg-[#58a6ff]/5 transition-colors"
          title="Fill canvas width, centered vertically (keeps aspect)"
        >
          Fit width, center
        </button>
      </div>
      {!isDefault && (
        <p className="text-[10px] text-[#f0a500] leading-snug bg-[#f0a500]/10 border border-[#f0a500]/30 rounded p-1.5">
          Video isn't filling the canvas. Click <strong>Fit to canvas</strong> above to reset.
        </p>
      )}

      <div className="grid grid-cols-2 gap-2">
        <NumInput label="Width" value={Math.round(p.w ?? 360)} onChange={(v) => update({ w: v })} />
        <NumInput label="Height" value={Math.round(p.h ?? 640)} onChange={(v) => update({ h: v })} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <NumInput label="X Offset" value={Math.round(p.x ?? 0)} onChange={(v) => update({ x: v })} />
        <NumInput label="Y Offset" value={Math.round(p.y ?? 0)} onChange={(v) => update({ y: v })} />
      </div>
      <Toggle label="Flip Horizontal" checked={p.flipH ?? false} onChange={(v) => update({ flipH: v })} />
    </div>
  );
}

// ─── Main Panel ─────────────────────────────────────────────────────────

export function PropertiesPanel({ selectedLayer, onUpdateProps }: PropertiesPanelProps) {
  const update = useCallback(
    (props: Record<string, any>) => {
      if (selectedLayer) onUpdateProps(selectedLayer.id, props);
    },
    [selectedLayer, onUpdateProps]
  );

  if (!selectedLayer) {
    return (
      <div className="h-full flex items-center justify-center p-4">
        <p className="text-xs text-[#8b949e] text-center">Click an element on the canvas to edit it</p>
      </div>
    );
  }

  const p = selectedLayer.props;

  return (
    <div className="p-3 space-y-1">
      {selectedLayer.type === "video" && <VideoControls p={p} update={update} />}
      {(selectedLayer.type === "headline" || selectedLayer.type === "subtitle") && <TextControls p={p} update={update} />}
      {selectedLayer.type === "logo" && <LogoControls p={p} update={update} />}
    </div>
  );
}
