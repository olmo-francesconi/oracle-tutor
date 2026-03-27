export type CardFilterState = Record<string, never>

export type SearchShellState = {
  draftQuery: string
  submittedQuery: string | null
  filters: CardFilterState
  results: string[]
  hasMore: boolean
  isLoading: boolean
  isLoadingMore: boolean
  selectedCard: string | null
}
