import type {
  AdminAuthTokenResponse,
  SemanticBaseModelOption,
  SemanticDatasetJobCreate,
  SemanticDatasetSummary,
  SemanticJobDetail,
  SemanticJobSummary,
  SemanticModelSummary,
  SemanticPromoteAccepted,
  SemanticTrainJobCreate,
  SemanticTrainOptions,
} from '../types/api'
import { assertOk, buildUrl } from './api'

const ADMIN_HEADERS = { 'Content-Type': 'application/json' }
const ADMIN_TOKEN_STORAGE_KEY = 'admin_token'

export function getAdminToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY)
}

export function clearAdminToken(): void {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY)
}

function setAdminToken(token: string): void {
  if (typeof window === 'undefined') return
  window.sessionStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, token)
}

function withAdminHeaders(): Record<string, string> {
  const token = getAdminToken()
  if (!token) return { ...ADMIN_HEADERS }
  return {
    ...ADMIN_HEADERS,
    Authorization: `Bearer ${token}`,
  }
}

async function assertAdminOk<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    clearAdminToken()
    if (typeof window !== 'undefined') {
      window.location.reload()
    }
  }
  return assertOk<T>(response)
}

async function getAdminJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method: 'GET',
    headers: withAdminHeaders(),
    signal,
  })

  return assertAdminOk<T>(response)
}

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    headers: withAdminHeaders(),
    body: JSON.stringify(body),
    signal,
  })

  return assertAdminOk<T>(response)
}

export async function exchangeAdminPasswordForToken(password: string): Promise<AdminAuthTokenResponse> {
  const response = await fetch(buildUrl('/admin/auth/token'), {
    method: 'POST',
    headers: ADMIN_HEADERS,
    body: JSON.stringify({ password }),
  })

  const payload = await assertOk<AdminAuthTokenResponse>(response)
  setAdminToken(payload.access_token)
  return payload
}

export async function getAdminSemanticModels(signal?: AbortSignal): Promise<SemanticModelSummary[]> {
  return getAdminJson<SemanticModelSummary[]>('/admin/semantic-models', signal)
}

export async function getAdminSemanticJobs(signal?: AbortSignal): Promise<SemanticJobSummary[]> {
  return getAdminJson<SemanticJobSummary[]>('/admin/semantic-jobs', signal)
}

export async function getAdminSemanticBaseModels(signal?: AbortSignal): Promise<SemanticBaseModelOption[]> {
  return getAdminJson<SemanticBaseModelOption[]>('/admin/semantic-base-models', signal)
}

export async function getAdminSemanticTrainOptions(signal?: AbortSignal): Promise<SemanticTrainOptions> {
  return getAdminJson<SemanticTrainOptions>('/admin/semantic-train-options', signal)
}

export async function queueSemanticTrainJob(
  payload: SemanticTrainJobCreate,
  signal?: AbortSignal
): Promise<SemanticJobDetail> {
  return postJson<SemanticJobDetail>('/admin/semantic-jobs/train', payload, signal)
}

export async function queueSemanticPromotion(
  modelId: number,
  payload: { requested_by: string; embed_batch_size: number },
  signal?: AbortSignal
): Promise<SemanticPromoteAccepted> {
  return postJson<SemanticPromoteAccepted>(`/admin/semantic-models/${modelId}/promote`, payload, signal)
}

export async function getAdminSemanticDatasets(signal?: AbortSignal): Promise<SemanticDatasetSummary[]> {
  return getAdminJson<SemanticDatasetSummary[]>('/admin/semantic-datasets', signal)
}

export async function queueSemanticDatasetJob(
  payload: SemanticDatasetJobCreate,
  signal?: AbortSignal
): Promise<SemanticJobDetail> {
  return postJson<SemanticJobDetail>('/admin/semantic-jobs/dataset', payload, signal)
}
