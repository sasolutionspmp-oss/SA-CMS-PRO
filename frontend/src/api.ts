import axios from "axios";

export interface IntakeFileItem {
  id: string;
  project_id: string;
  rel_path: string;
  mime: string;
  size: number;
  parsed_status: "pending" | "parsed" | "failed";
  updated_at: string;
  error?: string | null;
  page_count?: number | null;
  checksum?: string | null;
  artifact_path?: string | null;
  metadata?: Record<string, unknown>;
  snippet?: string | null;
}

export interface IntakeRunSummary {
  run_id: string;
  project_id: string;
  status: string;
  total: number;
  pending: number;
  parsed: number;
  failed: number;
  started_at: string;
  updated_at: string;
  completed_at?: string | null;
  items: IntakeFileItem[];
}

export interface BootstrapProject {
  id: string;
  code: string;
  name: string;
  status: string;
  stage: string;
  location?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  budget: number;
  eac: number;
  risk_flags: number;
  updated_at: string;
}

export interface BootstrapOrg {
  id: string;
  name: string;
  slug: string;
  role: string;
  projects: BootstrapProject[];
}

export interface BootstrapUser {
  id: string;
  username: string;
  full_name?: string | null;
  roles: string[];
  active_org_id: string;
}

export interface BootstrapResponse {
  user: BootstrapUser;
  orgs: BootstrapOrg[];
  active_project?: BootstrapProject | null;
}

export interface WbsItem {
  id: string;
  code: string;
  description: string;
  confidence: number;
  accepted: boolean;
  metadata: Record<string, unknown>;
  sequence: number;
}

export interface RateEntry {
  id: string;
  category: string;
  csi_code: string | null;
  low_rate: number;
  base_rate: number;
  high_rate: number;
  confidence: number;
  metadata: Record<string, unknown>;
}

export interface ScenarioParameters {
  markups: Record<string, number>;
  crew_rates: Record<string, number>;
  assumptions: Record<string, string>;
}

export interface Scenario {
  id: string;
  org_id: string;
  project_id: string;
  name: string;
  parameters: ScenarioParameters;
  markup_summary: Record<string, number>;
  totals: Record<string, number | Record<string, number>>;
  created_at: string;
  updated_at: string;
}

export interface EstimatorSummary {
  org_id: string;
  project_id: string;
  wbs: WbsItem[];
  rates: RateEntry[];
  scenarios: Scenario[];
}

export interface WbsItemUpdatePayload {
  accepted?: boolean;
  description?: string;
  confidence?: number;
}

export interface ScenarioCreatePayload {
  org_id: string;
  project_id: string;
  name: string;
  parameters?: Partial<ScenarioParameters>;
}

export interface ScenarioAdjustPayload {
  name?: string;
  parameters?: Partial<ScenarioParameters>;
  capture_snapshot?: boolean;
  snapshot_label?: string;
}

export interface TokenPayload {
  access_token: string;
  refresh_token?: string | null;
  expires_in?: number;
  refresh_expires_in?: number;
  org?: {
    id: string;
    name: string;
    slug: string;
    role: string;
  };
}

interface StoredTokens {
  accessToken: string;
  refreshToken?: string;
  expiresAt?: number;
  refreshExpiresAt?: number;
}

const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const TOKEN_STORAGE_KEY = "saCms.authTokens";

function readStoredTokens(): StoredTokens | null {
  try {
    const raw = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as StoredTokens;
    if (parsed.expiresAt && Date.now() >= parsed.expiresAt) {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch (error) {
    console.warn("Failed to parse stored tokens", error);
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    return null;
  }
}

function persistTokens(payload: TokenPayload): StoredTokens {
  const stored: StoredTokens = {
    accessToken: payload.access_token,
    refreshToken: payload.refresh_token ?? undefined,
    expiresAt: payload.expires_in ? Date.now() + payload.expires_in * 1000 : undefined,
    refreshExpiresAt: payload.refresh_expires_in ? Date.now() + payload.refresh_expires_in * 1000 : undefined,
  };
  localStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(stored));
  return stored;
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function getStoredTokens(): StoredTokens | null {
  return readStoredTokens();
}

export function getAccessToken(): string | null {
  const tokens = readStoredTokens();
  return tokens?.accessToken ?? null;
}

const apiClient = axios.create({ baseURL: API_BASE });
const platformClient = axios.create({ baseURL: `${API_BASE}/platform` });

const attachAuthHeader = (config: Parameters<typeof apiClient.interceptors.request.use>[0]) => {
  const token = getAccessToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
};

apiClient.interceptors.request.use(attachAuthHeader);
platformClient.interceptors.request.use(attachAuthHeader);

function handleAxiosError(error: unknown, fallbackMessage: string): Error {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return new Error(detail);
    }
    if (typeof error.message === "string" && error.message.trim()) {
      return new Error(error.message);
    }
  }
  return new Error(fallbackMessage);
}

