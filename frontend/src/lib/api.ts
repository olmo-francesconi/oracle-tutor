import type { ZodType } from 'zod'
import type {
  Card,
  CardMatch,
  FilterState,
  OracleSamples,
  SimilarCard,
  SimilarCardsPage,
} from '../types/api'
import {
  CardMatchListSchema,
  CardSchema,
  OracleSamplesSchema,
  SimilarCardsPageSchema,
} from '../types/schemas'
import type { AbilitySelection } from '../types/ui'
import {
  encodeAbilityList,
  excludedAbilities,
  includedAbilities,
} from './abilitySelection'
import { encodeCardTypeFilter, encodeFormatFilter } from './filters'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'

type MatchMode = NonNullable<FilterState['matchMode']>

type SimilarCardsParams = {
  limit: number
  offset: number
  card_type?: string
  colors?: string
  format?: string
  cmc_min?: number
  cmc_max?: number
  rarity?: string
  match_mode?: MatchMode
  color_feature?: 'identity' | 'colors'
  ignore_keywords?: string
  include_abilities?: string
  exclude_abilities?: string
}

type OracleSearchParams = SimilarCardsParams & {
  q: string
}

type ApiCardMatch = Omit<CardMatch, 'id'>
type ApiCard = Omit<Card, 'id'>
type ApiSimilarCard = Omit<SimilarCard, 'id'>

export function buildUrl(path: string, params?: Record<string, string | number | undefined>) {
  const url = new URL(`${API_BASE_URL}${path}`, window.location.origin)

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined) continue
      url.searchParams.set(key, String(value))
    }
  }

  return `${url.pathname}${url.search}`
}

export async function assertOk<T>(response: Response, schema: ZodType<T>): Promise<T> {
  if (!response.ok) {
    let detail = ''
    const responseClone = response.clone()

    try {
      const body: unknown = await response.json()

      if (typeof body === 'string') {
        detail = body
      } else if (body && typeof body === 'object' && 'detail' in body) {
        const nextDetail = (body as { detail: unknown }).detail
        detail = typeof nextDetail === 'string' ? nextDetail : JSON.stringify(nextDetail)
      } else {
        detail = JSON.stringify(body)
      }
    } catch {
      try {
        detail = await responseClone.text()
      } catch {
        detail = ''
      }
    }

    throw new Error(`Request failed: ${response.status}${detail ? ` - ${detail}` : ''}`)
  }

  const body: unknown = await response.json()
  const parsed = schema.safeParse(body)
  if (!parsed.success) {
    throw new Error(`Malformed response: ${parsed.error.issues.map((i) => i.message).join(', ')}`)
  }
  return parsed.data
}

async function getJson<T>(
  path: string,
  schema: ZodType<T>,
  params?: Record<string, string | number | undefined>,
  signal?: AbortSignal
): Promise<T> {
  const response = await fetch(buildUrl(path, params), {
    method: 'GET',
    signal,
  })

  return assertOk<T>(response, schema)
}

export function normalizeCardMatch(card: ApiCardMatch): CardMatch {
  return {
    ...card,
    id: card.scryfall_id ?? '',
  }
}

export function normalizeCard(card: ApiCard): Card {
  const primaryFace = card.faces?.[0]

  return {
    ...card,
    id: card.scryfall_id,
    mana_cost: card.mana_cost ?? primaryFace?.mana_cost,
    type_line: card.type_line ?? primaryFace?.type_line,
    oracle_text: card.oracle_text ?? primaryFace?.oracle_text,
    power: card.power ?? primaryFace?.power,
    toughness: card.toughness ?? primaryFace?.toughness,
    colors: card.colors ?? primaryFace?.colors,
  }
}

export function normalizeSimilarCard(card: ApiSimilarCard): SimilarCard {
  const primaryFace = card.faces?.[0]

  return {
    ...card,
    id: card.scryfall_id,
    mana_cost: card.mana_cost ?? primaryFace?.mana_cost,
    type_line: card.type_line ?? primaryFace?.type_line,
    oracle_text: card.oracle_text ?? primaryFace?.oracle_text,
    power: card.power ?? primaryFace?.power,
    toughness: card.toughness ?? primaryFace?.toughness,
    colors: card.colors ?? primaryFace?.colors,
  }
}

export function buildSimilarCardsParams(
  limit: number,
  offset: number,
  filters?: FilterState
): SimilarCardsParams {
  const params: SimilarCardsParams = { limit, offset }

  if (!filters) return params

  if (filters.cardType?.length) params.card_type = encodeCardTypeFilter(filters.cardType)
  if (filters.colors) params.colors = filters.colors
  if (filters.format?.length) params.format = encodeFormatFilter(filters.format)
  if (filters.cmcMin !== undefined) params.cmc_min = filters.cmcMin
  if (filters.cmcMax !== undefined) params.cmc_max = filters.cmcMax
  if (filters.rarities?.length) {
    params.rarity = filters.rarities.map((rarity) => rarity[0]).join('')
  }
  if (filters.matchMode) params.match_mode = filters.matchMode
  if (filters.colorFeature) params.color_feature = filters.colorFeature
  if (filters.ignoreKeywords) params.ignore_keywords = 'true'

  return params
}

export async function searchCards(
  query: string,
  limit: number = 10,
  offset: number = 0,
  signal?: AbortSignal
): Promise<CardMatch[]> {
  if (!query || query.length < 2) return []
  const data = await getJson('/search', CardMatchListSchema, { q: query, limit, offset }, signal)
  return data.map((card) => normalizeCardMatch(card as ApiCardMatch))
}

export async function getCard(id: string, signal?: AbortSignal): Promise<Card> {
  const data = await getJson(`/card/${id}`, CardSchema, undefined, signal)
  return normalizeCard(data as ApiCard)
}

export async function getSimilarCards(
  id: string,
  faceIx: number = 0,
  offset: number = 0,
  limit: number = 24,
  filters?: FilterState,
  abilities?: AbilitySelection,
  signal?: AbortSignal
): Promise<SimilarCardsPage> {
  const data = await getJson(
    '/similar-cards',
    SimilarCardsPageSchema,
    {
      ...buildSimilarCardsParams(limit, offset, filters),
      oracle_id: id,
      face_ix: faceIx,
      include_abilities: encodeAbilityList(includedAbilities(abilities)),
      exclude_abilities: encodeAbilityList(excludedAbilities(abilities)),
    },
    signal
  )

  return {
    items: data.items.map((card) => normalizeSimilarCard(card as ApiSimilarCard)),
    has_more: data.has_more,
  }
}

export async function searchOracleText(
  query: string,
  offset: number = 0,
  limit: number = 24,
  filters?: FilterState,
  signal?: AbortSignal
): Promise<SimilarCardsPage> {
  const params: OracleSearchParams = {
    q: query,
    ...buildSimilarCardsParams(limit, offset, filters),
  }

  const data = await getJson('/similar-cards', SimilarCardsPageSchema, params, signal)

  return {
    items: data.items.map((card) => normalizeSimilarCard(card as ApiSimilarCard)),
    has_more: data.has_more,
  }
}

export async function getOracleSamples(signal?: AbortSignal): Promise<OracleSamples> {
  return getJson('/oracle-samples', OracleSamplesSchema, { n: 60 }, signal)
}
