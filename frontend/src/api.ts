import axios from 'axios'
import type { Card, CardMatch, FilterState, SimilarCard } from './types'

const API_URL = '/api'

const api = axios.create({
  baseURL: API_URL,
})

export const searchCards = async (query: string): Promise<CardMatch[]> => {
  if (!query || query.length < 2) return []
  const response = await api.get<CardMatch[]>('/suggest-names', {
    params: { q: query, limit: 10 },
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
  const params: any = { limit, offset }
  if (filters) {
    if (filters.cardType) params.card_type = filters.cardType
    if (filters.colors) params.colors = filters.colors
    if (filters.format) params.format = filters.format
    if (filters.cmcMin !== undefined) params.cmc_min = filters.cmcMin
    if (filters.cmcMax !== undefined) params.cmc_max = filters.cmcMax
    if (filters.rarity) params.rarity = filters.rarity
    if (filters.matchMode) params.match_mode = filters.matchMode
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
  const params: any = { q: query, limit, offset }
  if (filters) {
    if (filters.cardType) params.card_type = filters.cardType
    if (filters.colors) params.colors = filters.colors
    if (filters.format) params.format = filters.format
    if (filters.cmcMin !== undefined) params.cmc_min = filters.cmcMin
    if (filters.cmcMax !== undefined) params.cmc_max = filters.cmcMax
    if (filters.rarity) params.rarity = filters.rarity
    if (filters.matchMode) params.match_mode = filters.matchMode
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
