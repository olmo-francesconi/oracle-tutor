import { useEffect } from 'react'
import type { RefObject } from 'react'
import { buildClearedState } from './searchShellState'
import { readSearchStateFromUrl, writeSearchStateToUrl } from '../lib/urlState'
import type { SearchShellState } from '../types/ui'

type RunSearch = (query: string, filters: SearchShellState['filters']) => void
type RunCardSearch = (oracleId: string, faceIx: number, name: string, filters: SearchShellState['filters']) => void
type SetState = React.Dispatch<React.SetStateAction<SearchShellState>>

export function useUrlSync(
  state: SearchShellState,
  skipRef: RefObject<boolean>,
  activeSearchRequestRef: RefObject<AbortController | null>,
  activeLoadMoreRequestRef: RefObject<AbortController | null>,
  setState: SetState,
  runSearch: RunSearch,
  runCardSearch: RunCardSearch,
): void {
  useEffect(() => {
    const handlePopState = () => {
      const nextState = readSearchStateFromUrl()

      if (nextState.pinnedCard) {
        skipRef.current = true
        void runCardSearch(nextState.pinnedCard.oracle_id, nextState.pinnedCard.face_ix, '', nextState.filters)
        return
      }

      const nextQuery = nextState.query

      if (!nextQuery) {
        activeSearchRequestRef.current?.abort()
        activeLoadMoreRequestRef.current?.abort()
        skipRef.current = true
        setState((current) => buildClearedState(current))
        return
      }

      skipRef.current = true
      setState((current) => ({
        ...current,
        draftQuery: nextQuery,
        filters: nextState.filters,
        error: null,
      }))

      void runSearch(nextQuery, nextState.filters)
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [runCardSearch, runSearch, skipRef, activeSearchRequestRef, activeLoadMoreRequestRef, setState])

  useEffect(() => {
    if (skipRef.current) {
      skipRef.current = false
      return
    }

    if (state.submittedQuery === null && !state.pinnedCard) return
    writeSearchStateToUrl(state.submittedQuery, state.filters, state.pinnedCard)
  }, [state.filters, state.submittedQuery, state.pinnedCard, skipRef])
}
