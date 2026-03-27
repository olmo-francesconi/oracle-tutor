import type { FilterState, SimilarCard } from './api'

export type CardFilterState = FilterState

export type SearchShellState = {
  draftQuery: string
  submittedQuery: string | null
  filters: CardFilterState
  results: SimilarCard[]
  hasMore: boolean
  isLoading: boolean
  isLoadingMore: boolean
  selectedCard: SimilarCard | null
}
