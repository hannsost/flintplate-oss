/**
 * Typed fetch wrapper for palmscout API
 * Provides authApi (auth endpoints) and profileApi (profile endpoints)
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/** API validation errors can be arrays of objects; never render raw payloads. */
export function apiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item: unknown) => {
      if (typeof item === "object" && item !== null && "msg" in item && typeof item.msg === "string") return item.msg;
      return typeof item === "string" ? item : "";
    }).filter(Boolean);
    if (messages.length) return messages.join(" · ");
  }
  return fallback || "Die Anfrage konnte nicht verarbeitet werden.";
}

let refreshInFlight: Promise<string | null> | null = null;
async function tryRefresh(): Promise<string | null> {
  if (!refreshInFlight) refreshInFlight = refreshSession().finally(() => { refreshInFlight = null; });
  return refreshInFlight;
}

/** Attempt a silent token refresh. Returns new access token or null. */
async function refreshSession(): Promise<string | null> {
  const { auth } = await import("@/lib/auth");
  const refreshToken = auth.getRefresh();
  if (!refreshToken) return null;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (res.status === 401 || res.status === 403) return null;
    if (!res.ok) throw new ApiError(res.status, "Sitzung kann gerade nicht erneuert werden. Bitte erneut versuchen.");
    const data = await res.json();
    auth.setTokens(data.access_token, data.refresh_token);
    return data.access_token as string;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(503, "Verbindung unterbrochen. Bitte erneut versuchen.");
  }
}

/** Redirect to /login and clear stored tokens. */
function forceLogout() {
  import("@/lib/auth").then(({ auth }) => auth.clear());
  if (typeof window !== "undefined") {
    window.location.replace("/anmelden?next=" + encodeURIComponent(window.location.pathname));
  }
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    // Only attempt silent refresh for authenticated requests (token was provided).
    // For public endpoints like /auth/login, a 401 is just wrong credentials — don't reload.
    if (token) {
      const newToken = await tryRefresh();
      if (newToken) {
        // Retry original request with fresh token
        const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
        const retry = await fetch(`${API_BASE}${path}`, { ...options, headers: retryHeaders });
        if (retry.ok) {
          if (retry.status === 204) return undefined as T;
          return retry.json() as Promise<T>;
        }
        if (retry.status !== 401) {
          let detail = retry.statusText;
          try { detail = apiErrorMessage((await retry.json()).detail, detail); } catch { /* use status text */ }
          throw new ApiError(retry.status, detail);
        }
      }
      // Refresh failed → logout
      forceLogout();
      throw new ApiError(401, "Sitzung abgelaufen. Bitte erneut anmelden.");
    }
    // Unauthenticated 401 (e.g. wrong login credentials) — just throw, don't reload
    let detail = res.statusText;
    try { const body = await res.json(); detail = apiErrorMessage(body.detail, detail); } catch { /* ignore */ }
    throw new ApiError(401, detail);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = apiErrorMessage(body.detail, detail);
    } catch {
      // ignore parse error
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ── Types ──────────────────────────────────────────────────────────────────

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export type WorkspaceType = "internal_hr" | "recruiter_agency" | "solo_recruiter" | "zeitarbeit";
export interface WorkspaceRead {
  id: string;
  name: string;
  type: WorkspaceType;
  status: string;
  trial_ends_at: string | null;
}

export interface UserRead {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  tenant_id: string | null;
  company_id: string | null;
  is_active: boolean;
  is_verified: boolean;
  ai_opt_in: boolean;
  terms_accepted: boolean;
  created_at: string;
}

// These resources are consumed by several layouts and widgets at the same time.
// Keep the cache here (instead of in a component) so route changes and multiple
// mounted consumers share one in-flight request as well as the result.
const USER_CACHE_TTL_MS = 5 * 60_000;
const NOTIFICATION_CACHE_TTL_MS = 30_000;
let userCache: { token: string; value: UserRead; expiresAt: number } | null = null;
let userRequest: { token: string; promise: Promise<UserRead> } | null = null;
let notificationCache: {
  token: string;
  value: NotificationListResponse;
  expiresAt: number;
} | null = null;
let notificationRequest: {
  token: string;
  promise: Promise<NotificationListResponse>;
} | null = null;

function cachedUser(token: string): Promise<UserRead> {
  if (userCache?.token === token && userCache.expiresAt > Date.now()) {
    return Promise.resolve(userCache.value);
  }
  if (userRequest?.token === token) return userRequest.promise;

  const promise = request<UserRead>("/users/me", {}, token).then((value) => {
    userCache = { token, value, expiresAt: Date.now() + USER_CACHE_TTL_MS };
    return value;
  });
  userRequest = { token, promise };
  void promise.then(
    () => {
      if (userRequest?.promise === promise) userRequest = null;
    },
    () => {
      if (userRequest?.promise === promise) userRequest = null;
    },
  );
  return promise;
}

function cachedNotifications(token: string): Promise<NotificationListResponse> {
  if (notificationCache?.token === token && notificationCache.expiresAt > Date.now()) {
    return Promise.resolve(notificationCache.value);
  }
  if (notificationRequest?.token === token) return notificationRequest.promise;

  const promise = request<NotificationListResponse>("/notifications/", {}, token).then((value) => {
    notificationCache = {
      token,
      value,
      expiresAt: Date.now() + NOTIFICATION_CACHE_TTL_MS,
    };
    return value;
  });
  notificationRequest = { token, promise };
  void promise.then(
    () => {
      if (notificationRequest?.promise === promise) notificationRequest = null;
    },
    () => {
      if (notificationRequest?.promise === promise) notificationRequest = null;
    },
  );
  return promise;
}

export interface ProfileRead {
  id: string;
  user_id: string;
  headline: string | null;
  summary: string | null;
  location: string | null;
  phone: string | null;
  website: string | null;
  linkedin_url: string | null;
  cv_original_filename: string | null;
  completeness_score: number;
  structured_data: Record<string, unknown> | null;
  work_experiences: WorkExperience[];
  educations: Education[];
  skills: Skill[];
  created_at: string;
  updated_at: string;
}

export interface WorkExperience {
  id: string;
  company: string;
  title: string;
  location: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  description: string | null;
}

export interface Education {
  id: string;
  institution: string;
  degree: string | null;
  field_of_study: string | null;
  start_date: string | null;
  end_date: string | null;
  grade: string | null;
}

export interface Skill {
  id: string;
  name: string;
  category: string | null;
  level: "beginner" | "intermediate" | "advanced" | "expert" | null;
  years_of_experience: number | null;
}

export interface CVUploadResponse {
  profile: ProfileRead;
  parse_status: "parsed" | "queued" | "failed";
  extracted_fields: Record<string, unknown>;
}

// ── Auth API ───────────────────────────────────────────────────────────────

export const authApi = {
  register: (data: {
    email: string;
    password: string;
    full_name: string;
  }) =>
    request<TokenResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  login: (email: string, password: string) => {
    const body = new URLSearchParams({ username: email, password });
    return request<TokenResponse>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
  },

  refresh: (refreshToken: string) =>
    request<TokenResponse>("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    }),

  me: cachedUser,

  workspace: (token: string) => request<WorkspaceRead | null>("/users/workspace", {}, token),

  updateMe: (token: string, data: { full_name?: string; password?: string }) =>
    request<UserRead>("/users/me", { method: "PATCH", body: JSON.stringify(data) }, token),

  getConsent: (token: string) =>
    request<{ id: string; ai_opt_in: boolean; terms_accepted: boolean } | null>(
      "/users/consent",
      {},
      token,
    ),

  updateConsent: (token: string, data: { ai_opt_in: boolean; terms_accepted: boolean }) =>
    request<{ id: string; ai_opt_in: boolean; terms_accepted: boolean }>(
      "/users/consent",
      { method: "PATCH", body: JSON.stringify(data) },
      token,
    ),

  forgotPassword: (email: string) =>
    request<void>("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),

  resetPassword: (token: string, newPassword: string) =>
    request<void>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password: newPassword }),
    }),

  sendVerification: (email: string) =>
    request<void>("/auth/send-verification", { method: "POST", body: JSON.stringify({ email }) }),

  verifyEmail: (token: string) =>
    request<void>(`/auth/verify-email?token=${encodeURIComponent(token)}`),

  listUsers: (token: string) =>
    request<{ id: string; full_name: string | null; email: string; role: string }[]>(
      "/users/list", {}, token,
    ),
};

// ── Profile API ────────────────────────────────────────────────────────────

export const profileApi = {
  getMe: (token: string) =>
    request<ProfileRead>("/profiles/me", {}, token),

  create: (
    token: string,
    data: Partial<Pick<ProfileRead, "headline" | "summary" | "location" | "phone" | "website" | "linkedin_url">>,
  ) =>
    request<ProfileRead>("/profiles", { method: "POST", body: JSON.stringify(data) }, token),

  update: (
    token: string,
    profileId: string,
    data: Record<string, unknown>,
  ) =>
    request<ProfileRead>(
      `/profiles/${profileId}`,
      { method: "PATCH", body: JSON.stringify(data) },
      token,
    ),

  getPublic: async (profileId: string): Promise<ProfileRead> => {
    const res = await fetch(`${API_BASE}/profiles/${profileId}`, {
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail ?? res.statusText);
    }
    return res.json();
  },

  uploadCV: (token: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${API_BASE}/profiles/me/cv`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body.detail ?? res.statusText);
      }
      return res.json() as Promise<CVUploadResponse>;
    });
  },
};

// ── AI API ─────────────────────────────────────────────────────────────────

export interface ParseCVResponse {
  parse_status: "parsed" | "fallback" | "failed";
  parser_version: string;
  confidence: number;
  token_count: number;
  structured_data: {
    name?: string | null;
    email?: string | null;
    phone?: string | null;
    location?: string | null;
    headline?: string | null;
    summary?: string | null;
    skills?: Array<{ name: string; level?: string | null; years_of_experience?: number | null; source?: string }>;
    work_experiences?: Array<{ company: string; title: string; location?: string | null; start_date?: string | null; end_date?: string | null; is_current?: boolean; description?: string | null; source?: string }>;
    educations?: Array<{ institution: string; degree?: string | null; field_of_study?: string | null; start_date?: string | null; end_date?: string | null; source?: string }>;
    _meta?: Record<string, unknown>;
  };
  raw_text_preview: string;
}

export const aiApi = {
  parseCv: (token: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${API_BASE}/ai/parse-cv`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body.detail ?? res.statusText);
      }
      return res.json() as Promise<ParseCVResponse>;
    });
  },
};

// ── Company API ────────────────────────────────────────────────────────────

export interface CompanyRead {
  id: string;
  name: string;
  website: string | null;
  description: string | null;
  location: string | null;
  logo_url: string | null;
  created_at: string;
}

export interface CompanyCreate {
  name: string;
  workspace_type?: "internal_hr" | "recruiter_agency" | "solo_recruiter" | "zeitarbeit";
  website?: string | null;
  description?: string | null;
  location?: string | null;
  logo_url?: string | null;
}

export const companyApi = {
  create: (token: string, data: CompanyCreate) =>
    request<CompanyRead>("/companies/", { method: "POST", body: JSON.stringify(data) }, token),

  getMine: (token: string) =>
    request<CompanyRead>("/companies/mine", {}, token),

  updateMine: (token: string, data: Partial<CompanyCreate>) =>
    request<CompanyRead>("/companies/mine", { method: "PATCH", body: JSON.stringify(data) }, token),
};

