"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Loading } from "@/components/shared/loading";
import { EmptyState } from "@/components/shared/empty-state";
import { api, Template } from "@/lib/api";
import { Canvas } from "@/components/editor/Canvas";
import { PropertiesPanel } from "@/components/editor/PropertiesPanel";

// Template layers share the exact same prop shape as the editor's layers,
// so the Canvas + PropertiesPanel components render them identically.
// When an export is created from a template, the backend copies these
// into headline_style / subtitle_style / logo_overrides directly.

interface TemplateLayer {
  id: string;
  name: string;
  type: string;
  visible: boolean;
  props: Record<string, any>;
}

const DEFAULT_LAYERS = (): TemplateLayer[] => [
  {
    id: "logo",
    name: "Logo",
    type: "logo",
    visible: true,
    props: {
      size: 72,
      opacity: 100,
      shape: "circle",
      objectFit: "contain",
      transparent: true,
      borderWidth: 0,
      borderColor: "#484f58",
      x: 50,
      y: 8,
    },
  },
  {
    id: "headline",
    name: "Headline",
    type: "headline",
    visible: true,
    props: {
      text: "Your headline here",
      fontFamily: "Inter",
      fontSize: 48,
      fontWeight: 700,
      color: "#FFFFFF",
      alignment: "center",
      letterSpacing: 0,
      textTransform: "none",
      shadowEnabled: true,
      shadowColor: "#000000",
      shadowBlur: 6,
      shadowX: 0,
      shadowY: 2,
      strokeEnabled: false,
      strokeColor: "#000000",
      strokeWidth: 2,
      opacity: 100,
      x: 50,
      y: 68,
    },
  },
  {
    id: "subtitle",
    name: "Subtitle",
    type: "subtitle",
    visible: true,
    props: {
      text: "Subtitle text goes here",
      fontFamily: "Inter",
      fontSize: 22,
      fontWeight: 400,
      color: "#C9D1D9",
      alignment: "center",
      letterSpacing: 0,
      textTransform: "none",
      shadowEnabled: true,
      shadowColor: "#000000",
      shadowBlur: 4,
      shadowX: 0,
      shadowY: 1,
      strokeEnabled: false,
      strokeColor: "#000000",
      strokeWidth: 1,
      opacity: 100,
      x: 50,
      y: 80,
    },
  },
];

// Normalise a template row loaded from the backend (which may store either
// the new flat shape or a legacy nested shape) into the flat layer props
// used by Canvas/PropertiesPanel.
function layersFromTemplate(t: Template): TemplateLayer[] {
  const base = DEFAULT_LAYERS();
  const normalise = (raw: any) => {
    if (!raw || typeof raw !== "object") return {};
    const s: any = { ...raw };
    if (s.position && typeof s.position === "object") {
      if (s.position.x != null && s.x == null) s.x = s.position.x;
      if (s.position.y != null && s.y == null) s.y = s.position.y;
      delete s.position;
    }
    for (const k of ["x", "y"]) {
      if (typeof s[k] === "number" && s[k] > 0 && s[k] <= 1) s[k] = Math.round(s[k] * 100);
    }
    const rename: Record<string, string> = {
      font_family: "fontFamily",
      font_size: "fontSize",
      font_weight: "fontWeight",
      shadow_enabled: "shadowEnabled",
      shadow_color: "shadowColor",
      shadow_blur: "shadowBlur",
      shadow_x: "shadowX",
      shadow_y: "shadowY",
      stroke_enabled: "strokeEnabled",
      stroke_color: "strokeColor",
      stroke_width: "strokeWidth",
      letter_spacing: "letterSpacing",
      text_transform: "textTransform",
      border_width: "borderWidth",
      border_color: "borderColor",
    };
    for (const [old, n] of Object.entries(rename)) {
      if (s[old] !== undefined && s[n] === undefined) {
        s[n] = s[old];
        delete s[old];
      }
    }
    return s;
  };

  const logoNorm = normalise(t.logo_position);
  // Template stores size as multiplier historically; if small, multiply.
  if (typeof logoNorm.size === "number" && logoNorm.size <= 3.5) {
    logoNorm.size = Math.round(logoNorm.size * 56);
  }

  return [
    { ...base[0], props: { ...base[0].props, ...logoNorm } },
    {
      ...base[1],
      props: { ...base[1].props, ...normalise(t.headline_defaults), text: base[1].props.text },
    },
    {
      ...base[2],
      props: { ...base[2].props, ...normalise(t.subtitle_defaults), text: base[2].props.text },
    },
  ];
}

