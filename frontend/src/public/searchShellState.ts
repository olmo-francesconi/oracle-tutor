import type { FilterState, SimilarCardsPage } from '../types/api'
import type { PinnedCard, SearchShellState } from '../types/ui'

export function buildSearchLoadingState(
  current: SearchShellState,
  query: string,
  filters: FilterState
): SearchShellState {
  return {
    ...current,
    submittedQuery: query,
    pinnedCard: null,
    filters,
    error: null,
    results: [],
    hasMore: false,
    isLoading: true,
    isLoadingMore: false,
  }
}

export function buildCardLoadingState(
  current: SearchShellState,
  card: PinnedCard,
  filters: FilterState
): SearchShellState {
  return {
    ...current,
    draftQuery: card.name || current.draftQuery,
    submittedQuery: card.name,
    pinnedCard: card,
    filters,
    error: null,
    results: [],
    hasMore: false,
    isLoading: true,
    isLoadingMore: false,
  }
}

export function buildCardSuccessState(
  current: SearchShellState,
  card: PinnedCard,
  filters: FilterState,
  page: SimilarCardsPage
): SearchShellState {
  return {
    ...current,
    draftQuery: card.name,
    submittedQuery: card.name,
    pinnedCard: card,
    filters,
    error: null,
    results: page.items,
    hasMore: page.has_more,
    isLoading: false,
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
    pinnedCard: null,
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
    return 'Your device appears to be offline. Reconnect, then retry.'
  }

  if (error instanceof Error) {
    if (error.message.toLowerCase().includes('semantic index not available')) {
      return 'No semantic model is loaded. A model must be registered and promoted before search is available.'
    }

    if (/request failed: 503\b/i.test(error.message)) {
      return 'The API is temporarily unavailable (503). Give it a moment, then retry.'
    }

    if (/request failed: 502\b/i.test(error.message)) {
      return 'The API is unreachable (502 Bad Gateway). Give it a moment, then retry.'
    }

    if (/request failed: 504\b/i.test(error.message)) {
      return 'The API timed out (504 Gateway Timeout). Give it a moment, then retry.'
    }
  }

  return 'Oracle Tutor cannot reach the live catalog right now. Give it a second, then retry the connection.'
}
