import type { FilterState, SimilarCard, SimilarCardsPage } from '../types/api'
import type { SearchShellState } from '../types/ui'

export function buildSearchLoadingState(
  current: SearchShellState,
  query: string,
  filters: FilterState
): SearchShellState {
  return {
    ...current,
    submittedQuery: query,
    filters,
    error: null,
    results: [],
    hasMore: false,
    isLoading: true,
    isLoadingMore: false,
    selectedCard: null,
  }
}

export function buildSearchSuccessState(
  current: SearchShellState,
  query: string,
  filters: FilterState,
  page: SimilarCardsPage
): SearchShellState {
  return {
    ...current,
    submittedQuery: query,
    filters,
    error: null,
    results: page.items,
    hasMore: page.has_more,
    isLoading: false,
    isLoadingMore: false,
    selectedCard: null,
  }
}

export function buildSearchFailureState(
  current: SearchShellState,
  query: string,
  filters: FilterState,
  error: string
): SearchShellState {
  return {
    ...current,
    submittedQuery: query,
    filters,
    error,
    results: [],
    hasMore: false,
    isLoading: false,
    isLoadingMore: false,
    selectedCard: null,
  }
}

export function buildClearedState(current: SearchShellState): SearchShellState {
  return {
    ...current,
    draftQuery: '',
    submittedQuery: null,
    filters: {},
    error: null,
    results: [],
    hasMore: false,
    isLoading: false,
    isLoadingMore: false,
    selectedCard: null,
  }
}

export function getSelectedCardKey(card: SimilarCard | null): string | null {
  if (!card) return null
  return `${card.id}-${card.face_ix}-${card.image_side}`
}

export function getSearchErrorMessage(error: unknown): string {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return 'You appear to be offline. Reconnect, then run the search again.'
  }

  if (error instanceof Error) {
    if (
      error.name === 'AbortError' ||
      error.message.includes('Failed to fetch') ||
      error.message.toLowerCase().includes('network')
    ) {
      return 'Connection issue. Check your network and try the search again.'
    }

    return error.message
  }

  return 'Something interrupted the search. Try again.'
}