// ── Jobs API ────────────────────────────────────────────────────────────────

export interface JobPosting {
  id: string;
  title: string;
  company: string;
  location: string | null;
  description: string | null;
  url: string | null;
  is_remote: boolean;
  salary_min: number | null;
  salary_max: number | null;
  required_skills: string[];
  employment_type: string | null;
  category: string | null;
  source: string;
  posted_at: string | null;
  created_at: string;
  publication_status: "draft" | "published" | "archived";
  version: number;
  published_at: string | null;
  expires_at: string | null;
  archived_at: string | null;
}

export interface JobMatchResult {
  job: JobPosting;
  score: number;
  vector_similarity: number | null;
  skill_overlap: number | null;
  explanation: {
    matched_skills: string[];
    missing_skills: string[];
    skill_overlap_pct: number;
    vector_similarity_raw: number;
    matching_mode?: "skills_only" | "hybrid";
  } | null;
}

export interface JobFeedResponse {
  jobs: JobMatchResult[];
  total: number;
  page: number;
  page_size: number;
}

export const jobsApi = {
  seed: (token: string) =>
    request<{ seeded: number }>("/jobs/seed", { method: "POST" }, token),

  recommended: (
    token: string,
    params: {
      remote_only?: boolean;
      min_salary?: number;
      location?: string;
      category?: string;
      text_search?: string;
      page?: number;
      page_size?: number;
    } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.remote_only) q.set("remote_only", "true");
    if (params.min_salary) q.set("min_salary", String(params.min_salary));
    if (params.location) q.set("location", params.location);
    if (params.category) q.set("category", params.category);
    if (params.text_search) q.set("text_search", params.text_search);
    if (params.page) q.set("page", String(params.page));
    if (params.page_size) q.set("page_size", String(params.page_size));
    return request<JobFeedResponse>(`/jobs/recommended?${q}`, {}, token);
  },

  match: (token: string, jobId: string) =>
    request<JobMatchResult>("/jobs/match", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    }, token),
};

// ── Recruiter Job API ───────────────────────────────────────────────────────

export interface JobCreate {
  title: string;
  company: string;
  location?: string | null;
  description?: string | null;
  url?: string | null;
  is_remote?: boolean;
  salary_min?: number | null;
  salary_max?: number | null;
  required_skills?: string[];
  employment_type?: string | null;
}

export interface JobUpdate {
  expected_version: number;
  company?: string | null;
  title?: string | null;
  location?: string | null;
  description?: string | null;
  url?: string | null;
  is_remote?: boolean | null;
  salary_min?: number | null;
  salary_max?: number | null;
  required_skills?: string[] | null;
  employment_type?: string | null;
}

export interface RecruiterJobListResponse {
  jobs: JobPosting[];
  total: number;
  page: number;
  page_size: number;
}

export interface CandidateMatch {
  profile_id: string;
  full_name: string | null;
  headline: string | null;
  location: string | null;
  score: number;
  skill_overlap_pct: number;
  matched_skills: string[];
  missing_skills: string[];
  passed_gate: boolean;
}

export interface CandidatePipelineResponse {
  candidates: CandidateMatch[];
  total: number;
  page: number;
  page_size: number;
}

