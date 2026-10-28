import type { FilterState, SimilarCard } from './api'

/** Tri-state per ability: absent = untouched, plus wanted / unwanted. */
export type AbilityChoice = 'include' | 'exclude'
export type AbilitySelection = Record<number, AbilityChoice>

export type PinnedCard = {
  oracle_id: string
  face_ix: number
  name: string
  abilities?: AbilitySelection
}

export type SearchShellState = {
  draftQuery: string
  submittedQuery: string | null
  pinnedCard: PinnedCard | null
  filters: FilterState
  error: string | null
  results: SimilarCard[]
  hasMore: boolean
  isLoading: boolean
  isLoadingMore: boolean
}
