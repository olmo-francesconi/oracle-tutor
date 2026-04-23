import { useEffect, useRef } from 'react'
import { readSearchStateFromUrl, writeSearchStateToUrl } from '../lib/urlState'
import type { FilterState } from '../types/api'
import type { PinnedCard } from '../types/ui'

type ShellUiState = {
  draftQuery: string
  submittedQuery: string | null
  pinnedCard: PinnedCard | null
  filters: FilterState
}

type SetUi = React.Dispatch<React.SetStateAction<ShellUiState>>

export function useUrlSync(state: ShellUiState, setUi: SetUi): void {
  const skipRef = useRef(state.submittedQuery !== null || state.pinnedCard !== null)

  useEffect(() => {
    const handlePopState = () => {
      const next = readSearchStateFromUrl()
      skipRef.current = true

      if (next.pinnedCard) {
        setUi({
          draftQuery: '',
          submittedQuery: null,
          pinnedCard: { ...next.pinnedCard, name: '' },
          filters: next.filters,
        })
        return
      }

      if (next.query) {
        setUi({
          draftQuery: next.query,
          submittedQuery: next.query,
          pinnedCard: null,
          filters: next.filters,
        })
        return
      }

      setUi({ draftQuery: '', submittedQuery: null, pinnedCard: null, filters: {} })
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [setUi])

  useEffect(() => {
    if (skipRef.current) {
      skipRef.current = false
      return
    }

    if (state.submittedQuery === null && state.pinnedCard === null) return
    writeSearchStateToUrl(state.submittedQuery, state.filters, state.pinnedCard)
  }, [state.filters, state.submittedQuery, state.pinnedCard])
}