export interface ScorecardRead {
  id: string;
  application_id: string;
  recruiter_id: string | null;
  overall_rating: number | null;
  technical_rating: number | null;
  communication_rating: number | null;
  motivation_rating: number | null;
  notes: string | null;
  recommendation: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScorecardUpsert {
  overall_rating?: number | null;
  technical_rating?: number | null;
  communication_rating?: number | null;
  motivation_rating?: number | null;
  notes?: string | null;
  recommendation?: string | null;
}

export const scorecardApi = {
  get: (token: string, applicationId: string) =>
    request<ScorecardRead | null>(`/applications/${applicationId}/scorecard`, {}, token),

  upsert: (token: string, applicationId: string, data: ScorecardUpsert) =>
    request<ScorecardRead>(
      `/applications/${applicationId}/scorecard`,
      { method: "PUT", body: JSON.stringify(data) },
      token,
    ),
};

export interface RecruiterAnalytics {
  daily_applications: { date: string; count: number }[];
  funnel: Record<string, number>;
  top_jobs: { job_id: string; title: string; count: number }[];
  days: number;
}

export interface RecruiterInterviewRead {
  id: string;
  application_id: string;
  job_id: string;
  job_title: string;
  candidate_user_id: string;
  candidate_name: string | null;
  candidate_email: string;
  scheduled_at: string;
  status: string;
  meeting_url: string | null;
  notes: string | null;
  created_at: string;
}

export interface RecruiterInterviewsResponse {
  interviews: RecruiterInterviewRead[];
  total: number;
  page: number;
  page_size: number;
}

export const recruiterApi = {
  createJob: (token: string, data: JobCreate) =>
    request<JobPosting>("/jobs/recruiter", { method: "POST", body: JSON.stringify(data) }, token),

  getJob: (token: string, jobId: string) => request<JobPosting>(`/jobs/recruiter/${jobId}`, {}, token),

  listJobs: (token: string, page = 1, page_size = 20) =>
    request<RecruiterJobListResponse>(`/jobs/recruiter?page=${page}&page_size=${page_size}`, {}, token),

  updateJob: (token: string, id: string, data: JobUpdate) =>
    request<JobPosting>(`/jobs/recruiter/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  deleteJob: (token: string, id: string, version: number) =>
    request<void>(`/jobs/recruiter/${id}?expected_version=${version}`, { method: "DELETE" }, token),

  publication: (token: string, job: JobPosting, action: "publish" | "withdraw" | "archive", data: { expires_at?: string; rights_confirmed?: boolean; note?: string } = {}, imported = false) =>
    request<JobPosting>(`/jobs/${imported ? "import-review" : "recruiter"}/${job.id}/publication/${action}`, { method: "POST", body: JSON.stringify({ ...data, expected_version: job.version }) }, token),

  publicationEvents: (token: string, id: string) =>
    request<{ id: string; action: string; version: number; note: string | null; created_at: string }[]>(`/jobs/recruiter/${id}/publication-events`, {}, token),

  importedJobs: (token: string, offset = 0) => request<JobPosting[]>(`/jobs/import-review?offset=${offset}`, {}, token),
  updateImportedJob: (token: string, job: JobPosting, data: JobCreate) => request<JobPosting>(`/jobs/import-review/${job.id}`, { method: "PATCH", body: JSON.stringify({ ...data, expected_version: job.version }) }, token),

  getCandidates: (token: string, jobId: string, page = 1, page_size = 20) =>
    request<CandidatePipelineResponse>(
      `/jobs/recruiter/${jobId}/candidates?page=${page}&page_size=${page_size}`,
      {},
      token,
    ),

  getApplications: (token: string, jobId: string, page = 1, page_size = 20) =>
    request<{ applications: RecruiterApplication[]; total: number; page: number; page_size: number }>(
      `/jobs/recruiter/${jobId}/applications?page=${page}&page_size=${page_size}`,
      {},
      token,
    ),

  updateApplicationStatus: (token: string, jobId: string, appId: string, status: string, note?: string) =>
    request<{ id: string; status: string }>(
      `/jobs/recruiter/${jobId}/applications/${appId}`,
      { method: "PATCH", body: JSON.stringify({ status, note }) },
      token,
    ),

  getDashboardStats: (token: string) =>
    request<RecruiterDashboardStats>("/jobs/recruiter/stats", {}, token),

  getCandidateProfile: (token: string, userId: string) =>
    request<CandidateProfileFull>(`/jobs/recruiter/candidates/${userId}/profile`, {}, token),

  searchCandidates: (
    token: string,
    params: { query?: string; skills?: string[]; location?: string; available_only?: boolean; page?: number; page_size?: number } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.query) q.set("query", params.query);
    if (params.location) q.set("location", params.location);
    if (params.available_only) q.set("available_only", "true");
    if (params.page) q.set("page", String(params.page));
    if (params.page_size) q.set("page_size", String(params.page_size));
    (params.skills ?? []).forEach((s) => q.append("skills", s));
    return request<CandidateSearchResponse>(`/jobs/recruiter/candidates?${q}`, {}, token);
  },

  getAllApplications: (
    token: string,
    params: { status?: string; page?: number; page_size?: number; application_id?: string } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.application_id) q.set("application_id", params.application_id);
    if (params.page) q.set("page", String(params.page));
    if (params.page_size) q.set("page_size", String(params.page_size));
    return request<RecruiterAllApplicationsResponse>(
      `/jobs/recruiter/applications?${q}`,
      {},
      token,
    );
  },

  exportApplicationsCsv: async (token: string, status?: string): Promise<void> => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    const res = await fetch(`${API_BASE}/jobs/recruiter/applications/export?${q}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new ApiError(res.status, "Export fehlgeschlagen.");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "bewerbungen.csv";
    a.click();
    URL.revokeObjectURL(url);
  },

  generateJobLinkedInPost: (token: string, jobId: string) =>
    request<LinkedInShareResponse>(`/jobs/recruiter/jobs/${jobId}/share/linkedin`, { method: "POST" }, token),

  generatePlacementLinkedInPost: (token: string, data: { position: string; company: string; category?: string }) =>
    request<LinkedInShareResponse>("/jobs/recruiter/placements/share/linkedin", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  bulkUpdateApplications: (token: string, applicationIds: string[], status: string) =>
    request<{ updated: number; requested: number }>(
      "/jobs/recruiter/applications/bulk",
      { method: "PATCH", body: JSON.stringify({ application_ids: applicationIds, status }) },
      token,
    ),

  listInterviews: (
    token: string,
    params: { interview_status?: string; upcoming_only?: boolean; page?: number; page_size?: number } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.interview_status) q.set("interview_status", params.interview_status);
    if (params.upcoming_only) q.set("upcoming_only", "true");
    if (params.page) q.set("page", String(params.page));
    if (params.page_size) q.set("page_size", String(params.page_size));
    return request<RecruiterInterviewsResponse>(`/jobs/recruiter/interviews?${q}`, {}, token);
  },

  cancelInterview: (token: string, applicationId: string) =>
    request<void>(
      `/applications/${applicationId}/interview`,
      { method: "PATCH", body: JSON.stringify({ status: "cancelled" }) },
      token,
    ),

  getAnalytics: (token: string, days = 30) =>
    request<RecruiterAnalytics>(`/jobs/recruiter/analytics?days=${days}`, {}, token),
};

export interface CandidateSearchResult {
  user_id: string;
  profile_id: string;
  full_name: string | null;
  headline: string | null;
  location: string | null;
  completeness_score: number;
}

export interface CandidateSearchResponse {
  candidates: CandidateSearchResult[];
  total: number;
  page: number;
  page_size: number;
}

export interface RecruiterApplication {
  id: string;
  user_id: string;
  candidate_name: string | null;
  candidate_headline: string | null;
  candidate_location: string | null;
  status: string;
  applied_at: string | null;
  notes: string | null;
  created_at: string;
  // Pipeline Builder
  pipeline_stage_id: string | null;
  pipeline_stage_name: string | null;
  pipeline_stage_color: string | null;
}

export interface RecruiterAllApplication {
  id: string;
  user_id: string;
  job_id: string | null;
  job_title: string | null;
  candidate_name: string | null;
  candidate_headline: string | null;
  candidate_location: string | null;
  status: string;
  applied_at: string | null;
  created_at: string;
  notes: string | null;
}

export interface RecruiterAllApplicationsResponse {
  applications: RecruiterAllApplication[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApplyResponse {
  application_id: string;
  job_id: string;
  status: string;
  message: string;
}

export const jobApplicationApi = {
  apply: (token: string, jobId: string, notes?: string) =>
    request<ApplyResponse>(
      `/jobs/${jobId}/apply`,
      { method: "POST", body: JSON.stringify({ notes: notes ?? null }) },
      token,
    ),
};

// ── Job Alerts API ─────────────────────────────────────────────────────────────

export interface JobAlertRead {
  id: string;
  keywords: string | null;
  location: string | null;
  remote_only: boolean;
  min_salary: number | null;
  category: string | null;
  min_score: number;
  is_active: boolean;
  created_at: string;
}

export interface JobAlertCreate {
  keywords?: string | null;
  location?: string | null;
  remote_only?: boolean;
  min_salary?: number | null;
  category?: string | null;
  min_score?: number;
}

export const jobAlertsApi = {
  list: (token: string) =>
    request<JobAlertRead[]>("/jobs/alerts", {}, token),

  create: (token: string, data: JobAlertCreate) =>
    request<JobAlertRead>("/jobs/alerts", { method: "POST", body: JSON.stringify(data) }, token),

  delete: (token: string, alertId: string) =>
    request<void>(`/jobs/alerts/${alertId}`, { method: "DELETE" }, token),
};

// ── Saved Jobs API ────────────────────────────────────────────────────────────

export const savedJobsApi = {
  save: (token: string, jobId: string) =>
    request<{ job_id: string; saved: boolean }>(`/jobs/${jobId}/save`, { method: "POST" }, token),

  unsave: (token: string, jobId: string) =>
    request<void>(`/jobs/${jobId}/save`, { method: "DELETE" }, token),

  listIds: (token: string) =>
    request<string[]>("/jobs/saved/ids", {}, token),

  list: (token: string) =>
    request<JobPosting[]>("/jobs/saved", {}, token),
};

// ── Applications API ────────────────────────────────────────────────────────

export type ApplicationStatus =
  | "research"
  | "applied"
  | "screening"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn";

export interface ApplicationHistoryEntry {
  id: string;
  from_status: ApplicationStatus | null;
  to_status: ApplicationStatus;
  note: string | null;
  changed_at: string;
}

export interface ApplicationRead {
  id: string;
  user_id: string;
  job_id: string | null;
  company: string;
  position: string;
  job_url: string | null;
  notes: string | null;
  source_platform: string | null;
  status: ApplicationStatus;
  applied_at: string | null;
  created_at: string;
  updated_at: string;
  history: ApplicationHistoryEntry[];
}

export interface KanbanColumn {
  status: ApplicationStatus;
  label: string;
  applications: ApplicationRead[];
}

export interface KanbanBoard {
  columns: KanbanColumn[];
  total: number;
}

// Pipeline Kanban board (Sprint 2.4)
export interface KanbanCard {
  application_id: string;
  candidate_name: string | null;
  candidate_email: string;
  job_title: string;
  company: string;
  status: string;
  entered_at: string;
}

export interface KanbanBoardColumn {
  stage_id: string;
  stage_name: string;
  stage_color: string | null;
  position: number;
  is_terminal: boolean;
  cards: KanbanCard[];
}

export interface KanbanBoardRead {
  template_id: string;
  template_name: string;
  columns: KanbanBoardColumn[];
}

export interface ApplicationCreate {
  company: string;
  position: string;
  job_url?: string | null;
  notes?: string | null;
  job_id?: string | null;
  status?: ApplicationStatus;
}

export interface ApplicationUpdate {
  company?: string | null;
  position?: string | null;
  job_url?: string | null;
  notes?: string | null;
  status?: ApplicationStatus | null;
  note?: string | null;
}

export const applicationsApi = {
  getKanban: (token: string) =>
    request<KanbanBoard>("/applications/kanban", {}, token),

  list: (token: string) =>
    request<ApplicationRead[]>("/applications", {}, token),

  create: (token: string, data: ApplicationCreate) =>
    request<ApplicationRead>("/applications", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  update: (token: string, id: string, data: ApplicationUpdate) =>
    request<ApplicationRead>(`/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }, token),

  delete: (token: string, id: string) =>
    request<void>(`/applications/${id}`, { method: "DELETE" }, token),
};

// ── Notifications API ────────────────────────────────────────────────────────

export interface NotificationRead {
  id: string;
  type: string;
  title: string;
  body: string;
  meta: Record<string, unknown> | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationListResponse {
  notifications: NotificationRead[];
  unread_count: number;
}

export const notificationsApi = {
  list: cachedNotifications,

  readAll: async (token: string) => {
    const result = await request<{ marked_read: number }>(
      "/notifications/read-all",
      { method: "POST" },
      token,
    );
    if (notificationCache?.token === token) {
      notificationCache = {
        ...notificationCache,
        value: {
          ...notificationCache.value,
          unread_count: 0,
          notifications: notificationCache.value.notifications.map((notification) => ({
            ...notification,
            read_at: notification.read_at ?? new Date().toISOString(),
          })),
        },
      };
    }
    return result;
  },

  readOne: (token: string, id: string) =>
    request<{ ok: boolean }>(`/notifications/${id}/read`, { method: "PATCH" }, token),
};

// ── Interview Schedule API ────────────────────────────────────────────────────

export interface InterviewScheduleRead {
  id: string;
  application_id: string;
  proposed_by: string | null;
  scheduled_at: string;
  status: "proposed" | "confirmed" | "declined" | "cancelled";
  meeting_url: string | null;
  notes: string | null;
  created_at: string;
}

export const interviewScheduleApi = {
  propose: (
    token: string,
    applicationId: string,
    data: { scheduled_at: string; meeting_url?: string | null; notes?: string | null },
  ) =>
    request<InterviewScheduleRead>(
      `/applications/${applicationId}/interview`,
      { method: "POST", body: JSON.stringify(data) },
      token,
    ),

  get: (token: string, applicationId: string) =>
    request<InterviewScheduleRead | null>(
      `/applications/${applicationId}/interview`,
      {},
      token,
    ),

  updateStatus: (
    token: string,
    applicationId: string,
    status: "confirmed" | "declined" | "cancelled",
    notes?: string,
  ) =>
    request<InterviewScheduleRead>(
      `/applications/${applicationId}/interview`,
      { method: "PATCH", body: JSON.stringify({ status, notes }) },
      token,
    ),
};

// ── Market Stats + Gap Analysis API ──────────────────────────────────────────

export interface SalaryStat {
  category: string;
  count: number;
  salary_min_avg: number | null;
  salary_max_avg: number | null;
  salary_mid: number | null;
}

export interface MarketStats {
  total_jobs: number;
  remote_count: number;
  remote_pct: number;
  top_skills: Array<{ skill: string; count: number; pct: number }>;
  categories: Array<{ category: string; count: number; pct: number }>;
  salary_by_category: SalaryStat[];
  employment_types: Array<{ type: string; count: number }>;
}

export interface SkillGap {
  skill: string;
  market_demand_pct: number;
  course_url: string | null;
  category: string | null;
  difficulty: string | null;
  est_hours: number | null;
  priority_score: number;
}

export interface LearningPath {
  category: string;
  skills: SkillGap[];
  total_hours: number;
}

export interface ProfileGapAnalysis {
  my_skills: string[];
  top_gaps: SkillGap[];
  coverage_pct: number;
  strong_skills: string[];
  learning_paths: LearningPath[];
}

export const marketApi = {
  stats: (token: string) =>
    request<MarketStats>("/jobs/market/stats", {}, token),

  myGaps: (token: string) =>
    request<ProfileGapAnalysis>("/profiles/me/gaps", {}, token),
};

// ── Partner Placements API ────────────────────────────────────────────────────

export interface PlacementRead {
  id: string;
  job_id: string | null;
  application_id: string;
  recruiter_id: string;
  candidate_name: string | null;
  position_title: string | null;
  company_name: string | null;
  commission_pct: number;
  annual_salary: number | null;
  commission_eur: number | null;
  notes: string | null;
  placed_at: string;
  created_at: string;
}

export interface PlacementCreate {
  commission_pct?: number;
  annual_salary?: number | null;
  notes?: string | null;
}

export interface PlacementStats {
  total_placements: number;
  total_commission_eur: number;
  avg_commission_eur: number;
  avg_commission_pct: number;
  placements_this_month: number;
  commission_this_month: number;
}

// ── LinkedIn Content-Kit ──────────────────────────────────────────────────────

export interface LinkedInShareResponse {
  text: string;
  post_type: string;
  ai_generated: boolean;
  disclaimer: string;
}

// ── Recruiter Dashboard Stats ─────────────────────────────────────────────────

export interface RecruiterDashboardStats {
  total_jobs: number;
  total_applications: number;
  applications_by_status: Record<string, number>;
  interviews_this_week: number;
  new_applications_today: number;
}

export interface CandidateProfileFull {
  user_id: string;
  full_name: string | null;
  email: string;
  headline: string | null;
  summary: string | null;
  location: string | null;
  phone: string | null;
  linkedin_url: string | null;
  completeness_score: number;
  work_experiences: Array<{
    company: string; title: string;
    start_date: string | null; end_date: string | null;
    is_current: boolean; description: string | null;
  }>;
  educations: Array<{
    institution: string; degree: string | null;
    field_of_study: string | null;
    start_date: string | null; end_date: string | null;
  }>;
  skills: Array<{ name: string; level: string | null; category: string | null }>;
}

export const placementApi = {
  place: (token: string, applicationId: string, data: PlacementCreate) =>
    request<PlacementRead>(`/recruiter/placements/applications/${applicationId}/place`, {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  list: (token: string) =>
    request<PlacementRead[]>("/recruiter/placements/", {}, token),

  stats: (token: string) =>
    request<PlacementStats>("/recruiter/placements/stats", {}, token),
};

// ── Zeitarbeit API ────────────────────────────────────────────────────────────

export interface AssignmentRead {
  id: string;
  recruiter_id: string;
  company_id: string | null;
  title: string;
  description: string | null;
  required_skills: string[];
  location: string | null;
  shift: string | null;
  hourly_rate: number | null;
  start_date: string | null;
  end_date: string | null;
  status: string;
  max_duration_months: number;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssignmentCreate {
  title: string;
  description?: string | null;
  required_skills?: string[];
  location?: string | null;
  shift?: string | null;
  hourly_rate?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  company_id?: string | null;
  max_duration_months?: number;
  notes?: string | null;
}

export interface DispositionRead {
  id: string;
  assignment_id: string;
  worker_id: string;
  worker_name: string | null;
  worker_headline: string | null;
  score: number;
  matched_skills: string[];
  missing_skills: string[];
  status: string;
  started_at: string | null;
  ended_at: string | null;
  notes: string | null;
  created_at: string;
}

export interface AvailabilityRead {
  id: string;
  user_id: string;
  is_in_pool: boolean;
  available_from: string | null;
  available_until: string | null;
  preferred_shift: string | null;
  preferred_location: string | null;
  max_commute_km: number | null;
  total_placed_months: number;
  notes: string | null;
  updated_at: string;
  aueg_remaining_months: number;
  aueg_status: "green" | "yellow" | "red";
}

export interface ZeitarbeitStats {
  total_assignments: number;
  active_assignments: number;
  workers_in_pool: number;
  total_dispositions: number;
  active_dispositions: number;
  avg_fill_score: number;
}

export const zeitarbeitApi = {
  createAssignment: (token: string, data: AssignmentCreate) =>
    request<AssignmentRead>("/zeitarbeit/orders", { method: "POST", body: JSON.stringify(data) }, token),

  listAssignments: (token: string, status?: string) =>
    request<AssignmentRead[]>(`/zeitarbeit/orders${status ? `?status=${status}` : ""}`, {}, token),

  updateAssignment: (token: string, id: string, data: Partial<AssignmentCreate> & { status?: string }) =>
    request<AssignmentRead>(`/zeitarbeit/orders/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  deleteAssignment: (token: string, id: string) =>
    request<void>(`/zeitarbeit/orders/${id}`, { method: "DELETE" }, token),

  stats: (token: string) =>
    request<ZeitarbeitStats>("/zeitarbeit/orders/stats", {}, token),

  runMatching: (token: string, assignmentId: string) =>
    request<DispositionRead[]>(`/zeitarbeit/orders/${assignmentId}/match`, { method: "POST" }, token),

  getDispositions: (token: string, assignmentId: string) =>
    request<DispositionRead[]>(`/zeitarbeit/orders/${assignmentId}/dispositions`, {}, token),

  updateDisposition: (token: string, assignmentId: string, workerId: string, data: { status: string; started_at?: string | null; ended_at?: string | null; notes?: string | null }) =>
    request<DispositionRead>(`/zeitarbeit/orders/${assignmentId}/dispositions/${workerId}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  getPool: (token: string) =>
    request<AvailabilityRead[]>("/zeitarbeit/pool", {}, token),

  getMyAvailability: (token: string) =>
    request<AvailabilityRead | null>("/zeitarbeit/availability/me", {}, token),

  setMyAvailability: (token: string, data: Partial<AvailabilityRead>) =>
    request<AvailabilityRead>("/zeitarbeit/availability/me", { method: "PUT", body: JSON.stringify(data) }, token),
};

// ── Feedback API ─────────────────────────────────────────────────────────────

export const feedbackApi = {
  submit: (
    data: { category?: string; message: string; email?: string; page_url?: string },
    token?: string,
  ) =>
    request<{ id: string; status: string }>("/feedback", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),
};

// ── Export API ───────────────────────────────────────────────────────────────

export const exportApi = {
  pdf: (token: string) =>
    fetch(`${API_BASE}/profiles/me/export/pdf`, {
      headers: { Authorization: `Bearer ${token}` },
    }),

  docx: (token: string) =>
    fetch(`${API_BASE}/profiles/me/export/docx`, {
      headers: { Authorization: `Bearer ${token}` },
    }),

  linkedin: (token: string) =>
    request<{ text: string }>("/profiles/me/export/linkedin", {}, token),

  link: (token: string) =>
    request<{ url: string; profile_id: string }>("/profiles/me/export/link", { method: "POST" }, token),
  revokeLink: (token: string) =>
    request<void>("/profiles/me/export/link", { method: "DELETE" }, token),
};

// ── Interview Prep API ────────────────────────────────────────────────────────

export interface InterviewQuestion {
  category: string;
  question: string;
  star_tip: string | null;
  example_answer_hint: string;
}

export interface InterviewPrepResponse {
  questions: InterviewQuestion[];
  general_tips: string[];
  model_used: string;
  ai_generated: boolean;
  disclaimer: string;
}

export const interviewApi = {
  generate: (
    token: string,
    data: {
      company: string;
      position: string;
      job_id?: string | null;
      job_description?: string | null;
    },
  ) =>
    request<InterviewPrepResponse>("/ai/interview-prep", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),
};

// ── Cover Letter API ─────────────────────────────────────────────────────────

export interface CoverLetterRead {
  id: string;
  user_id: string;
  job_id: string | null;
  application_id: string | null;
  company: string;
  position: string;
  tone: string;
  generated_text: string;
  model_used: string;
  ai_generated: boolean;
  created_at: string;
}

export interface CVAdjustResponse {
  highlighted_skills: string[];
  highlighted_experience_ids: string[];
  suggested_summary: string;
  tips: string[];
  model_used: string;
  ai_generated: boolean;
  disclaimer: string;
}

export const coverLetterApi = {
  generate: (
    token: string,
    data: {
      company: string;
      position: string;
      job_id?: string | null;
      application_id?: string | null;
      job_description?: string | null;
      company_context?: string | null;
      tone?: string;
    },
  ) =>
    request<CoverLetterRead>("/ai/cover-letter", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  list: (token: string) =>
    request<CoverLetterRead[]>("/ai/cover-letters", {}, token),

  delete: (token: string, id: string) =>
    request<void>(`/ai/cover-letters/${id}`, { method: "DELETE" }, token),

  adjustCv: (
    token: string,
    data: {
      company: string;
      position: string;
      job_id?: string | null;
      job_description?: string | null;
    },
  ) =>
    request<CVAdjustResponse>("/ai/cv-adjust", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),
};

// ── Workforce Canvas ──────────────────────────────────────────────────────────

export interface PoolWorkerRead {
  user_id: string;
  full_name: string | null;
  headline: string | null;
  location: string | null;
  aueg_remaining_months: number;
  aueg_status: "green" | "yellow" | "red";
  total_placed_months: number;
  preferred_shift: string | null;
  skills: string[];
}

export interface JobCanvasRead {
  assignment: AssignmentRead;
  dispositions: DispositionRead[];
  pool_size: number;
}

export interface WorkerCanvasRead {
  worker: PoolWorkerRead;
  active_assignments: AssignmentRead[];
  recommended_assignments: AssignmentRead[];
}

export interface CanvasAssignPayload {
  assignment_id: string;
  worker_id: string;
  status?: string;
}

export const canvasApi = {
  getPool: (token: string) =>
    request<PoolWorkerRead[]>("/zeitarbeit/canvas/pool", {}, token),

  getJobView: (token: string, assignmentId: string) =>
    request<JobCanvasRead>(`/zeitarbeit/canvas/job/${assignmentId}`, {}, token),

  getWorkerView: (token: string, workerId: string) =>
    request<WorkerCanvasRead>(`/zeitarbeit/canvas/worker/${workerId}`, {}, token),

  assign: (token: string, payload: CanvasAssignPayload) =>
    request<DispositionRead>("/zeitarbeit/canvas/assign", {
      method: "POST",
      body: JSON.stringify(payload),
    }, token),
};

// ── Vermerke ─────────────────────────────────────────────────────────────────

export type VermerkType =
  | "präferenz"
  | "warnhinweis"
  | "beziehungswissen"
  | "dokumentenhinweis"
  | "override_grund";

export type VermerkVisibility = "internal" | "partner" | "public";

export interface VermerkRead {
  id: string;
  author_id: string | null;
  candidate_id: string | null;
  application_id: string | null;
  assignment_id: string | null;
  type: VermerkType;
  text: string;
  valid_until: string | null;
  strength: number | null;
  visibility: VermerkVisibility;
  source: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface VermerkCreate {
  type: VermerkType;
  text: string;
  visibility?: VermerkVisibility;
  valid_until?: string | null;
  strength?: number | null;
  source?: string | null;
  candidate_id?: string | null;
  application_id?: string | null;
  assignment_id?: string | null;
}

export interface VermerkUpdate {
  text?: string;
  valid_until?: string | null;
  strength?: number | null;
  visibility?: VermerkVisibility;
  is_active?: boolean;
}

// ── Pipeline Builder ──────────────────────────────────────────────────────────

export interface PipelineStageRead {
  id: string;
  template_id: string;
  name: string;
  position: number;
  color: string | null;
  is_terminal: boolean;
  on_enter_actions: Record<string, unknown>[] | null;
  sla_hours: number | null;
  sla_escalate_to: string | null;
  requires_approval: boolean;
  approver_role: string | null;
  created_at: string;
  updated_at: string;
}

export interface PipelineTemplateRead {
  id: string;
  recruiter_id: string | null;
  company_id: string | null;
  name: string;
  is_default: boolean;
  stages: PipelineStageRead[];
  created_at: string;
  updated_at: string;
}

export interface PipelineStageCreate {
  name: string;
  position: number;
  color?: string | null;
  is_terminal?: boolean;
  on_enter_actions?: Record<string, unknown>[] | null;
  sla_hours?: number | null;
  sla_escalate_to?: string | null;
  requires_approval?: boolean;
  approver_role?: string | null;
}

export interface PipelineStageUpdate {
  name?: string;
  position?: number;
  color?: string | null;
  is_terminal?: boolean;
  on_enter_actions?: Record<string, unknown>[] | null;
  sla_hours?: number | null;
  sla_escalate_to?: string | null;
  requires_approval?: boolean;
  approver_role?: string | null;
}

export interface StageTransitionRequest {
  application_id: string;
  to_stage_id: string;
  note?: string | null;
}

export interface StageTransitionResponse {
  application_id: string;
  stage: PipelineStageRead;
}

export const pipelineApi = {
  listTemplates: (token: string) =>
    request<PipelineTemplateRead[]>("/pipeline/templates", {}, token),

  createTemplate: (token: string, data: { name: string; stages?: PipelineStageCreate[] }) =>
    request<PipelineTemplateRead>("/pipeline/templates", { method: "POST", body: JSON.stringify(data) }, token),

  updateTemplate: (token: string, id: string, data: { name?: string; is_default?: boolean }) =>
    request<PipelineTemplateRead>(`/pipeline/templates/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  deleteTemplate: (token: string, id: string) =>
    request<void>(`/pipeline/templates/${id}`, { method: "DELETE" }, token),

  addStage: (token: string, templateId: string, data: PipelineStageCreate) =>
    request<PipelineStageRead>(`/pipeline/templates/${templateId}/stages`, { method: "POST", body: JSON.stringify(data) }, token),

  updateStage: (token: string, stageId: string, data: PipelineStageUpdate) =>
    request<PipelineStageRead>(`/pipeline/stages/${stageId}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  deleteStage: (token: string, stageId: string) =>
    request<void>(`/pipeline/stages/${stageId}`, { method: "DELETE" }, token),

  transition: (token: string, data: StageTransitionRequest) =>
    request<StageTransitionResponse>("/pipeline/transitions", { method: "POST", body: JSON.stringify(data) }, token),

  getCurrentStage: (token: string, applicationId: string) =>
    request<PipelineStageRead | null>(`/pipeline/applications/${applicationId}/stage`, {}, token),

  getStageHistory: (token: string, applicationId: string) =>
    request<unknown[]>(`/pipeline/applications/${applicationId}/history`, {}, token),

  getKanban: (token: string, templateId: string) =>
    request<KanbanBoardRead>(`/pipeline/kanban/${templateId}`, {}, token),
};

// ── Map View ──────────────────────────────────────────────────────────────────

export interface MapAssignmentOut {
  id: string;
  title: string;
  location: string | null;
  lat: number | null;
  lng: number | null;
  status: string;
  required_skills: string[];
  worker_count: number;
}

export interface MapWorkerOut {
  user_id: string;
  full_name: string | null;
  preferred_location: string | null;
  lat: number | null;
  lng: number | null;
  is_in_pool: boolean;
  aueg_status: "green" | "yellow" | "red";
  aueg_remaining_months: number;
  current_assignment_id: string | null;
  current_assignment_title: string | null;
}

export interface MapDataResponse {
  assignments: MapAssignmentOut[];
  workers: MapWorkerOut[];
}

export const mapsApi = {
  getData: (token: string) =>
    request<MapDataResponse>("/maps/data", {}, token),
};

export const vermerkeApi = {
  create: (token: string, data: VermerkCreate) =>
    request<VermerkRead>("/vermerke/", { method: "POST", body: JSON.stringify(data) }, token),

  listForCandidate: (token: string, candidateId: string) =>
    request<VermerkRead[]>(`/vermerke/candidate/${candidateId}`, {}, token),

  listForApplication: (token: string, applicationId: string) =>
    request<VermerkRead[]>(`/vermerke/application/${applicationId}`, {}, token),

  listForAssignment: (token: string, assignmentId: string) =>
    request<VermerkRead[]>(`/vermerke/assignment/${assignmentId}`, {}, token),

  update: (token: string, vermerkId: string, data: VermerkUpdate) =>
    request<VermerkRead>(`/vermerke/${vermerkId}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  delete: (token: string, vermerkId: string) =>
    request<void>(`/vermerke/${vermerkId}`, { method: "DELETE" }, token),
};

// ── Admin Hub ──────────────────────────────────────────────────────────────

export interface CustomerRead {
  id: string;
  name: string;
  slug: string;
  type: WorkspaceType;
  plan: "free" | "starter" | "professional" | "enterprise";
  status: "trial" | "active" | "suspended" | "churned";
  contact_email: string | null;
  contact_name: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  country: string;
  notes: string | null;
  trial_ends_at: string | null;
  contract_start: string | null;
  contract_end: string | null;
  created_at: string;
  updated_at: string;
  user_count: number;
  modules: string[];
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  // White-Label (Sprint 2.6)
  custom_domain: string | null;
  primary_color: string | null;
  logo_url: string | null;
}

export interface TenantBranding {
  name: string;
  slug: string;
  plan: string;
  status: string;
  custom_domain: string | null;
  primary_color: string;
  logo_url: string | null;
}

// Sprint 2.7 – Public Job Listings
export interface PublicJobRead {
  id: string;
  title: string;
  company: string;
  location: string | null;
  description: string | null;
  url: string | null;
  is_remote: boolean;
  salary_min: number | null;
  salary_max: number | null;
  required_skills: string[];
  employment_type: string | null;
  category: string | null;
  source: string;
  posted_at: string | null;
  created_at: string;
}

export interface CustomerCreate {
  name: string;
  slug: string;
  type: string;
  plan: string;
  status: string;
  contact_email?: string | null;
  contact_name?: string | null;
  phone?: string | null;
  address?: string | null;
  city?: string | null;
  country?: string;
  notes?: string | null;
  trial_ends_at?: string | null;
  contract_start?: string | null;
  contract_end?: string | null;
}

export interface ModuleRead {
  module_key: string;
  enabled: boolean;
  usage_limit: number | null;
  usage_current: number;
  activated_at: string;
  expires_at: string | null;
}

export interface AdminStats {
  total_customers: number;
  active_customers: number;
  trial_customers: number;
  suspended_customers: number;
  by_type: Record<string, number>;
  by_plan: Record<string, number>;
  top_modules: Array<{ module_key: string; count: number }>;
}

export interface ImportRun {
  id: string;
  source: string;
  status: "running" | "done" | "error";
  jobs_found: number;
  jobs_new: number;
  error_msg: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface ModuleCatalogEntry {
  key: string;
  name: string;
  category: string;
}

export const adminApi = {
  listCustomers: (token: string, params?: { status?: string; type?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.type) q.set("type", params.type);
    const qs = q.toString() ? `?${q.toString()}` : "";
    return request<CustomerRead[]>(`/admin/customers${qs}`, {}, token);
  },

  createCustomer: (token: string, data: CustomerCreate) =>
    request<CustomerRead>("/admin/customers", { method: "POST", body: JSON.stringify(data) }, token),

  getCustomer: (token: string, id: string) =>
    request<CustomerRead>(`/admin/customers/${id}`, {}, token),

  updateCustomer: (token: string, id: string, data: Partial<CustomerCreate>) =>
    request<CustomerRead>(`/admin/customers/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  archiveCustomer: (token: string, id: string) =>
    request<void>(`/admin/customers/${id}`, { method: "DELETE" }, token),

  getModules: (token: string, customerId: string) =>
    request<ModuleRead[]>(`/admin/customers/${customerId}/modules`, {}, token),

  toggleModule: (token: string, customerId: string, moduleKey: string, data: { enabled: boolean; usage_limit?: number | null }) =>
    request<ModuleRead>(`/admin/customers/${customerId}/modules/${moduleKey}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }, token),

  getModuleCatalog: (token: string) =>
    request<ModuleCatalogEntry[]>("/admin/modules", {}, token),

  getStats: (token: string) =>
    request<AdminStats>("/admin/stats", {}, token),

  getImportRuns: (token: string, limit = 50) =>
    request<ImportRun[]>(`/admin/import-runs?limit=${limit}`, {}, token),

  triggerImport: (token: string, source = "all") =>
    request<{ status: string; source: string }>("/admin/import-runs", {
      method: "POST",
      body: JSON.stringify({ source }),
    }, token),

  assignTenant: (token: string, userId: string, tenantId: string | null) =>
    request<void>("/admin/assign-tenant", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, tenant_id: tenantId }),
    }, token),

  setCustomDomain: (token: string, customerId: string, customDomain: string | null) =>
    request<CustomerRead>(`/admin/customers/${customerId}/custom-domain`, {
      method: "PUT",
      body: JSON.stringify({ custom_domain: customDomain }),
    }, token),

  getLogoUploadUrl: (token: string, customerId: string, contentType: string) =>
    request<{ upload_url: string; logo_url: string; expires_in: number }>(
      `/admin/customers/${customerId}/logo-presign?content_type=${encodeURIComponent(contentType)}`,
      { method: "POST" },
      token,
    ),

  updateBranding: (token: string, customerId: string, data: { primary_color?: string | null; logo_url?: string | null }) =>
    request<CustomerRead>(`/admin/customers/${customerId}/branding`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }, token),
};

// ── Public Branding API ─────────────────────────────────────────────────────

export const publicApi = {
  getBrandingByDomain: (domain: string) =>
    request<TenantBranding>(`/public/branding?domain=${encodeURIComponent(domain)}`),

  getBrandingBySlug: (slug: string) =>
    request<TenantBranding>(`/public/branding/slug/${encodeURIComponent(slug)}`),

  getPublicJobs: (slug: string, limit = 50, offset = 0) =>
    request<PublicJobRead[]>(
      `/public/jobs?slug=${encodeURIComponent(slug)}&limit=${limit}&offset=${offset}`
    ),

  getPublicJob: (jobId: string, slug?: string) =>
    request<PublicJobRead>(`/public/jobs/${jobId}${slug ? `?slug=${encodeURIComponent(slug)}` : ""}`),
};

// ── Billing API ─────────────────────────────────────────────────────────────

export const billingApi = {
  createCheckout: (token: string, plan: string) =>
    request<{ url: string }>("/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan }),
    }, token),

  openPortal: (token: string) =>
    request<{ url: string }>("/billing/portal", {}, token),
};

// ── Org Charts API ───────────────────────────────────────────────────────────

export type OrgNodeStatus = "filled" | "open" | "temp" | "contractor" | "planned";
export type OrgEdgeType = "solid" | "dotted" | "functional";
export type OrgChartType = "hierarchical" | "matrix" | "flat" | "divisional";

export interface OrgNodeRead {
  id: string;
  chart_id: string;
  title: string;
  department: string | null;
  person_name: string | null;
  person_email: string | null;
  person_id: string | null;
  job_posting_id: string | null;
  status: OrgNodeStatus;
  pos_x: number;
  pos_y: number;
  node_width: number;
  node_height: number;
  color: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface OrgEdgeRead {
  id: string;
  chart_id: string;
  source_id: string;
  target_id: string;
  edge_type: OrgEdgeType;
  label: string | null;
  created_at: string;
}

export interface OrgChartRead {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  chart_type: OrgChartType;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  node_count: number;
}

export interface OrgChartFull extends OrgChartRead {
  nodes: OrgNodeRead[];
  edges: OrgEdgeRead[];
}

export interface OrgNodeWrite {
  id?: string;
  title: string;
  department?: string | null;
  person_name?: string | null;
  person_email?: string | null;
  person_id?: string | null;
  job_posting_id?: string | null;
  status: OrgNodeStatus;
  pos_x: number;
  pos_y: number;
  node_width?: number;
  node_height?: number;
  color?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface OrgEdgeWrite {
  id?: string;
  source_id: string;
  target_id: string;
  edge_type: OrgEdgeType;
  label?: string | null;
}

export interface BulkSavePayload {
  nodes: OrgNodeWrite[];
  edges: OrgEdgeWrite[];
  name?: string;
  description?: string;
}

export const orgChartApi = {
  list: (token: string) =>
    request<OrgChartRead[]>("/org-charts", {}, token),

  create: (token: string, data: { name: string; description?: string; chart_type: OrgChartType }) =>
    request<OrgChartFull>("/org-charts", { method: "POST", body: JSON.stringify(data) }, token),

  get: (token: string, id: string) =>
    request<OrgChartFull>(`/org-charts/${id}`, {}, token),

  update: (token: string, id: string, data: { name?: string; description?: string; chart_type?: OrgChartType }) =>
    request<OrgChartRead>(`/org-charts/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  delete: (token: string, id: string) =>
    request<void>(`/org-charts/${id}`, { method: "DELETE" }, token),

  save: (token: string, id: string, payload: BulkSavePayload) =>
    request<OrgChartFull>(`/org-charts/${id}/save`, { method: "PUT", body: JSON.stringify(payload) }, token),
};


// ── DMS (Sprint 3.1) ──────────────────────────────────────────────────────────

export interface DocCategoryRead {
  id: string;
  tenant_id: string | null;
  name: string;
  slug: string;
  color: string;
  icon: string;
  sort_order: number;
  is_system: boolean;
  created_at: string;
}

export interface DocumentRead {
  id: string;
  tenant_id: string;
  created_by: string | null;
  name: string;
  original_filename: string;
  file_url: string;
  mime_type: string;
  file_size: number;
  checksum: string | null;
  category_id: string | null;
  tags: string[] | null;
  description: string | null;
  is_template: boolean;
  linked_entity_type: string | null;
  linked_entity_id: string | null;
  version_number: number;
  parent_document_id: string | null;
  is_latest_version: boolean;
  visibility: string;
  share_token: string | null;
  share_expires_at: string | null;
  expires_at: string | null;
  expires_reminder_days: number;
  ocr_text: string | null;
  thumbnail_url: string | null;
  processing_status: string;
  status: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  category: DocCategoryRead | null;
}

export interface DocShareRead {
  id: string;
  document_id: string;
  shared_by: string | null;
  share_token: string;
  shared_with_email: string | null;
  access_type: string;
  expires_at: string | null;
  accessed_count: number;
  last_accessed_at: string | null;
  created_at: string;
}

export interface DocActivityRead {
  id: string;
  document_id: string;
  user_id: string | null;
  action: string;
  metadata_: Record<string, unknown> | null;
  created_at: string;
}

export interface DocCommentRead {
  id: string;
  document_id: string;
  user_id: string | null;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentDetail extends DocumentRead {
  shares: DocShareRead[];
  activity: DocActivityRead[];
  comments: DocCommentRead[];
  versions: DocumentRead[];
}

export interface ExpiryDashboard {
  overdue: DocumentRead[];
  expiring_soon: DocumentRead[];
  ok: DocumentRead[];
}

export interface DocumentPresignResponse {
  upload_url: string;
  file_url: string;
  original_filename: string;
  mime_type: string;
  file_size: number;
}

export const dmsApi = {
  // presign
  presign: (token: string, data: { filename: string; mime_type: string; file_size: number }) =>
    request<DocumentPresignResponse>("/documents/presign", { method: "POST", body: JSON.stringify(data) }, token),

  // CRUD
  list: (token: string, params?: Record<string, string>) =>
    request<DocumentRead[]>(`/documents${params ? "?" + new URLSearchParams(params) : ""}`, {}, token),

  get: (token: string, id: string) =>
    request<DocumentDetail>(`/documents/${id}`, {}, token),

  create: (token: string, data: Partial<DocumentRead> & { name: string; original_filename: string; file_url: string; mime_type: string }) =>
    request<DocumentRead>("/documents", { method: "POST", body: JSON.stringify(data) }, token),

  update: (token: string, id: string, data: Partial<DocumentRead>) =>
    request<DocumentRead>(`/documents/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  delete: (token: string, id: string) =>
    request<void>(`/documents/${id}`, { method: "DELETE" }, token),

  archive: (token: string, id: string) =>
    request<DocumentRead>(`/documents/${id}/archive`, { method: "POST" }, token),

  restore: (token: string, id: string) =>
    request<DocumentRead>(`/documents/${id}/restore`, { method: "POST" }, token),

  newVersion: (token: string, id: string, data: Partial<DocumentRead> & { name: string; original_filename: string; file_url: string; mime_type: string }) =>
    request<DocumentRead>(`/documents/${id}/new-version`, { method: "POST", body: JSON.stringify(data) }, token),

  versions: (token: string, id: string) =>
    request<DocumentRead[]>(`/documents/${id}/versions`, {}, token),

  // Shares
  createShare: (token: string, id: string, data: { shared_with_email?: string; access_type?: string; expires_at?: string; password?: string }) =>
    request<DocShareRead>(`/documents/${id}/shares`, { method: "POST", body: JSON.stringify(data) }, token),

  listShares: (token: string, id: string) =>
    request<DocShareRead[]>(`/documents/${id}/shares`, {}, token),

  revokeShare: (token: string, id: string, shareId: string) =>
    request<void>(`/documents/${id}/shares/${shareId}`, { method: "DELETE" }, token),

  // Activity
  getActivity: (token: string, id: string) =>
    request<DocActivityRead[]>(`/documents/${id}/activity`, {}, token),

  // Comments
  listComments: (token: string, id: string) =>
    request<DocCommentRead[]>(`/documents/${id}/comments`, {}, token),

  addComment: (token: string, id: string, content: string) =>
    request<DocCommentRead>(`/documents/${id}/comments`, { method: "POST", body: JSON.stringify({ content }) }, token),

  deleteComment: (token: string, id: string, commentId: string) =>
    request<void>(`/documents/${id}/comments/${commentId}`, { method: "DELETE" }, token),

  // Expiry dashboard
  expiry: (token: string) =>
    request<ExpiryDashboard>("/documents/expiry", {}, token),

  // Bulk download
  bulkDownload: (token: string, ids: string[]) =>
    fetch(`${API_BASE}/documents/bulk-download`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ document_ids: ids }),
    }),

