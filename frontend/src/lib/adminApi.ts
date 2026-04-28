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
import {
  AdminAuthTokenResponseSchema,
  SemanticBaseModelListSchema,
  SemanticDatasetListSchema,
  SemanticJobDetailSchema,
  SemanticJobListSchema,
  SemanticModelListSchema,
  SemanticPromoteAcceptedSchema,
  SemanticTrainOptionsSchema,
} from '../types/schemas'
import type { ZodType } from 'zod'
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

let unauthorizedHandler: (() => void) | null = null

export function setAdminUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

function withAdminHeaders(): Record<string, string> {
  const token = getAdminToken()
  if (!token) return { ...ADMIN_HEADERS }
  return {
    ...ADMIN_HEADERS,
    Authorization: `Bearer ${token}`,
  }
}

async function assertAdminOk<T>(response: Response, schema: ZodType<T>): Promise<T> {
  if (response.status === 401) {
    clearAdminToken()
    unauthorizedHandler?.()
  }
  return assertOk<T>(response, schema)
}

async function getAdminJson<T>(path: string, schema: ZodType<T>, signal?: AbortSignal): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method: 'GET',
    headers: withAdminHeaders(),
    signal,
  })

  return assertAdminOk<T>(response, schema)
}

async function postJson<T>(path: string, schema: ZodType<T>, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    headers: withAdminHeaders(),
    body: JSON.stringify(body),
    signal,
  })

  return assertAdminOk<T>(response, schema)
}

export async function exchangeAdminPasswordForToken(password: string): Promise<AdminAuthTokenResponse> {
  const response = await fetch(buildUrl('/admin/auth/token'), {
    method: 'POST',
    headers: ADMIN_HEADERS,
    body: JSON.stringify({ password }),
  })

  const payload = await assertOk(response, AdminAuthTokenResponseSchema)
  setAdminToken(payload.access_token)
  return payload
}

export async function getAdminSemanticModels(signal?: AbortSignal): Promise<SemanticModelSummary[]> {
  return getAdminJson('/admin/semantic-models', SemanticModelListSchema, signal)
}

export async function getAdminSemanticJobs(signal?: AbortSignal): Promise<SemanticJobSummary[]> {
  return getAdminJson('/admin/semantic-jobs', SemanticJobListSchema, signal)
}

export async function getAdminSemanticBaseModels(signal?: AbortSignal): Promise<SemanticBaseModelOption[]> {
  return getAdminJson('/admin/semantic-base-models', SemanticBaseModelListSchema, signal)
}

export async function getAdminSemanticTrainOptions(signal?: AbortSignal): Promise<SemanticTrainOptions> {
  return getAdminJson('/admin/semantic-train-options', SemanticTrainOptionsSchema, signal)
}

export async function queueSemanticTrainJob(
  payload: SemanticTrainJobCreate,
  signal?: AbortSignal
): Promise<SemanticJobDetail> {
  return postJson('/admin/semantic-jobs/train', SemanticJobDetailSchema, payload, signal)
}

export async function queueSemanticPromotion(
  modelId: string,
  payload: { requested_by: string; embed_batch_size: number },
  signal?: AbortSignal
): Promise<SemanticPromoteAccepted> {
  return postJson(`/admin/semantic-models/${modelId}/promote`, SemanticPromoteAcceptedSchema, payload, signal)
}

export async function getAdminSemanticDatasets(signal?: AbortSignal): Promise<SemanticDatasetSummary[]> {
  return getAdminJson('/admin/semantic-datasets', SemanticDatasetListSchema, signal)
}

export async function queueSemanticDatasetJob(
  payload: SemanticDatasetJobCreate,
  signal?: AbortSignal
): Promise<SemanticJobDetail> {
  return postJson('/admin/semantic-jobs/dataset', SemanticJobDetailSchema, payload, signal)
}
