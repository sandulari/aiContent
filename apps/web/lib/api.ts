const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ────────────────────────────────────────────────────────────────

export interface User {
  id: string; email: string; display_name: string; role?: string; ig_username: string | null; created_at: string;
}

export type PageType = "own" | "reference";

export interface UserPage {
  id: string; ig_username: string; ig_display_name: string | null; ig_profile_pic_url: string | null;
  page_type: PageType;
  follower_count: number | null; total_posts: number | null;
  avg_views_per_reel: number | null; avg_engagement_rate: number | null;
  is_active: boolean; last_analyzed_at: string | null; created_at: string;
  niche: string | null; top_topics: string[] | null;
}

export interface WeeklyDashboard {
  page_id: string;
  ig_username: string;
  has_data: boolean;
  week_key: string | null;
  follower_count: number | null;
  follower_delta: number | null;
  total_posts: number | null;
  total_posts_delta: number | null;
  total_views_week: number | null;
  total_likes_week: number | null;
  total_comments_week: number | null;
  comments_gained_wow: number | null;
  engagement_rate_delta: number | null;
  top_reel: null | {
    ig_video_id: string;
    ig_url: string | null;
    view_count: number | null;
    like_count: number | null;
    caption: string | null;
  };
  snapshots_available: number;
}

export interface DashboardData {
  page_id: string;
  ig_username: string;
  period: { from_date: string; to_date: string; days: number };
  followers: number | null;
  followers_delta: number | null;
  followers_delta_pct: number | null;
  views: number | null;
  views_delta: number | null;
  views_delta_pct: number | null;
  likes: number | null;
  likes_delta: number | null;
  likes_delta_pct: number | null;
  comments: number | null;
  comments_delta: number | null;
  comments_delta_pct: number | null;
  posts_count: number | null;
  posts_delta: number | null;
  engagement_rate: number | null;
  engagement_delta: number | null;
  top_reel: {
    ig_video_id: string;
    ig_url: string | null;
    view_count: number;
    like_count: number;
    caption: string | null;
    posted_at: string | null;
  } | null;
  daily_snapshots: {
    date: string;
    followers: number;
    views: number;
    likes: number;
    comments: number;
  }[];
  has_data: boolean;
  reels?: {
    ig_code: string;
    ig_url: string;
    posted_at: string | null;
    view_count: number;
    like_count: number;
    comment_count: number;
    caption: string | null;
  }[];
}

export interface RecommendationSummary {
  total: number;
  at_least_500k: number;
  target_min: number;
  view_floor: number;
  meets_target: boolean;
}

export interface PageProfile {
  id: string; niche_primary: string | null; niche_secondary: string | null;
  top_topics: string[] | null; top_formats: string[] | null;
  content_style: Record<string, any> | null; best_duration_range: Record<string, any> | null;
  posting_frequency: number | null; analyzed_at: string | null;
}

export interface Recommendation {
  id: string; viral_reel_id: string; match_score: number; match_reason: string | null;
  match_factors: Record<string, any> | null; is_used: boolean; recommended_at: string;
  ig_url: string | null; thumbnail_url: string | null; view_count: number;
  like_count: number; duration_seconds: number | null; caption: string | null;
  posted_at: string | null; source_page: string | null;
}

export interface ReelDetail {
  id: string; ig_video_id: string; ig_url: string; thumbnail_url: string | null;
  view_count: number; like_count: number; comment_count: number | null;
  duration_seconds: number | null; caption: string | null; posted_at: string | null;
  status: string; source_page: string | null;
  sources: ReelSource[]; files: ReelFile[];
}

export interface ReelSource {
  id: string; source_type: string; source_url: string; source_title: string | null;
  match_confidence: number | null; is_selected: boolean; found_at: string;
}

export interface ReelFile {
  id: string; file_type: string; resolution: string; file_size_bytes: number; created_at: string;
}

export interface Template {
  id: string; user_id: string; template_name: string; logo_minio_key: string | null;
  logo_position: Record<string, any>; headline_defaults: Record<string, any>;
  subtitle_defaults: Record<string, any>; background_color: string;
  is_default: boolean; created_at: string; updated_at: string;
}

export interface UserExport {
  id: string; user_id: string; user_page_id: string | null; viral_reel_id: string; template_id: string;
  headline_text: string; headline_style: Record<string, any>;
  subtitle_text: string; subtitle_style: Record<string, any>;
  caption_text: string | null; video_transform: Record<string, any>;
  video_trim: Record<string, any>; audio_config: Record<string, any>;
  logo_overrides?: Record<string, any> | null;
  logo_override_key?: string | null;
  export_minio_key: string | null; export_status: string;
  created_at: string; exported_at: string | null;
}

export interface Niche { id: string; name: string; slug: string; }

