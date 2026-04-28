import type { FilterState, SimilarCard } from './api'

export type CardFilterState = FilterState

export type PinnedCard = {
  oracle_id: string
  face_ix: number
  name: string
}

export type SearchShellState = {
  draftQuery: string
  submittedQuery: string | null
  pinnedCard: PinnedCard | null
  filters: CardFilterState
  error: string | null
  results: SimilarCard[]
  hasMore: boolean
  isLoading: boolean
  isLoadingMore: boolean
}
