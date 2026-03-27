import type {
  Card,
  CardMatch,
  FilterState,
  OracleSamples,
  SimilarCard,
  SimilarCardsPage,
} from '../types/api'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'
const SEARCH_CACHE_LIMIT = 40

const cardSearchCache = new Map<string, CardMatch[]>()

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
}

type OracleSearchParams = SimilarCardsParams & {
  q: string
}

type ApiCardMatch = Omit<CardMatch, 'id'>
type ApiCard = Omit<Card, 'id'>
type ApiSimilarCard = Omit<SimilarCard, 'id'>
type ApiSimilarCardsPage = {
  items: ApiSimilarCard[]
  has_more: boolean
}

function buildUrl(path: string, params?: Record<string, string | number | undefined>) {
  const url = new URL(`${API_BASE_URL}${path}`, window.location.origin)

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined) continue
      url.searchParams.set(key, String(value))
    }
  }

  return `${url.pathname}${url.search}`
}

function readCachedCardMatches(key: string): CardMatch[] | null {
  const cached = cardSearchCache.get(key)
  if (!cached) return null

  cardSearchCache.delete(key)
  cardSearchCache.set(key, cached)

  return cached
}

function writeCachedCardMatches(key: string, matches: CardMatch[]) {
  if (cardSearchCache.has(key)) {
    cardSearchCache.delete(key)
  }

  cardSearchCache.set(key, matches)

  if (cardSearchCache.size <= SEARCH_CACHE_LIMIT) return

  const oldestKey = cardSearchCache.keys().next().value
  if (oldestKey) {
    cardSearchCache.delete(oldestKey)
  }
}

async function assertOk<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = ''

    try {
      const body = await response.json()

      if (typeof body === 'string') {
        detail = body
      } else if (body && typeof body === 'object' && 'detail' in body) {
        const nextDetail = body.detail
        detail = typeof nextDetail === 'string' ? nextDetail : JSON.stringify(nextDetail)
      } else {
        detail = JSON.stringify(body)
      }
    } catch {
      try {
        detail = await response.text()
      } catch {
        detail = ''
      }
    }

    throw new Error(`Request failed: ${response.status}${detail ? ` - ${detail}` : ''}`)
  }

  return response.json() as Promise<T>
}

async function getJson<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  signal?: AbortSignal
): Promise<T> {
  const response = await fetch(buildUrl(path, params), {
    method: 'GET',
    signal,
  })

  return assertOk<T>(response)
}

function normalizeCardMatch(card: ApiCardMatch): CardMatch {
  return {
    ...card,
    id: card.scryfall_id ?? '',
  }
}

function normalizeCard(card: ApiCard): Card {
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

function normalizeSimilarCard(card: ApiSimilarCard): SimilarCard {
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

function buildSimilarCardsParams(
  limit: number,
  offset: number,
  filters?: FilterState
): SimilarCardsParams {
  const params: SimilarCardsParams = { limit, offset }

  if (!filters) return params

  if (filters.cardType) params.card_type = filters.cardType
  if (filters.colors) params.colors = filters.colors
  if (filters.format) params.format = filters.format
  if (filters.cmcMin !== undefined) params.cmc_min = filters.cmcMin
  if (filters.cmcMax !== undefined) params.cmc_max = filters.cmcMax
  if (filters.rarities?.length) {
    params.rarity = filters.rarities.map((rarity) => rarity[0]).join('')
  }
  if (filters.matchMode) params.match_mode = filters.matchMode
  if (filters.colorFeature) params.color_feature = filters.colorFeature

  return params
}

export async function searchCards(
  query: string,
  limit: number = 10,
  offset: number = 0,
  signal?: AbortSignal
): Promise<CardMatch[]> {
  if (!query || query.length < 2) return []

  const cacheKey = JSON.stringify([query, limit, offset])
  const cached = readCachedCardMatches(cacheKey)
  if (cached) {
    return cached
  }

  const data = await getJson<ApiCardMatch[]>(
    '/search',
    { q: query, limit, offset },
    signal
  )

  const matches = data.map(normalizeCardMatch)
  writeCachedCardMatches(cacheKey, matches)
  return matches
}

export async function getCard(id: string, signal?: AbortSignal): Promise<Card> {
  const data = await getJson<ApiCard>(`/card/${id}`, undefined, signal)
  return normalizeCard(data)
}

export async function getSimilarCards(
  id: string,
  faceIx: number = 0,
  offset: number = 0,
  limit: number = 24,
  filters?: FilterState,
  signal?: AbortSignal
): Promise<SimilarCardsPage> {
  const data = await getJson<ApiSimilarCardsPage>(
    '/similar-cards',
    {
      ...buildSimilarCardsParams(limit, offset, filters),
      oracle_id: id,
      face_ix: faceIx,
    },
    signal
  )

  return {
    items: data.items.map(normalizeSimilarCard),
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

  const data = await getJson<ApiSimilarCardsPage>('/similar-cards', params, signal)

  return {
    items: data.items.map(normalizeSimilarCard),
    has_more: data.has_more,
  }
}

export async function getOracleSamples(signal?: AbortSignal): Promise<OracleSamples> {
  try {
    return await getJson<OracleSamples>(
      '/oracle-samples',
      { n: 60 },
      signal
    )
  } catch {
    return { texts: [], terms: [] }
  }
}
