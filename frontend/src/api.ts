import axios from "axios";

export interface IntakeFileItem {
  id: string;
  project_id: string;
  rel_path: string;
  filename: string;
  classification: string;
  mime: string;
  size: number;
  parsed_status: "pending" | "parsed" | "failed";
  updated_at: string | null;
  checksum: string;
  metadata: Record<string, unknown>;
  snippet?: string | null;
  error?: string | null;
  page_count?: number | null;
  artifact_path?: string | null;
}


export interface IntakeRiskFlag {
  file_id: string;
  rel_path: string;
  code: string;
  message: string;
  line: number;
  snippet: string;
  run_id?: string | null;
  project_id?: string | null;
}

export interface IntakeSummaryHighlight {
  file_id: string;
  rel_path: string;
  snippet: string;
  score: number;
  rank: number;
  run_id?: string | null;
  project_id?: string | null;
}

export interface IntakeDocumentEntity {
  id: string;
  document_id: string;
  entity_type: string;
  label: string;
  confidence: number;
  snippet?: string | null;
  metadata: Record<string, unknown>;
}

export interface IntakeDocumentLink {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relation_type: string;
  confidence: number;
  rationale?: string | null;
}

export interface IntakeRunSummary {
  run_id: string;
  project_id: string;
  org_id: string;
  status: string;
  total: number;
  pending: number;
  parsed: number;
  failed: number;
  started_at: string | null;
  updated_at: string | null;
  completed_at?: string | null;
  items: IntakeFileItem[];
  entities: IntakeDocumentEntity[];
  links: IntakeDocumentLink[];
  risk_flags: IntakeRiskFlag[];
  risk_generated_at?: string | null;
  summary_highlights: IntakeSummaryHighlight[];
  summary_generated_at?: string | null;
}

export interface IntakeUploadResponse {
  upload_name: string;
  stored_path: string;
  size_bytes: number;
  checksum: string;
  original_filename: string;
  org_id: string;
  project_id: string;
}

export interface IntakeTelemetry {
  fallback_events: number;
  last_event_at: string | null;
}