export async function login(username: string, password: string, orgId?: string): Promise<TokenPayload> {
  const response = await apiClient.post<TokenPayload>("/auth/login", {
    username,
    password,
    org_id: orgId,
  });
  persistTokens(response.data);
  return response.data;
}

export async function refreshToken(token: string): Promise<TokenPayload> {
  const response = await apiClient.post<TokenPayload>("/auth/refresh", {
    refresh_token: token,
  });
  persistTokens(response.data);
  return response.data;
}

export async function fetchBootstrap(): Promise<BootstrapResponse> {
  const response = await apiClient.get<BootstrapResponse>("/bootstrap");
  return response.data;
}

export async function launchIntake(projectId: string, zipPath: string): Promise<IntakeRunSummary> {
  const response = await apiClient.post<IntakeRunSummary>("/intake/launch", {
    project_id: projectId,
    zip_path: zipPath,
  });
  return response.data;
}

export async function fetchIntakeStatus(runId: string): Promise<IntakeRunSummary> {
  const response = await apiClient.get<IntakeRunSummary>("/intake/status", {
    params: { run_id: runId },
  });
  return response.data;
}

export async function downloadExport(projectId: string, kind: "pdf" | "docx" | "xlsx"): Promise<Blob> {
  const response = await apiClient.get(`/export/estimate.${kind}`, {
    params: { project_id: projectId },
    responseType: "blob",
    validateStatus: (status) => status < 500,
  });
  if (response.status >= 400) {
    throw new Error(`Export ${kind} failed (${response.status})`);
  }
  return response.data as Blob;
}

const ESTIMATOR_EMPTY: EstimatorSummary = {
  org_id: "",
  project_id: "",
  wbs: [],
  rates: [],
  scenarios: [],
};

export async function fetchEstimatorSummary(orgId: string, projectId: string): Promise<EstimatorSummary> {
  try {
    const response = await platformClient.get<EstimatorSummary>("/estimator/summary", {
      params: { org_id: orgId, project_id: projectId },
    });
    return response.data;
  } catch (error) {
    console.warn("Estimator summary fallback", error);
    return { ...ESTIMATOR_EMPTY, org_id: orgId, project_id: projectId };
  }
}

export async function mineEstimatorScope(orgId: string, projectId: string): Promise<WbsItem[]> {
  try {
    const response = await platformClient.post<WbsItem[]>("/estimator/mine", {
      org_id: orgId,
      project_id: projectId,
    });
    return response.data;
  } catch (error) {
    throw handleAxiosError(error, "Scope mining failed");
  }
}

export async function updateWbsItem(itemId: string, payload: WbsItemUpdatePayload): Promise<WbsItem> {
  try {
    const response = await platformClient.patch<WbsItem>(`/estimator/wbs/${itemId}`, payload);
    return response.data;
  } catch (error) {
    throw handleAxiosError(error, "Unable to update WBS item");
  }
}

export async function createEstimatorScenario(payload: ScenarioCreatePayload): Promise<Scenario> {
  try {
    const response = await platformClient.post<Scenario>("/estimator/scenarios", payload);
    return response.data;
  } catch (error) {
    throw handleAxiosError(error, "Failed to create scenario");
  }
}

export async function adjustEstimatorScenario(scenarioId: string, payload: ScenarioAdjustPayload): Promise<Scenario> {
  try {
    const response = await platformClient.patch<Scenario>(`/estimator/scenarios/${scenarioId}`, payload);
    return response.data;
  } catch (error) {
    throw handleAxiosError(error, "Failed to update scenario");
  }
}
