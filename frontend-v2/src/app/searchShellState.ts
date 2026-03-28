import type { FilterState, SimilarCardsPage } from '../types/api'
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
  }
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

export function isApiDownError(error: unknown): boolean {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return true
  }

  if (!(error instanceof Error)) {
    return false
  }

  if (error.name === 'AbortError') {
    return false
  }

  const message = error.message.toLowerCase()
  if (message.includes('failed to fetch') || message.includes('network')) {
    return true
  }

  return /request failed: (502|503|504)\b/.test(message)
}

export function getApiDownMessage(error: unknown): string {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return 'You appear to be offline. Reconnect, then retry the connection.'
  }

  if (error instanceof Error && /request failed: 503\b/i.test(error.message)) {
    return 'The API is up but not accepting requests right now. Give it a second, then retry the connection.'
  }

  return 'The API is not responding right now. Give it a second, then retry the connection.'
}
