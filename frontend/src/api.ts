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

export const searchCards = async (
  query: string,
  limit: number = 10,
  offset: number = 0
): Promise<CardMatch[]> => {
  if (!query || query.length < 2) return []
  const response = await api.get<CardMatch[]>('/suggest-names', {
    params: { q: query, limit, offset },
  })
  return response.data
}

export const getCard = async (id: string): Promise<Card> => {
  const response = await api.get<Card>(`/card/${id}`)
  return response.data
}

export const getSimilarCards = async (
  id: string,
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
    if (filters.rarity) params.rarity = filters.rarity
    if (filters.matchMode) params.match_mode = filters.matchMode
    if (filters.colorFeature) params.color_feature = filters.colorFeature
  }

  const response = await api.get<SimilarCard[]>(`/similar-cards/${id}`, {
    params,
  })
  return response.data
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
    if (filters.rarity) params.rarity = filters.rarity
    if (filters.matchMode) params.match_mode = filters.matchMode
    if (filters.colorFeature) params.color_feature = filters.colorFeature
  }

  const response = await api.get<SimilarCard[]>('/search-oracle', {
    params,
  })
  return response.data
}

export const getApiHealth = async (): Promise<{ status: string }> => {
  const response = await api.get('/health')
  return response.data
}

export const getApiVersion = async (): Promise<{ version: string }> => {
  const response = await api.get('/version')
  return response.data
}