  // Categories
  listCategories: (token: string) =>
    request<DocCategoryRead[]>("/documents/categories", {}, token),

  createCategory: (token: string, data: { name: string; slug: string; color?: string; icon?: string }) =>
    request<DocCategoryRead>("/documents/categories", { method: "POST", body: JSON.stringify(data) }, token),

  updateCategory: (token: string, id: string, data: { name?: string; color?: string; icon?: string }) =>
    request<DocCategoryRead>(`/documents/categories/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token),

  deleteCategory: (token: string, id: string) =>
    request<void>(`/documents/categories/${id}`, { method: "DELETE" }, token),
};

export interface PublicDocumentRead {
  id: string;
  name: string;
  original_filename: string;
  file_url: string;
  mime_type: string;
  file_size: number;
  description: string | null;
  thumbnail_url: string | null;
  access_type: string;
}

// ── Worker Hub types ────────────────────────────────────────────────────────

export interface WorkerModules {
  timetracking: boolean;
  schedule: boolean;
  messages: boolean;
  documents: boolean;
  absences: boolean;
  equipment: boolean;
  tasks: boolean;
  payroll: boolean;
  tickets: boolean;
  profile_selfservice: boolean;
}

export interface WorkerMeRead {
  id: string;
  full_name: string | null;
  email: string;
  active_modules: WorkerModules;
  employment_type: string;
  tenant_id: string;
}

export interface WorkerSettingsRead {
  id: string;
  user_id: string;
  tenant_id: string;
  is_active: boolean;
  employment_type: string;
  max_weekly_hours: number | null;
  hourly_rate: string | null;
  active_modules: Record<string, boolean>;
  internal_note: string | null;
  assigned_manager_id: string | null;
  assigned_team_id: string | null;
  activated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkerSettingsUpdate {
  is_active?: boolean;
  employment_type?: string;
  max_weekly_hours?: number;
  active_modules?: Record<string, boolean>;
  internal_note?: string;
  assigned_manager_id?: string;
  assigned_team_id?: string | null;
}

export interface WorkerListRead {
  id: string;
  full_name: string | null;
  email: string;
  is_active_user: boolean;
  settings: WorkerSettingsRead | null;
  employment_type: string | null;
  modules_enabled: number;
  manager: { id: string; full_name: string | null; email: string } | null;
  team: { id: string; name: string } | null;
}

export interface WorkerActivateRequest {
  user_id: string;
  employment_type?: string;
  max_weekly_hours?: number;
  hourly_rate?: number;
  assigned_manager_id?: string;
  internal_note?: string;
}

export interface HireFromApplicationRequest {
  application_id: string;
  employment_type?: string;
  max_weekly_hours?: number;
  hourly_rate?: number;
  assigned_manager_id?: string;
  internal_note?: string;
}

export interface WorkerBulkRequest {
  user_ids: string[];
  action: "activate" | "deactivate" | "assign_manager";
  assigned_manager_id?: string;
}

// ── Worker API (worker-facing) ──────────────────────────────────────────────

export const workerApi = {
  me: (token: string) =>
    request<WorkerMeRead>("/worker/me", {}, token),

  modules: (token: string) =>
    request<WorkerModules>("/worker/modules", {}, token),
};

// ── Worker Management API (HR/Recruiter-facing) ─────────────────────────────

export const workerManagementApi = {
  list: (token: string) =>
    request<WorkerListRead[]>("/zeitarbeit/workers", {}, token),

  get: (token: string, workerId: string) =>
    request<WorkerListRead>(`/zeitarbeit/workers/${workerId}`, {}, token),

  searchCandidate: (token: string, email: string) =>
    request<{ id: string; email: string; full_name: string | null }>(
      `/zeitarbeit/workers/search-candidate?email=${encodeURIComponent(email)}`,
      {},
      token,
    ),

  activate: (token: string, data: WorkerActivateRequest) =>
    request<WorkerListRead>("/zeitarbeit/workers/activate", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  updateSettings: (token: string, workerId: string, data: WorkerSettingsUpdate) =>
    request<WorkerSettingsRead>(`/zeitarbeit/workers/${workerId}/settings`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }, token),

  bulk: (token: string, data: WorkerBulkRequest) =>
    request<{ affected: number; action: string }>("/zeitarbeit/workers/bulk", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  deactivate: (token: string, workerId: string) =>
    request<void>(`/zeitarbeit/workers/${workerId}`, { method: "DELETE" }, token),

  /** End of hiring pipeline: application → 'offer' + worker activation in one step. */
  hireFromApplication: (token: string, data: HireFromApplicationRequest) =>
    request<WorkerListRead>("/zeitarbeit/workers/hire-from-application", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),
};

// ── Time Tracking Types ──────────────────────────────────────────────────────

export interface TimeEntryRead {
  id: string;
  worker_id: string;
  entry_date: string;          // ISO date "YYYY-MM-DD"
  clock_in: string;            // ISO datetime
  clock_out: string | null;
  break_minutes: number;
  net_minutes: number | null;
  status: "draft" | "submitted" | "approved" | "rejected" | "correction_requested";
  location_note: string | null;
  project_code: string | null;
  cost_center: string | null;
  worker_note: string | null;
  rejection_note: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TimeEntrySummary {
  approved_minutes: number;
  submitted_minutes: number;
  draft_minutes: number;
  total_entries: number;
}

export interface PendingEntryRead extends TimeEntryRead {
  worker_name: string | null;
  worker_email: string;
}

export interface TimeClockInRequest {
  location_note?: string;
  project_code?: string;
  cost_center?: string;
  worker_note?: string;
  clock_in?: string;  // defaults to now on backend
}

export interface TimeClockOutRequest {
  clock_out: string;
  break_minutes?: number;
}

export interface TimeCorrectionRequest {
  new_clock_in?: string;
  new_clock_out?: string;
  new_break_minutes?: number;
  reason: string;
}

export interface TimeApprovalDecision {
  action: "approve" | "reject";
  note?: string;
}

export interface TimeBulkDecision {
  entry_ids: string[];
  action: "approve" | "reject";
  note?: string;
}

// ── Time Tracking API (worker-facing) ────────────────────────────────────────

export const timeApi = {
  list: (token: string, month?: string, status?: string) => {
    const params = new URLSearchParams();
    if (month) params.set("month", month);
    if (status) params.set("status", status);
    const qs = params.toString();
    return request<TimeEntryRead[]>(`/worker/time${qs ? `?${qs}` : ""}`, {}, token);
  },

  summary: (token: string, month?: string) => {
    const qs = month ? `?month=${encodeURIComponent(month)}` : "";
    return request<TimeEntrySummary>(`/worker/time/summary${qs}`, {}, token);
  },

  clockIn: (token: string, data: TimeClockInRequest) =>
    request<TimeEntryRead>("/worker/time", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  clockOut: (token: string, entryId: string, data: TimeClockOutRequest) =>
    request<TimeEntryRead>(`/worker/time/${entryId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }, token),