export interface AITextResult {
  headlines: string[]; subtitles: string[]; caption_suggestion: string | null;
}

// ── Fetch ────────────────────────────────────────────────────────────────

interface FetchOpts extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message); this.name = "ApiError";
  }
}

let _refreshing: Promise<void> | null = null;

async function _doFetch<T>(url: string, init: RequestInit, headers: Record<string, string>): Promise<T> {
  const res = await fetch(url, { ...init, headers, credentials: "include" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    let msg = res.statusText;
    if (typeof body.detail === "string") msg = body.detail;
    else if (Array.isArray(body.detail)) msg = body.detail.map((d: any) => d.msg || String(d)).join(", ");
    throw new ApiError(res.status, msg, body);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

async function req<T>(endpoint: string, opts: FetchOpts = {}): Promise<T> {
  const { params, ...init } = opts;
  let url = `${API_BASE}${endpoint}`;
  if (params) {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) { if (v !== undefined && v !== null) sp.append(k, String(v)); }
    const qs = sp.toString();
    if (qs) url += `?${qs}`;
  }
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string>) };
  if (init.body instanceof FormData) delete headers["Content-Type"];

  try {
    return await _doFetch<T>(url, init, headers);
  } catch (e) {
    // On 401, try refreshing the token once and retry
    if (e instanceof ApiError && e.status === 401 && !endpoint.includes("/auth/")) {
      if (!_refreshing) {
        _refreshing = fetch(`${API_BASE}/api/auth/refresh`, { method: "POST", credentials: "include" })
          .then((r) => { if (!r.ok) throw new Error("refresh failed"); })
          .finally(() => { _refreshing = null; });
      }
      try {
        await _refreshing;
        return await _doFetch<T>(url, init, headers);
      } catch {
        throw e; // refresh failed — throw original 401
      }
    }
    throw e;
  }
}

// ── API Client ───────────────────────────────────────────────────────────