export interface LaunchIntakeParams {
  projectId: string;
  zipPath?: string;
  uploadName?: string;
  orgId?: string;
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

interface RawIntakeFile {
  id: string;
  filename: string;
  relative_path: string;
  classification: string;
  parsed_status: "pending" | "parsed" | "failed";
  mime_type: string;
  size_bytes: number;
  checksum: string;
  snippet?: string | null;
  metadata?: Record<string, unknown>;
  updated_at?: string | null;
}

interface RawIntakeDocumentEntity {
  id: string;
  document_id: string;
  entity_type: string;
  label: string;
  confidence: number;
  snippet?: string | null;
  metadata?: Record<string, unknown>;
}

interface RawIntakeStatus {
  run_id: string;
  project_id: string;
  org_id: string;
  status: string;
  total: number;
  pending: number;
  parsed: number;
  failed: number;
  started_at?: string | null;
  completed_at?: string | null;
  files: RawIntakeFile[];
  entities: RawIntakeDocumentEntity[];
  links: IntakeDocumentLink[];
  risk_flags?: IntakeRiskFlag[];
  risk_generated_at?: string | null;
  summary_highlights?: IntakeSummaryHighlight[];
  summary_generated_at?: string | null;
}

function mapIntakeFile(raw: RawIntakeFile, projectId: string): IntakeFileItem {
  const metadata = (raw.metadata ?? {}) as Record<string, unknown>;
  const pageCount = metadata["page_count"];
  const artifactPath = metadata["artifact_path"];
  const errorMessage = metadata["error"];
  return {
    id: raw.id,
    project_id: projectId,
    rel_path: raw.relative_path,
    filename: raw.filename,
    classification: raw.classification,
    mime: raw.mime_type,
    size: raw.size_bytes,
    parsed_status: raw.parsed_status,
    updated_at: raw.updated_at ?? null,
    checksum: raw.checksum,
    metadata,
    snippet: raw.snippet ?? null,
    error: typeof errorMessage === "string" ? errorMessage : null,
    page_count: typeof pageCount === "number" ? pageCount : undefined,
    artifact_path: typeof artifactPath === "string" ? artifactPath : undefined,
  };
}

function mapIntakeEntity(raw: RawIntakeDocumentEntity): IntakeDocumentEntity {
  return {
    id: raw.id,
    document_id: raw.document_id,
    entity_type: raw.entity_type,
    label: raw.label,
    confidence: raw.confidence,
    snippet: raw.snippet ?? null,
    metadata: raw.metadata ?? {},
  };
}

function mapIntakeLink(link: IntakeDocumentLink): IntakeDocumentLink {
  return {
    id: link.id,
    source_entity_id: link.source_entity_id,
    target_entity_id: link.target_entity_id,
    relation_type: link.relation_type,
    confidence: link.confidence,
    rationale: link.rationale ?? null,
  };
}

export function normalizeIntakeStatus(raw: RawIntakeStatus): IntakeRunSummary {
  const items = raw.files.map((file) => mapIntakeFile(file, raw.project_id));
  let updatedAt: string | null = null;
  for (const file of raw.files) {
    if (file.updated_at && (!updatedAt || file.updated_at > updatedAt)) {
      updatedAt = file.updated_at;
    }
  }
  if (!updatedAt) {
    updatedAt = raw.completed_at ?? raw.started_at ?? null;
  }
  const entities = raw.entities.map(mapIntakeEntity);
  const links = raw.links.map(mapIntakeLink);
  return {
    run_id: raw.run_id,
    project_id: raw.project_id,
    org_id: raw.org_id,
    status: raw.status,
    total: raw.total,
    pending: raw.pending,
    parsed: raw.parsed,
    failed: raw.failed,
    started_at: raw.started_at ?? null,
    updated_at: updatedAt,
    completed_at: raw.completed_at ?? null,
    items,
    entities,
    links,
    risk_flags: raw.risk_flags ?? [],
    risk_generated_at: raw.risk_generated_at ?? null,
    summary_highlights: raw.summary_highlights ?? [],
    summary_generated_at: raw.summary_generated_at ?? null,
  };
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

export async function uploadIntakeBundle(
  file: File,
  orgId: string,
  projectId: string,
  options?: { signal?: AbortSignal; onProgress?: (percent: number) => void },
): Promise<IntakeUploadResponse> {
  const formData = new FormData();
  formData.append("org_id", orgId);
  formData.append("project_id", projectId);
  formData.append("file", file);
  const response = await apiClient.post<IntakeUploadResponse>("/intake/uploads", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    signal: options?.signal,
    onUploadProgress: (event) => {
      if (options?.onProgress && event.total) {
        const percent = Math.round((event.loaded / event.total) * 100);
        options.onProgress(percent);
      }
    },
  });
  return response.data;
}

export async function fetchIntakeTelemetry(): Promise<IntakeTelemetry> {
  const response = await apiClient.get<IntakeTelemetry>("/intake/telemetry");
  return response.data;
}
export async function launchIntake(params: LaunchIntakeParams): Promise<IntakeRunSummary> {
  const { projectId, zipPath, uploadName, orgId } = params;
  const payload: Record<string, unknown> = { project_id: projectId };
  if (orgId) {
    payload.org_id = orgId;
  }
  if (zipPath) {
    payload.zip_path = zipPath;
  }
  if (uploadName) {
    payload.upload_name = uploadName;
  }
  const response = await apiClient.post<RawIntakeStatus>("/intake/launch", payload);
  return normalizeIntakeStatus(response.data);
}


export async function fetchIntakeStatus(runId: string): Promise<IntakeRunSummary> {
  const response = await apiClient.get<RawIntakeStatus>("/intake/status", {
    params: { run_id: runId },
  });
  return normalizeIntakeStatus(response.data);
}

export interface IntakeStreamHandlers {
  onUpdate: (summary: IntakeRunSummary) => void;
  onError?: (event: Event | MessageEvent) => void;
}

export function subscribeIntakeStatus(runId: string, handlers: IntakeStreamHandlers): () => void {
  const url = new URL(`${API_BASE}/intake/status/stream`);
  url.searchParams.set("run_id", runId);
  const source = new EventSource(url.toString());

  const handleUpdate = (event: MessageEvent<string>) => {
    try {
      const raw = JSON.parse(event.data) as RawIntakeStatus;
      handlers.onUpdate(normalizeIntakeStatus(raw));
    } catch (error) {
      console.error("Failed to parse intake stream update", error);
      handlers.onError?.(event);
    }
  };

  const handleError = (event: Event) => {
    if (event instanceof MessageEvent && typeof event.data === "string" && event.data) {
      try {
        const payload = JSON.parse(event.data);
        console.error("Intake stream reported error", payload);
      } catch {
        // ignore JSON parse issues for error payloads
      }
    }
    handlers.onError?.(event);
    if (!(event instanceof MessageEvent)) {
      source.close();
    }
  };

  source.addEventListener("update", handleUpdate as unknown as EventListener);
  source.addEventListener("error", handleError as EventListener);

  return () => {
    source.removeEventListener("update", handleUpdate as unknown as EventListener);
    source.removeEventListener("error", handleError as EventListener);
    source.close();
  };
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