  submit: (token: string, entryId: string) =>
    request<TimeEntryRead>(`/worker/time/${entryId}/submit`, {
      method: "POST",
    }, token),

  requestCorrection: (token: string, entryId: string, data: TimeCorrectionRequest) =>
    request<TimeEntryRead>(`/worker/time/${entryId}/correction`, {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  get: (token: string, entryId: string) =>
    request<TimeEntryRead>(`/worker/time/${entryId}`, {}, token),

  export: (token: string, month?: string, workerId?: string) => {
    const params = new URLSearchParams();
    if (month) params.set("month", month);
    if (workerId) params.set("worker_id", workerId);
    const qs = params.toString();
    return request<{ rows: Record<string, string | number | null>[] }>(
      `/worker/time/export${qs ? `?${qs}` : ""}`,
      {},
      token,
    );
  },
};

// ── Time Approval API (HR/Recruiter-facing) ──────────────────────────────────

export const timeApprovalApi = {
  pending: (token: string, workerId?: string) => {
    const qs = workerId ? `?worker_id=${encodeURIComponent(workerId)}` : "";
    return request<PendingEntryRead[]>(`/zeitarbeit/time-entries/pending${qs}`, {}, token);
  },

  all: (token: string, params?: { worker_id?: string; month?: string; status?: string }) => {
    const p = new URLSearchParams();
    if (params?.worker_id) p.set("worker_id", params.worker_id);
    if (params?.month) p.set("month", params.month);
    if (params?.status) p.set("status", params.status);
    const qs = p.toString();
    return request<PendingEntryRead[]>(`/zeitarbeit/time-entries/all${qs ? `?${qs}` : ""}`, {}, token);
  },

  decide: (token: string, entryId: string, data: TimeApprovalDecision) =>
    request<TimeEntryRead>(`/zeitarbeit/time-entries/${entryId}/decision`, {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  bulkDecide: (token: string, data: TimeBulkDecision) =>
    request<{ affected: number; action: string }>("/zeitarbeit/time-entries/bulk-decision", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  corrections: (token: string) =>
    request<PendingEntryRead[]>("/zeitarbeit/time-entries/corrections/pending", {}, token),

  export: (token: string, month?: string, workerId?: string) => {
    const params = new URLSearchParams();
    if (month) params.set("month", month);
    if (workerId) params.set("worker_id", workerId);
    const qs = params.toString();
    return request<Record<string, unknown>[]>(
      `/zeitarbeit/time-entries/export${qs ? `?${qs}` : ""}`,
      {},
      token,
    );
  },
};

// ── Work Assignment Types ─────────────────────────────────────────────────────

export interface WorkAssignmentRead {
  id: string;
  worker_id: string;
  tenant_id: string;
  created_by: string | null;
  start_date: string;
  end_date: string;
  shift_start: string | null;
  shift_end: string | null;
  customer_company: string | null;
  location: string | null;
  role_description: string | null;
  notes: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface AssignmentWithWorker extends WorkAssignmentRead {
  worker_name: string | null;
  worker_email: string;
  customer: string | null;
  shift: string | null;
  activity: string | null;
}

export interface WorkAssignmentCreate {
  worker_id: string;
  start_date: string;
  end_date: string;
  shift_start?: string;
  shift_end?: string;
  customer_company?: string;
  location?: string;
  role_description?: string;
  notes?: string;
  status?: string;
}

export interface WorkAssignmentUpdate {
  start_date?: string;
  end_date?: string;
  shift_start?: string | null;
  shift_end?: string | null;
  customer_company?: string | null;
  location?: string | null;
  role_description?: string | null;
  notes?: string | null;
  status?: string;
}

// ── Worker Schedule API (worker-facing) ───────────────────────────────────────

export const scheduleApi = {
  list: (token: string, month?: string, upcoming?: boolean) => {
    const p = new URLSearchParams();
    if (month) p.set("month", month);
    if (upcoming) p.set("upcoming", "true");
    const qs = p.toString();
    return request<WorkAssignmentRead[]>(`/worker/schedule${qs ? `?${qs}` : ""}`, {}, token);
  },

  get: (token: string, assignmentId: string) =>
    request<WorkAssignmentRead>(`/worker/schedule/${assignmentId}`, {}, token),
};

// ── Assignments API (HR-facing) ───────────────────────────────────────────────

export const assignmentsApi = {
  list: (token: string, params?: { month?: string; worker_id?: string; status?: string }) => {
    const p = new URLSearchParams();
    if (params?.month) p.set("month", params.month);
    if (params?.worker_id) p.set("worker_id", params.worker_id);
    if (params?.status) p.set("status", params.status);
    const qs = p.toString();
    return request<AssignmentWithWorker[]>(`/zeitarbeit/assignments${qs ? `?${qs}` : ""}`, {}, token);
  },

  create: (token: string, data: WorkAssignmentCreate) =>
    request<AssignmentWithWorker>("/zeitarbeit/assignments", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  get: (token: string, id: string) =>
    request<AssignmentWithWorker>(`/zeitarbeit/assignments/${id}`, {}, token),

  update: (token: string, id: string, data: WorkAssignmentUpdate) =>
    request<AssignmentWithWorker>(`/zeitarbeit/assignments/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }, token),

  delete: (token: string, id: string) =>
    request<void>(`/zeitarbeit/assignments/${id}`, { method: "DELETE" }, token),

  bulkStatus: (token: string, assignment_ids: string[], status: string) =>
    request<{ affected: number; status: string }>("/zeitarbeit/assignments/bulk-status", {
      method: "POST",
      body: JSON.stringify({ assignment_ids, status }),
    }, token),
};

// ── Teams Types ───────────────────────────────────────────────────────────────

export interface TeamMemberRead {
  id: string;
  team_id: string;
  user_id: string;
  role: string;
  joined_at: string;
  full_name: string | null;
  email: string;
}

export interface TeamRead {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  parent_team_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  member_count: number;
}

export interface TeamWithMembers extends TeamRead {
  members: TeamMemberRead[];
}

export interface TeamCreate {
  name: string;
  description?: string;
  parent_team_id?: string;
}

export interface TeamUpdate {
  name?: string;
  description?: string;
  parent_team_id?: string;
  is_active?: boolean;
}

export interface TeamMemberAdd {
  user_id: string;
  role?: string;
}

export interface MyTeamRead {
  id: string;
  name: string;
  role: string;
  member_count: number;
}

// ── Teams API ─────────────────────────────────────────────────────────────────

export const teamsApi = {
  list: (token: string) =>
    request<TeamRead[]>("/teams", {}, token),

  mine: (token: string) =>
    request<MyTeamRead[]>("/teams/mine", {}, token),

  get: (token: string, teamId: string) =>
    request<TeamWithMembers>(`/teams/${teamId}`, {}, token),

  create: (token: string, data: TeamCreate) =>
    request<TeamWithMembers>("/teams", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  update: (token: string, teamId: string, data: TeamUpdate) =>
    request<TeamWithMembers>(`/teams/${teamId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }, token),

  delete: (token: string, teamId: string) =>
    request<void>(`/teams/${teamId}`, { method: "DELETE" }, token),

  addMember: (token: string, teamId: string, data: TeamMemberAdd) =>
    request<TeamMemberRead>(`/teams/${teamId}/members`, {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  updateMemberRole: (token: string, teamId: string, userId: string, role: string) =>
    request<TeamMemberRead>(`/teams/${teamId}/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }, token),

  removeMember: (token: string, teamId: string, userId: string) =>
    request<void>(`/teams/${teamId}/members/${userId}`, { method: "DELETE" }, token),
};

// ── Messaging Types ───────────────────────────────────────────────────────────

export interface MessageRead {
  id: string;
  thread_id: string;
  sender_id: string;
  sender_name: string | null;
  sender_role: string;
  body: string;
  is_internal_note: boolean;
  created_at: string;
}

export interface ThreadRead {
  id: string;
  tenant_id: string;
  worker_id: string;
  worker_name: string | null;
  worker_email: string;
  assigned_team_id: string | null;
  assigned_team_name: string | null;
  claimed_by: string | null;
  claimed_by_name: string | null;
  subject: string;
  status: string;
  last_message_at: string | null;
  unread_hr: number;
  unread_worker: number;
  created_at: string;
  updated_at: string;
  preview: string;
}

export interface ThreadWithMessages extends ThreadRead {
  messages: MessageRead[];
}

export interface NewThreadRequest {
  subject: string;
  body: string;
  assigned_team_id?: string;
}

// ── Worker Messages API ───────────────────────────────────────────────────────

export const workerMessagesApi = {
  list: (token: string) =>
    request<ThreadRead[]>("/worker/messages", {}, token),

  get: (token: string, threadId: string) =>
    request<ThreadWithMessages>(`/worker/messages/${threadId}`, {}, token),

  create: (token: string, data: NewThreadRequest) =>
    request<ThreadWithMessages>("/worker/messages", {
      method: "POST",
      body: JSON.stringify(data),
    }, token),

  reply: (token: string, threadId: string, body: string) =>
    request<MessageRead>(`/worker/messages/${threadId}/reply`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }, token),
};

// ── HR Messages API ───────────────────────────────────────────────────────────

export const hrMessagesApi = {
  list: (
    token: string,
    params?: { status?: string; team_id?: string; worker_id?: string; unread_only?: boolean },
  ) => {
    const p = new URLSearchParams();
    if (params?.status) p.set("status", params.status);
    if (params?.team_id) p.set("team_id", params.team_id);
    if (params?.worker_id) p.set("worker_id", params.worker_id);
    if (params?.unread_only) p.set("unread_only", "true");
    const qs = p.toString();
    return request<ThreadRead[]>(`/zeitarbeit/messages${qs ? `?${qs}` : ""}`, {}, token);
  },

  get: (token: string, threadId: string) =>
    request<ThreadWithMessages>(`/zeitarbeit/messages/${threadId}`, {}, token),

  reply: (token: string, threadId: string, body: string, is_internal_note = false) =>
    request<MessageRead>(`/zeitarbeit/messages/${threadId}/reply`, {
      method: "POST",
      body: JSON.stringify({ body, is_internal_note }),
    }, token),

  claim: (token: string, threadId: string) =>
    request<ThreadRead>(`/zeitarbeit/messages/${threadId}/claim`, { method: "POST" }, token),

  unclaim: (token: string, threadId: string) =>
    request<ThreadRead>(`/zeitarbeit/messages/${threadId}/unclaim`, { method: "POST" }, token),

  resolve: (token: string, threadId: string) =>
    request<ThreadRead>(`/zeitarbeit/messages/${threadId}/resolve`, { method: "POST" }, token),

  reopen: (token: string, threadId: string) =>
    request<ThreadRead>(`/zeitarbeit/messages/${threadId}/reopen`, { method: "POST" }, token),

  assignTeam: (token: string, threadId: string, teamId: string | null) =>
    request<ThreadRead>(`/zeitarbeit/messages/${threadId}/assign-team`, {
      method: "PATCH",
      body: JSON.stringify({ team_id: teamId }),
    }, token),
};

// ── Absences ──────────────────────────────────────────────────────────────────

export interface AbsenceRead {
  id: string;
  worker_id: string;
  worker_name: string | null;
  worker_email: string;
  tenant_id: string;
  absence_type: string;
  absence_type_label: string;
  start_date: string;
  end_date: string;
  working_days: number;
  worker_note: string | null;
  status: string;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  reviewer_note: string | null;
  certificate_uploaded: boolean;
  created_at: string;
  updated_at: string;
}

export interface AbsenceSummary {
  year: number;
  vacation_days_approved: number;
  vacation_days_pending: number;
  sick_days_approved: number;
  total_approved: number;
}

export interface AbsenceCreate {
  absence_type: string;
  start_date: string;
  end_date: string;
  worker_note?: string;
}

export const absencesApi = {
  list: (token: string, params?: { year?: number; status?: string }) => {
    const p = new URLSearchParams();
    if (params?.year) p.set("year", String(params.year));
    if (params?.status) p.set("status", params.status);
    const qs = p.toString();
    return request<AbsenceRead[]>(`/worker/absences${qs ? `?${qs}` : ""}`, {}, token);
  },

  summary: (token: string, year?: number) => {
    const qs = year ? `?year=${year}` : "";
    return request<AbsenceSummary>(`/worker/absences/summary${qs}`, {}, token);
  },

  create: (token: string, body: AbsenceCreate) =>
    request<AbsenceRead>("/worker/absences", {
      method: "POST",
      body: JSON.stringify(body),
    }, token),

  get: (token: string, id: string) =>
    request<AbsenceRead>(`/worker/absences/${id}`, {}, token),

  cancel: (token: string, id: string) =>
    request<void>(`/worker/absences/${id}`, { method: "DELETE" }, token),
};

export const hrAbsencesApi = {
  list: (
    token: string,
    params?: { status?: string; worker_id?: string; year?: number; absence_type?: string },
  ) => {
    const p = new URLSearchParams();
    if (params?.status) p.set("status", params.status);
    if (params?.worker_id) p.set("worker_id", params.worker_id);
    if (params?.year) p.set("year", String(params.year));
    if (params?.absence_type) p.set("absence_type", params.absence_type);
    const qs = p.toString();
    return request<AbsenceRead[]>(`/zeitarbeit/absences${qs ? `?${qs}` : ""}`, {}, token);
  },

  get: (token: string, id: string) =>
    request<AbsenceRead>(`/zeitarbeit/absences/${id}`, {}, token),

  review: (token: string, id: string, action: "approve" | "reject", reviewer_note?: string) =>
    request<AbsenceRead>(`/zeitarbeit/absences/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ action, reviewer_note }),
    }, token),

  cancel: (token: string, id: string) =>
    request<void>(`/zeitarbeit/absences/${id}`, { method: "DELETE" }, token),
};

// ── Worker Documents ──────────────────────────────────────────────────────────

export interface DocCategoryRead {
  id: string;
  name: string;
  slug: string;
  color: string;
  icon: string;
  sort_order: number;
}

export interface WorkerDocRead {
  id: string;
  name: string;
  original_filename: string;
  file_url: string;
  mime_type: string;
  file_size: number;
  description: string | null;
  tags: string[] | null;
  category_id: string | null;
  category: DocCategoryRead | null;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export const workerDocsApi = {
  list: (token: string, category_id?: string) => {
    const qs = category_id ? `?category_id=${category_id}` : "";
    return request<WorkerDocRead[]>(`/worker/documents${qs}`, {}, token);
  },

  get: (token: string, id: string) =>
    request<WorkerDocRead>(`/worker/documents/${id}`, {}, token),
};

// ── Equipment ─────────────────────────────────────────────────────────────────

export interface EquipmentItemRead {
  id: string;
  tenant_id: string;
  name: string;
  category: string;
  serial_number: string | null;
  asset_tag: string | null;
  status: string;
  condition: string;
  description: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface EquipmentAssignmentRead {
  id: string;
  equipment_item_id: string;
  worker_id: string;
  tenant_id: string;
  assigned_by: string | null;
  assigned_at: string;
  returned_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  item: EquipmentItemRead | null;
  worker_name: string | null;
  worker_email: string;
  assigned_by_name: string | null;
}

export interface EquipmentItemCreate {
  name: string;
  category?: string;
  serial_number?: string;
  asset_tag?: string;
  condition?: string;
  description?: string;
  notes?: string;
}

export interface AssignItemRequest {
  worker_id: string;
  assigned_at: string;
  notes?: string;
}

export const workerEquipmentApi = {
  list: (token: string) =>
    request<EquipmentAssignmentRead[]>("/worker/equipment", {}, token),

  get: (token: string, id: string) =>
    request<EquipmentAssignmentRead>(`/worker/equipment/${id}`, {}, token),
};

export const hrEquipmentApi = {
  listItems: (token: string, params?: { status?: string; category?: string }) => {
    const p = new URLSearchParams();
    if (params?.status) p.set("status", params.status);
    if (params?.category) p.set("category", params.category);
    const qs = p.toString();
    return request<EquipmentItemRead[]>(`/zeitarbeit/equipment${qs ? `?${qs}` : ""}`, {}, token);
  },

  createItem: (token: string, body: EquipmentItemCreate) =>
    request<EquipmentItemRead>("/zeitarbeit/equipment", {
      method: "POST",
      body: JSON.stringify(body),
    }, token),

  updateItem: (token: string, id: string, body: Partial<EquipmentItemCreate & { status: string }>) =>
    request<EquipmentItemRead>(`/zeitarbeit/equipment/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }, token),

  deleteItem: (token: string, id: string) =>
    request<void>(`/zeitarbeit/equipment/${id}`, { method: "DELETE" }, token),

  listAssignments: (token: string, params?: { worker_id?: string; active_only?: boolean }) => {
    const p = new URLSearchParams();
    if (params?.worker_id) p.set("worker_id", params.worker_id);
    if (params?.active_only !== undefined) p.set("active_only", String(params.active_only));
    const qs = p.toString();
    return request<EquipmentAssignmentRead[]>(`/zeitarbeit/equipment/assignments/list${qs ? `?${qs}` : ""}`, {}, token);
  },

  assign: (token: string, itemId: string, body: AssignItemRequest) =>
    request<EquipmentAssignmentRead>(`/zeitarbeit/equipment/${itemId}/assign`, {
      method: "POST",
      body: JSON.stringify(body),
    }, token),

  returnItem: (token: string, itemId: string, returned_at: string, notes?: string) =>
    request<EquipmentAssignmentRead>(`/zeitarbeit/equipment/${itemId}/return`, {
      method: "POST",
      body: JSON.stringify({ returned_at, notes }),
    }, token),
};

// ── Tasks ─────────────────────────────────────────────────────────────────────

export interface TaskRead {
  id: string;
  tenant_id: string;
  assigned_to: string | null;
  assigned_agent_id: string | null;
  assigned_by: string | null;
  title: string;
  description: string | null;
  due_date: string | null;
  priority: string;
  status: string;
  completed_at: string | null;
  worker_note: string | null;
  created_at: string;
  updated_at: string;
  assigned_to_name: string | null;
  assigned_to_email: string;
  assigned_by_name: string | null;
}

export interface TaskCreate {
  assigned_to: string;
  title: string;
  description?: string;
  due_date?: string;
  priority?: string;
}

export const workerTasksApi = {
  list: (token: string, status?: string) => {
    const qs = status ? `?status=${status}` : "";
    return request<TaskRead[]>(`/worker/tasks${qs}`, {}, token);
  },

  updateStatus: (token: string, id: string, status: string, worker_note?: string) =>
    request<TaskRead>(`/worker/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status, worker_note }),
    }, token),
};

export const hrTasksApi = {
  list: (token: string, params?: { worker_id?: string; status?: string; priority?: string }) => {
    const p = new URLSearchParams();
    if (params?.worker_id) p.set("worker_id", params.worker_id);
    if (params?.status) p.set("status", params.status);
    if (params?.priority) p.set("priority", params.priority);
    const qs = p.toString();
    return request<TaskRead[]>(`/zeitarbeit/tasks${qs ? `?${qs}` : ""}`, {}, token);
  },

  create: (token: string, body: TaskCreate) =>
    request<TaskRead>("/zeitarbeit/tasks", {
      method: "POST",
      body: JSON.stringify(body),
    }, token),

  update: (token: string, id: string, body: Partial<TaskCreate & { status: string }>) =>
    request<TaskRead>(`/zeitarbeit/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }, token),

  delete: (token: string, id: string) =>
    request<void>(`/zeitarbeit/tasks/${id}`, { method: "DELETE" }, token),
};

// ── Payroll ───────────────────────────────────────────────────────────────────

export interface PayStubRead {
  id: string;
  tenant_id: string;
  worker_id: string;
  created_by: string | null;
  period_year: number;
  period_month: number;
  period_label: string;
  gross_cents: number;
  net_cents: number;
  tax_cents: number;
  social_security_cents: number;
  hours_worked: number | null;
  overtime_hours: number | null;
  document_url: string | null;
  notes: string | null;
  status: string;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  worker_name: string | null;
  worker_email: string;
}

export interface PayStubCreate {
  worker_id: string;
  period_year: number;
  period_month: number;
  gross_cents: number;
  net_cents: number;
  tax_cents?: number;
  social_security_cents?: number;
  hours_worked?: number;
  overtime_hours?: number;
  document_url?: string;
  notes?: string;
}

export const workerPayrollApi = {
  list: (token: string, year?: number) => {
    const qs = year ? `?year=${year}` : "";
    return request<PayStubRead[]>(`/worker/payroll${qs}`, {}, token);
  },

  get: (token: string, id: string) =>
    request<PayStubRead>(`/worker/payroll/${id}`, {}, token),
};

export const hrPayrollApi = {
  list: (token: string, params?: { worker_id?: string; year?: number; status?: string }) => {
    const p = new URLSearchParams();
    if (params?.worker_id) p.set("worker_id", params.worker_id);
    if (params?.year) p.set("year", String(params.year));
    if (params?.status) p.set("status", params.status);
    const qs = p.toString();
    return request<PayStubRead[]>(`/zeitarbeit/payroll${qs ? `?${qs}` : ""}`, {}, token);
  },

  create: (token: string, body: PayStubCreate) =>
    request<PayStubRead>("/zeitarbeit/payroll", {
      method: "POST",
      body: JSON.stringify(body),
    }, token),

  update: (token: string, id: string, body: Partial<PayStubCreate>) =>
    request<PayStubRead>(`/zeitarbeit/payroll/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }, token),

  publish: (token: string, id: string) =>
    request<PayStubRead>(`/zeitarbeit/payroll/${id}/publish`, { method: "POST" }, token),

  delete: (token: string, id: string) =>
    request<void>(`/zeitarbeit/payroll/${id}`, { method: "DELETE" }, token),
};

// ── Worker Profile ────────────────────────────────────────────────────────────

export interface WorkerProfileRead {
  user_id: string;
  email: string;
  full_name: string | null;
  phone: string | null;
  address_street: string | null;
  address_city: string | null;
  address_zip: string | null;
  address_country: string | null;
  date_of_birth: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  iban: string | null;
  avatar_url: string | null;
  employment_type: string;
  is_active: boolean;
}

export interface WorkerProfileUpdate {
  full_name?: string;
  phone?: string;
  address_street?: string;
  address_city?: string;
  address_zip?: string;
  address_country?: string;
  date_of_birth?: string;
  emergency_contact_name?: string;
  emergency_contact_phone?: string;
  iban?: string;
  avatar_url?: string;
}

export const workerProfileApi = {
  get: (token: string) =>
    request<WorkerProfileRead>("/worker/profile", {}, token),

  update: (token: string, body: WorkerProfileUpdate) =>
    request<WorkerProfileRead>("/worker/profile", {
      method: "PATCH",
      body: JSON.stringify(body),
    }, token),

  changePassword: (token: string, current_password: string, new_password: string) =>
    request<void>("/worker/profile/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }, token),
};

// ── Candidate Interview API ───────────────────────────────────────────────────

export interface CandidateInterviewRead {
  id: string;
  application_id: string;
  job_title: string;
  scheduled_at: string;
  status: string;
  meeting_url: string | null;
}

export const candidateApi = {
  listInterviews: (token: string): Promise<CandidateInterviewRead[]> =>
    request<CandidateInterviewRead[]>("/applications/my-interviews", {}, token),

  respondInterview: (token: string, applicationId: string, newStatus: "confirmed" | "declined") =>
    request<void>(
      `/applications/${applicationId}/interview`,
      { method: "PATCH", body: JSON.stringify({ status: newStatus }) },
      token,
    ),
};