export const api = {
  auth: {
    register(data: { email: string; password: string; display_name: string }) {
      return req<{ user: { id: string; email: string; display_name: string; role: string } }>("/api/auth/register", { method: "POST", body: JSON.stringify(data) });
    },
    login(data: { email: string; password: string }) {
      return req<{ user: { id: string; email: string; display_name: string; role: string } }>("/api/auth/login", { method: "POST", body: JSON.stringify(data) });
    },
    logout() {
      return req<{ message: string }>("/api/auth/logout", { method: "POST" });
    },
    refresh() {
      return req<{ user: { id: string; email: string; display_name: string; role: string } }>("/api/auth/refresh", { method: "POST" });
    },
    me() { return req<{ id: string; email: string; display_name: string; role: string }>("/api/auth/me"); },
    forgotPassword(email: string) {
      return req<{ message: string }>("/api/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
    },
    resetPassword(email: string, token: string, new_password: string) {
      return req<{ message: string }>("/api/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ email, token, new_password }),
      });
    },
  },

  myPages: {
    list(page_type?: PageType) {
      return req<UserPage[]>("/api/my-pages", { params: page_type ? { page_type } : undefined });
    },
    add(ig_username: string, page_type: PageType = "own") {
      return req<UserPage>("/api/my-pages", {
        method: "POST",
        body: JSON.stringify({ ig_username, page_type }),
      });
    },
    remove(id: string) { return req<void>(`/api/my-pages/${id}`, { method: "DELETE" }); },
    getProfile(id: string) { return req<PageProfile>(`/api/my-pages/${id}/profile`); },
    getStats(id: string) { return req<Record<string, any>>(`/api/my-pages/${id}/stats`); },
    getRecommendations(pageId: string, params?: { sort_by?: string; limit?: number; offset?: number; min_views?: number }) {
      return req<Recommendation[]>(`/api/my-pages/${pageId}/recommendations`, { params: params as any });
    },
    getRecommendationsSummary(pageId: string) {
      return req<RecommendationSummary>(`/api/my-pages/${pageId}/recommendations/summary`);
    },
    getDashboard(pageId: string, params?: { from_date?: string; to_date?: string }) {
      return req<DashboardData>(`/api/my-pages/${pageId}/dashboard`, { params: params as any });
    },
    getWeeklyDashboard(pageId: string) {
      return req<WeeklyDashboard>(`/api/my-pages/${pageId}/weekly-dashboard`);
    },
    refreshStats(pageId: string) {
      return req<{ status: string; task_id: string }>(`/api/my-pages/${pageId}/refresh-stats`, { method: "POST" });
    },
    saveIntegration(provider: string, apiKey: string) {
      return req<{ status: string }>(`/api/my-pages/integrations/${provider}`, {
        method: "POST",
        body: JSON.stringify({ api_key: apiKey }),
      });
    },
  },

  recommendations: {
    dismiss(id: string) { return req<{ status: string }>(`/api/my-pages/recommendations/${id}/dismiss`, { method: "POST" }); },
    use(id: string) { return req<{ status: string; viral_reel_id: string }>(`/api/my-pages/recommendations/${id}/use`, { method: "POST" }); },
  },

  reels: {
    get(id: string) { return req<ReelDetail>(`/api/reels/${id}`); },
    findSources(id: string) { return req<{ job_id: string }>(`/api/reels/${id}/find-sources`, { method: "POST" }); },
    download(id: string, sourceId: string) {
      return req<{ job_id: string }>(`/api/reels/${id}/download`, { method: "POST", body: JSON.stringify({ source_id: sourceId }) });
    },
  },

  templates: {
    list() { return req<Template[]>("/api/templates"); },
    get(id: string) { return req<Template>(`/api/templates/${id}`); },
    create(data: any) { return req<Template>("/api/templates", { method: "POST", body: JSON.stringify(data) }); },
    update(id: string, data: any) { return req<Template>(`/api/templates/${id}`, { method: "PUT", body: JSON.stringify(data) }); },
    delete(id: string) { return req<void>(`/api/templates/${id}`, { method: "DELETE" }); },
    setDefault(id: string) { return req<Template>(`/api/templates/${id}/set-default`, { method: "POST" }); },
    uploadLogo(id: string, file: File) {
      const fd = new FormData(); fd.append("file", file);
      return req<Template>(`/api/templates/${id}/upload-logo`, { method: "POST", body: fd });
    },
  },

  exports: {
    list() { return req<UserExport[]>("/api/exports"); },
    create(data: any) { return req<UserExport>("/api/exports", { method: "POST", body: JSON.stringify(data) }); },
    update(id: string, data: any) { return req<UserExport>(`/api/exports/${id}`, { method: "PUT", body: JSON.stringify(data) }); },
    applyTemplate(exportId: string, templateId: string) {
      return req<UserExport>(`/api/exports/${exportId}/apply-template/${templateId}`, { method: "POST" });
    },
    uploadLogo(id: string, file: File) {
      const fd = new FormData(); fd.append("file", file);
      return req<UserExport>(`/api/exports/${id}/upload-logo`, { method: "POST", body: fd });
    },
    clearLogo(id: string) {
      return req<void>(`/api/exports/${id}/logo-override`, { method: "DELETE" });
    },
    delete(id: string) {
      return req<void>(`/api/exports/${id}`, { method: "DELETE" });
    },
    render(id: string) { return req<{ job_id: string }>(`/api/exports/${id}/render`, { method: "POST" }); },
    getStatus(id: string) { return req<UserExport>(`/api/exports/${id}/status`); },
    downloadUrl(id: string) {
      // Cookies are sent automatically — no need to append ?token=
      return `${API_BASE}/api/exports/${id}/download`;
    },
  },

  files: {
    downloadUrl(fileId: string) { return `${API_BASE}/api/files/${fileId}/download`; },
    getVideoStreamUrl(reelId: string) { return `${API_BASE}/api/files/video/${reelId}/stream`; },
    getVideoInfo(reelId: string) { return req<{ url: string; resolution: string; duration_seconds: number; file_size_bytes?: number }>(`/api/files/video/${reelId}/info`); },
    getLogoUrl(templateId: string) { return `${API_BASE}/api/files/logo/${templateId}`; },
    getExportLogoUrl(exportId: string, cacheBuster?: number) {
      const qs = cacheBuster ? `?t=${cacheBuster}` : "";
      return `${API_BASE}/api/files/export-logo/${exportId}${qs}`;
    },
    getThumbnailUrl(reelId: string) { return `${API_BASE}/api/files/thumbnail/${reelId}`; },
    uploadAudio(file: File) {
      const fd = new FormData(); fd.append("file", file);
      return req<{ minio_key: string }>("/api/files/upload-audio", { method: "POST", body: fd });
    },
  },

  niches: {
    list() { return req<Niche[]>("/api/niches"); },
  },

  ai: {
    generateText(data: { viral_reel_id: string; user_page_id: string }) {
      return req<AITextResult>("/api/ai/generate-text", { method: "POST", body: JSON.stringify(data) });
    },
    regenerate(data: { viral_reel_id: string; user_page_id: string; style_hint?: string }) {
      return req<AITextResult>("/api/ai/regenerate", { method: "POST", body: JSON.stringify(data) });
    },
    chat(data: {
      viral_reel_id: string;
      user_page_id: string;
      messages: { role: "user" | "assistant"; content: string }[];
    }) {
      return req<{
        assistant_message: string;
        suggestions: { headlines: string[]; subtitles: string[]; caption: string };
      }>("/api/ai/chat", { method: "POST", body: JSON.stringify(data) });
    },
  },
};