// Reverse: serialise layers back to the flat shape we persist.
function layersToTemplatePayload(layers: TemplateLayer[], name: string, bg: string) {
  const logo = layers.find((l) => l.id === "logo")!.props;
  const headline = layers.find((l) => l.id === "headline")!.props;
  const subtitle = layers.find((l) => l.id === "subtitle")!.props;
  // Keep only style fields (strip text content — that's per-export).
  const dropText = (p: Record<string, any>) => {
    const { text, ...rest } = p;
    return rest;
  };
  return {
    template_name: name,
    background_color: bg,
    logo_position: logo,
    headline_defaults: dropText(headline),
    subtitle_defaults: dropText(subtitle),
  };
}

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  const [tpl, setTpl] = useState<Template | null>(null);
  const [layers, setLayers] = useState<TemplateLayer[]>(DEFAULT_LAYERS());
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>("headline");
  const [bgColor, setBgColor] = useState("#000000");
  const [name, setName] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logoInputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null) as React.RefObject<HTMLVideoElement>;

  // Warn the user if they try to close/reload the tab with unsaved edits.
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const fetchAll = useCallback(async () => {
    try {
      const ts = await api.templates.list();
      setTemplates(ts);
      if (ts.length === 0) {
        setTpl(null);
      } else if (!tpl) {
        // Select default or first
        const pick = ts.find((t) => t.is_default) || ts[0];
        loadTemplate(pick);
      }
    } catch (e: any) {
      console.error("Failed to fetch templates:", e?.message || "unknown error");
      setError(e?.message || "Failed to load templates. Please try again.");
    }
    setLoading(false);
  }, [tpl]);

  useEffect(() => {
    fetchAll();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadTemplate = (t: Template) => {
    setTpl(t);
    setName(t.template_name);
    setBgColor(t.background_color || "#000000");
    setLayers(layersFromTemplate(t));
    setDirty(false);
    setSelectedLayerId("headline");
  };

  const updateLayerProps = useCallback((id: string, props: Record<string, any>) => {
    setLayers((prev) => prev.map((l) => (l.id === id ? { ...l, props: { ...l.props, ...props } } : l)));
    setDirty(true);
  }, []);

  const toggleVisibility = (id: string) => {
    setLayers((prev) => prev.map((l) => (l.id === id ? { ...l, visible: !l.visible } : l)));
    setDirty(true);
  };

  const handleSave = async () => {
    if (!tpl) return;
    setSaving(true);
    try {
      const payload = layersToTemplatePayload(layers, name, bgColor);
      const updated = await api.templates.update(tpl.id, payload);
      setTpl(updated);
      setTemplates((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      setDirty(false);
    } catch (e: any) {
      console.error("Failed to save template:", e?.message || "unknown error");
      setError(e?.message || "Failed to save template. Please try again.");
    }
    setSaving(false);
  };

  const handleSetDefault = async () => {
    if (!tpl) return;
    try {
      const updated = await api.templates.setDefault(tpl.id);
      setTpl(updated);
      // Refresh list so the default toggle is reflected elsewhere.
      const ts = await api.templates.list();
      setTemplates(ts);
    } catch (e: any) {
      console.error("Failed to set default template:", e?.message || "unknown error");
      setError(e?.message || "Failed to set default template. Please try again.");
    }
  };

  const handleDelete = async () => {
    if (!tpl) return;
    if (!confirm(`Delete template "${tpl.template_name}"?`)) return;
    try {
      await api.templates.delete(tpl.id);
      const ts = await api.templates.list();
      setTemplates(ts);
      if (ts.length > 0) {
        loadTemplate(ts.find((t) => t.is_default) || ts[0]);
      } else {
        setTpl(null);
      }
    } catch (e: any) {
      console.error("Failed to delete template:", e?.message || "unknown error");
      setError(e?.message || "Failed to delete template. Please try again.");
    }
  };

  const handleCreate = async () => {
    if (!createName.trim()) return;
    setCreating(true);
    try {
      const t = await api.templates.create({ template_name: createName.trim() });
      setTemplates((prev) => [t, ...prev]);
      setShowCreate(false);
      setCreateName("");
      loadTemplate(t);
    } catch (e: any) {
      console.error("Failed to create template:", e?.message || "unknown error");
      setError(e?.message || "Failed to create template. Please try again.");
    }
    setCreating(false);
  };

  const handleLogoUpload = async (file: File) => {
    if (!tpl) return;
    setUploadingLogo(true);
    try {
      const updated = await api.templates.uploadLogo(tpl.id, file);
      setTpl(updated);
      setTemplates((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    } catch (e: any) {
      console.error("Failed to upload logo:", e?.message || "unknown error");
      setError(e?.message || "Failed to upload logo. Please try again.");
    }
    setUploadingLogo(false);
  };

  if (loading) {
    return <div className="p-8"><Loading size="lg" className="py-20" /></div>;
  }

  const selectedLayer = selectedLayerId
    ? { id: selectedLayerId, type: selectedLayerId, props: layers.find((l) => l.id === selectedLayerId)?.props || {} }
    : null;

  const logoUrl = tpl?.logo_minio_key ? api.files.getLogoUrl(tpl.id) : null;

  return (
    <div className="flex h-screen overflow-hidden">
      {error && (
        <div className="mx-4 mt-4 p-3 text-sm text-[#f85149] bg-[#f85149]/10 border border-[#f85149]/30 rounded absolute top-0 left-0 right-0 z-50">
          {error}
        </div>
      )}
      {/* ─── Left: template list ─── */}
      <div className="w-[220px] flex-shrink-0 bg-[#0d1117] border-r border-[#21262d] flex flex-col">
        <div className="px-4 py-3 border-b border-[#21262d] flex items-center justify-between">
          <span className="text-sm font-semibold text-[#e6edf3]">Templates</span>
          <button onClick={() => setShowCreate(true)} className="text-xs text-[#58a6ff] hover:underline">
            + New
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {templates.length === 0 ? (
            <p className="text-xs text-[#484f58] text-center py-8">No templates yet</p>
          ) : (
            templates.map((t) => (
              <div
                key={t.id}
                onClick={() => loadTemplate(t)}
                className={`px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${
                  tpl?.id === t.id
                    ? "bg-[#161b22] border border-[#30363d]"
                    : "hover:bg-[#161b22]/50 border border-transparent"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-[#e6edf3] truncate">{t.template_name}</span>
                  {t.is_default && (
                    <span className="text-[9px] text-[#3fb950] bg-[#0f2e16] px-1.5 py-0.5 rounded">
                      default
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {tpl ? (
        <div className="flex-1 flex bg-[#0d1117] overflow-hidden">
          {/* ─── Canvas ─── */}
          <div className="flex-1 flex flex-col items-center justify-center bg-[#080a0f] p-4 relative">
            <div className="mb-3 flex items-center gap-2">
              <Input
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setDirty(true);
                }}
                className="h-8 text-sm"
              />
              <Button size="sm" variant={dirty ? "primary" : "secondary"} onClick={handleSave} loading={saving} disabled={!dirty && !saving}>
                {dirty ? "Save changes" : "Saved"}
              </Button>
              {!tpl.is_default && (
                <Button size="sm" variant="ghost" onClick={handleSetDefault}>
                  Set default
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={handleDelete}>
                Delete
              </Button>
            </div>
            <Canvas
              layers={layers}
              selectedLayerId={selectedLayerId}
              videoUrl={null}
              logoUrl={logoUrl}
              videoRef={videoRef}
              backgroundColor={bgColor}
              onSelectLayer={setSelectedLayerId}
              onUpdateLayerProps={updateLayerProps}
            />
            <p className="text-[10px] text-[#484f58] mt-3 text-center max-w-md">
              Design your default look. When you open a reel in the editor, these values seed headline / subtitle / logo.
              You can always override per-export.
            </p>
          </div>

          {/* ─── Right: properties panel ─── */}
          <div className="w-[280px] flex-shrink-0 bg-[#0d1117] border-l border-[#21262d] overflow-y-auto">
            <div className="px-3 py-2 border-b border-[#21262d] flex items-center justify-between">
              <span className="text-[11px] font-medium text-[#8b949e] uppercase tracking-wider">
                {selectedLayerId ? `${selectedLayerId} styles` : "Properties"}
              </span>
            </div>

            {/* Layer switcher */}
            <div className="px-3 py-2 border-b border-[#21262d] grid grid-cols-3 gap-1">
              {layers.map((l) => (
                <button
                  key={l.id}
                  onClick={() => setSelectedLayerId(l.id)}
                  className={`text-[11px] py-1.5 rounded transition-colors ${
                    selectedLayerId === l.id
                      ? "bg-[#161b22] text-[#58a6ff] border border-[#30363d]"
                      : "text-[#8b949e] hover:text-[#c9d1d9] border border-transparent"
                  }`}
                >
                  {l.name}
                </button>
              ))}
            </div>

            {/* Logo upload control (visible when logo is selected) */}
            {selectedLayerId === "logo" && (
              <div className="px-3 py-3 border-b border-[#21262d] space-y-2">
                <input
                  ref={logoInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleLogoUpload(f);
                    if (e.target) e.target.value = "";
                  }}
                />
                <Button size="sm" variant="secondary" onClick={() => logoInputRef.current?.click()} loading={uploadingLogo}>
                  {tpl.logo_minio_key ? "Replace logo" : "Upload logo"}
                </Button>
                {tpl.logo_minio_key && (
                  <p className="text-[10px] text-[#484f58]">
                    Transparent PNG recommended. Shape + fit control how it renders on the reel.
                  </p>
                )}
              </div>
            )}

            <PropertiesPanel selectedLayer={selectedLayer} onUpdateProps={updateLayerProps} />

            {/* Background color — shown at the bottom regardless of selection */}
            <div className="px-3 py-3 border-t border-[#21262d] space-y-2">
              <span className="text-[11px] text-[#8b949e] uppercase tracking-wider">Canvas background</span>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={bgColor}
                  onChange={(e) => {
                    setBgColor(e.target.value);
                    setDirty(true);
                  }}
                  className="w-8 h-8 rounded border border-[#30363d] cursor-pointer bg-transparent"
                />
                <input
                  type="text"
                  value={bgColor}
                  onChange={(e) => {
                    setBgColor(e.target.value);
                    setDirty(true);
                  }}
                  className="flex-1 px-2 py-1 text-xs bg-[#0d1117] text-[#c9d1d9] border border-[#30363d] rounded font-mono"
                />
              </div>
              <p className="text-[10px] text-[#484f58] leading-snug">
                Only visible in the final export where the video doesn't fill the 9:16 frame.
              </p>
            </div>

            {/* Visibility toggles */}
            <div className="px-3 py-3 border-t border-[#21262d] space-y-1">
              <span className="text-[11px] text-[#8b949e] uppercase tracking-wider block mb-1">Visibility</span>
              {layers.map((l) => (
                <div key={l.id} className="flex items-center justify-between">
                  <span className="text-xs text-[#c9d1d9]">{l.name}</span>
                  <button
                    onClick={() => toggleVisibility(l.id)}
                    className={`text-[10px] px-2 py-0.5 rounded ${l.visible ? "text-[#3fb950]" : "text-[#484f58]"}`}
                  >
                    {l.visible ? "shown" : "hidden"}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center bg-[#080a0f]">
          <EmptyState
            title="No template selected"
            description="Create your first brand template to set default headline/subtitle/logo styling."
            actionLabel="New Template"
            onAction={() => setShowCreate(true)}
          />
        </div>
      )}

      <Modal isOpen={showCreate} onClose={() => setShowCreate(false)} title="New Template">
        <div className="space-y-4">
          <Input
            label="Name"
            placeholder="My Brand Template"
            value={createName}
            onChange={(e) => setCreateName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <div className="flex gap-2 justify-end">
            <Button variant="secondary" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} loading={creating}>
              Create
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
