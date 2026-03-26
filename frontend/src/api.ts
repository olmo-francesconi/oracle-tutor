import axios from 'axios'
import type { Card, CardMatch, FilterState, SimilarCard } from './types'

const API_URL = '/api'

const api = axios.create({
  baseURL: API_URL,
})

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
type OracleSamples = {
  texts: string[]
  terms: string[]
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
  return {
    ...card,
    id: card.scryfall_id,
  }
}

export const searchCards = async (
  query: string,
  limit: number = 10,
  offset: number = 0,
  signal?: AbortSignal
): Promise<CardMatch[]> => {
  if (!query || query.length < 2) return []
  const response = await api.get<ApiCardMatch[]>('/search', {
    params: { q: query, limit, offset },
    signal,
  })
  return response.data.map(normalizeCardMatch)
}

export const getCard = async (id: string): Promise<Card> => {
  const response = await api.get<ApiCard>(`/card/${id}`)
  return normalizeCard(response.data)
}

export const getSimilarCards = async (
  id: string,
  faceIx: number = 0,
  offset: number = 0,
  limit: number = 24,
  filters?: FilterState
): Promise<SimilarCard[]> => {
  const params: SimilarCardsParams = { limit, offset }
  if (filters) {
    if (filters.cardType) params.card_type = filters.cardType
    if (filters.colors) params.colors = filters.colors
    if (filters.format) params.format = filters.format
    if (filters.cmcMin !== undefined) params.cmc_min = filters.cmcMin
    if (filters.cmcMax !== undefined) params.cmc_max = filters.cmcMax
    if (filters.rarities?.length) params.rarity = filters.rarities.map((r) => r[0]).join('')
    if (filters.matchMode) params.match_mode = filters.matchMode
    if (filters.colorFeature) params.color_feature = filters.colorFeature
  }

  const response = await api.get<ApiSimilarCard[]>('/similar-cards', {
    params: { ...params, oracle_id: id, face_ix: faceIx },
  })
  return response.data.map(normalizeSimilarCard)
}

export const searchOracleText = async (
  query: string,
  offset: number = 0,
  limit: number = 24,
  filters?: FilterState
): Promise<SimilarCard[]> => {
  const params: OracleSearchParams = { q: query, limit, offset }
  if (filters) {
    if (filters.cardType) params.card_type = filters.cardType
    if (filters.colors) params.colors = filters.colors
    if (filters.format) params.format = filters.format
    if (filters.cmcMin !== undefined) params.cmc_min = filters.cmcMin
    if (filters.cmcMax !== undefined) params.cmc_max = filters.cmcMax
    if (filters.rarities?.length) params.rarity = filters.rarities.map((r) => r[0]).join('')
    if (filters.matchMode) params.match_mode = filters.matchMode
    if (filters.colorFeature) params.color_feature = filters.colorFeature
  }

  const response = await api.get<ApiSimilarCard[]>('/similar-cards', {
    params,
  })
  return response.data.map(normalizeSimilarCard)
}

export const getOracleSamples = async (): Promise<OracleSamples> => {
  try {
    const response = await api.get<OracleSamples>('/oracle-samples', {
      params: { n: 60 },
    })
    return response.data
  } catch {
    return { texts: [], terms: [] }
  }
}
