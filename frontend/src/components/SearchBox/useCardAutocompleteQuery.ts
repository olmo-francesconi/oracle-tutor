import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { searchCards } from '../../lib/api'

const DEBOUNCE_MS = 180
const AUTOCOMPLETE_LIMIT = 6

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}

export function useCardAutocompleteQuery(rawValue: string) {
  const trimmed = rawValue.trim()
  const debounced = useDebouncedValue(trimmed, DEBOUNCE_MS)
  const enabled = debounced.length >= 2

  return useQuery({
    queryKey: ['card-autocomplete', debounced],
    queryFn: ({ signal }) => searchCards(debounced, AUTOCOMPLETE_LIMIT, 0, signal),
    enabled,
    // Keep suggestions around for quick re-show; TanStack will dedupe identical
    // keys across focus/blur cycles.
    staleTime: 60_000,
  })
}
